"""Transaction monitoring - FR 5.1.

FR 5.1: "Show a live feed of transactions and flag suspicious activity using
rule-based and velocity-based checks for an analyst to review."

Two families of check, as the requirement names them:

    rule-based      properties of the single transaction (size, round numbers,
                    a recipient the sender has never paid, a brand new account)
    velocity-based  properties of the sender's recent history (count and value
                    in a rolling window, fan-out to many recipients, structuring
                    just under a threshold)

The output is a level and a list of human-readable flags, not a score out of
100.  An analyst reviewing a queue needs to know why something surfaced; an
opaque number tells them nothing and trains them to click through.

This is deliberately not a fraud model.  It is the rule layer that a real
compliance stack puts in front of one, and the SRS asks for exactly that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..enums import RiskLevel, TransactionState
from ..models import Transaction, User

#: A single transfer at or above this USD value is worth an analyst's eye.
LARGE_TRANSFER_USD = Decimal("1000")

#: More than this many transfers in the window is unusual for a consumer.
VELOCITY_COUNT_WINDOW = timedelta(hours=24)
VELOCITY_COUNT_THRESHOLD = 5

#: Aggregate value in the window that warrants review regardless of count.
VELOCITY_VALUE_USD = Decimal("2500")

#: Sending to this many distinct recipients in the window looks like fan-out.
FANOUT_THRESHOLD = 4

#: An account younger than this sending immediately is worth a flag.
NEW_ACCOUNT_AGE = timedelta(hours=24)


def _usd(amount: Decimal) -> Decimal:
    return amount / Decimal(str(settings.mid_market_ngn_per_usd))


def score_transaction(db: Session, tx: Transaction, user: User) -> tuple[RiskLevel, list[str]]:
    """Return a risk level and the reasons behind it.

    Called at authorization, so the level is already on the row by the time it
    reaches the admin console's live feed.
    """
    flags: list[str] = []
    usd_value = _usd(tx.sourceAmount)
    now = datetime.now(UTC)

    # ---- rule-based ------------------------------------------------------
    if usd_value >= LARGE_TRANSFER_USD:
        flags.append(f"Large transfer: ${usd_value:,.0f}")

    limit = Decimal(str(user.limitUsd()))
    if limit > 0 and usd_value >= limit * Decimal("0.9"):
        # Sending just under a limit repeatedly is the classic structuring
        # pattern, and one instance is enough to note.
        flags.append(f"Within 10% of the {user.kycLevel} limit")

    if user.kycLevel.value == "TIER1" and usd_value >= Decimal("150"):
        flags.append("High value relative to verification tier")

    # createdAt is always tz-aware UTC - see models.UtcDateTime.
    if now - user.createdAt < NEW_ACCOUNT_AGE:
        flags.append("Account opened in the last 24 hours")

    if user.isFrozen:
        flags.append("Sender is frozen")

    # ---- velocity-based --------------------------------------------------
    since = now - VELOCITY_COUNT_WINDOW
    recent = (
        db.execute(
            select(Transaction).where(
                Transaction.senderId == user.id,
                Transaction.createdAt >= since,
                Transaction.id != tx.id,
            )
        )
        .scalars()
        .all()
    )

    if len(recent) >= VELOCITY_COUNT_THRESHOLD:
        flags.append(f"{len(recent) + 1} transfers in 24h")

    window_value = sum((_usd(t.sourceAmount) for t in recent), Decimal("0")) + usd_value
    if window_value >= VELOCITY_VALUE_USD:
        flags.append(f"${window_value:,.0f} sent in 24h")

    recipients = {t.recipientMsisdn for t in recent if t.recipientMsisdn}
    recipients.add(tx.recipientMsisdn)
    if len(recipients) >= FANOUT_THRESHOLD:
        flags.append(f"{len(recipients)} distinct recipients in 24h")

    if tx.recipientMsisdn and tx.recipientMsisdn not in {t.recipientMsisdn for t in recent}:
        prior = db.execute(
            select(Transaction).where(
                Transaction.senderId == user.id,
                Transaction.recipientMsisdn == tx.recipientMsisdn,
                Transaction.state == TransactionState.SETTLED,
            )
        ).scalars().first()
        if prior is None and usd_value >= Decimal("300"):
            flags.append("First transfer to this recipient")

    # ---- level -----------------------------------------------------------
    if user.isFrozen or len(flags) >= 3:
        level = RiskLevel.HIGH
    elif flags:
        level = RiskLevel.MEDIUM
    else:
        level = RiskLevel.LOW

    return level, flags


def feed_summary(db: Session) -> dict:
    """Headline numbers for the top of the admin console."""
    now = datetime.now(UTC)
    today = now - timedelta(hours=24)

    rows = (
        db.execute(select(Transaction).where(Transaction.createdAt >= today)).scalars().all()
    )
    settled = [t for t in rows if t.state == TransactionState.SETTLED]
    refunded = [t for t in rows if t.state == TransactionState.REFUNDED]
    failed = [t for t in rows if t.state == TransactionState.FAILED]
    flagged = [t for t in rows if t.riskLevel in (RiskLevel.MEDIUM, RiskLevel.HIGH)]

    volume_usd = sum((_usd(t.sourceAmount) for t in settled), Decimal("0"))

    durations = [
        (t.settledAt - t.createdAt).total_seconds() for t in settled if t.settledAt and t.createdAt
    ]
    durations.sort()

    def pct(p: float) -> float:
        if not durations:
            return 0.0
        idx = min(len(durations) - 1, int(len(durations) * p))
        return round(durations[idx], 1)

    terminal = len(settled) + len(refunded) + len(failed)

    return {
        "transactionsToday": len(rows),
        "settledToday": len(settled),
        "refundedToday": len(refunded),
        "failedToday": len(failed),
        "flaggedToday": len(flagged),
        "volumeUsd": str(volume_usd.quantize(Decimal("0.01"))),
        # NFR 3 is a promise about terminal outcomes: nothing is left stranded.
        "settlementRate": round(len(settled) / terminal * 100, 2) if terminal else 0.0,
        # NFR 1: under 30s typical, under 60s worst case.
        "medianSettlementSeconds": pct(0.5),
        "p95SettlementSeconds": pct(0.95),
        "slaTargetSeconds": 30,
    }
