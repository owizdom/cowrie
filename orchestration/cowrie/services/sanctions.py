"""Sanctions Service - FR 1.3.

FR 1.3: "Check every user against OFAC, UN, and EU sanctions lists at signup
and refresh daily."

The use case diagram makes this an <<include>> of both "Verify identity (KYC)"
and "Initiate & confirm transfer", so it runs at three moments: signup, every
transfer, and on a daily sweep.  All three are implemented; the daily sweep is
driven by the background worker.

About the list
--------------
The seeded list is fictional.  Shipping a copy of the real OFAC SDN, UN
Consolidated or EU Financial Sanctions lists in a student repository would be
both stale within a week and misleading about what has been integrated.  What
is real is the matching logic and the enforcement path: a hit blocks the
transfer at the Authorized state and drives Authorized -> Failed, exactly as the
state machine diagram specifies.

Matching
--------
Normalised token-set comparison rather than exact string equality, because
sanctions screening that only catches perfect spelling catches nothing.  Names
are lowercased, punctuation stripped, and compared by Jaccard similarity over
token sets, with a configurable threshold.  Real screening vendors add
transliteration, phonetic matching and date-of-birth corroboration; those are
out of scope and named here so the gap is visible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SanctionsEntry, SanctionsScreening, User

#: A hit at or above this similarity blocks.  0.85 is deliberately strict: in a
#: demo a false positive is confusing, and the seeded blocked user matches
#: exactly.  A real deployment tunes this down and staffs a review queue for the
#: band between "possible" and "certain".
MATCH_THRESHOLD = 0.85

LISTS = ["OFAC", "UN", "EU"]


@dataclass(slots=True)
class ScreeningResult:
    passed: bool
    matched_name: str = ""
    matched_list: str = ""
    score: float = 0.0
    lists_checked: list[str] | None = None

    @property
    def reason(self) -> str:
        if self.passed:
            return ""
        return (
            f"Sanctions hold: name matches '{self.matched_name}' on the "
            f"{self.matched_list} list at {self.score:.0%} confidence (FR 1.3)"
        )


def _normalise(name: str) -> set[str]:
    cleaned = re.sub(r"[^a-z\s]", " ", name.lower())
    return {tok for tok in cleaned.split() if len(tok) > 1}


def _similarity(a: str, b: str) -> float:
    """Jaccard similarity over name tokens."""
    tokens_a, tokens_b = _normalise(a), _normalise(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


class SanctionsService:
    def screen_name(self, db: Session, full_name: str) -> ScreeningResult:
        """Compare one name against every seeded list."""
        entries = db.execute(select(SanctionsEntry)).scalars().all()

        best_score = 0.0
        best: SanctionsEntry | None = None
        for entry in entries:
            score = _similarity(full_name, entry.fullName)
            if score > best_score:
                best_score, best = score, entry

        if best and best_score >= MATCH_THRESHOLD:
            return ScreeningResult(
                passed=False,
                matched_name=best.fullName,
                matched_list=best.listName,
                score=best_score,
                lists_checked=LISTS,
            )

        return ScreeningResult(passed=True, score=best_score, lists_checked=LISTS)

    def screen_user(
        self,
        db: Session,
        user: User,
        *,
        trigger: str = "TRANSFER",
        transaction_id: str | None = None,
        force_hit: bool = False,
    ) -> ScreeningResult:
        """Screen a user and record the result.

        FR 1.3 requires screening at signup and a daily refresh, so every run is
        persisted with its trigger; the admin console's Sanctions Watch view is
        a read over this table.

        `force_hit` is the demo hook behind DemoScenario.SANCTIONS_HOLD.
        """
        if force_hit:
            result = ScreeningResult(
                passed=False,
                matched_name="Ibrahim Al-Rashid Kone",
                matched_list="OFAC",
                score=0.93,
                lists_checked=LISTS,
            )
        else:
            result = self.screen_name(db, user.fullName or user.email)

        db.add(
            SanctionsScreening(
                userId=user.id,
                transactionId=transaction_id,
                trigger=trigger,
                passed=result.passed,
                listsChecked=result.lists_checked or LISTS,
                matchedName=result.matched_name,
                matchScore=round(result.score * 100, 2),
            )
        )
        db.flush()
        return result

    def daily_refresh(self, db: Session) -> dict:
        """The "refresh daily" half of FR 1.3.

        Re-screens every user, because a list changes under a user who was
        clean yesterday.  Any user who newly matches is frozen, which stops
        their transfers at authorization.
        """
        users = db.execute(select(User)).scalars().all()
        newly_flagged: list[str] = []

        for user in users:
            result = self.screen_user(db, user, trigger="DAILY")
            if not result.passed and not user.isFrozen:
                user.isFrozen = True
                newly_flagged.append(user.id)

        db.flush()
        return {"screened": len(users), "newlyFlagged": newly_flagged}


service = SanctionsService()
