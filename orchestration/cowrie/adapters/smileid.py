"""Smile ID - KYC (simulated).

Stands in for the Smile ID Mobile SDK v10+ (SRS 3.3): liveness detection,
document verification and selfie-to-ID matching across African ID types.

Real integration shape, preserved here:
    job submission -> {"job_id", "result": {"ResultCode", "ConfidenceValue"}}
    signed callback on completion

FR 1.2 requires the check to confirm the person is real and matches the ID, and
that transaction limits scale with the verification level, so this returns both
a liveness verdict and a confidence score.  The score is what the admin review
queue displays next to each submission.

Not simulated: the on-device capture SDK, the signed callback verification, and
the government database lookups behind each ID type.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from dataclasses import dataclass

from ..config import settings
from ..enums import KycIdType, KycLevel


@dataclass(slots=True)
class SmileIdResult:
    job_id: str
    liveness_passed: bool
    confidence: float
    auto_decision: str
    """APPROVE | REVIEW | REJECT - what Smile ID recommends.  Cowrie routes
    anything that is not a clean APPROVE into the human review queue."""
    granted_level: KycLevel
    provider: str = "Smile ID"


#: Which ID types are accepted for which country, and the level each unlocks.
#: FR 1.2 names exactly these five types.
ID_TYPE_RULES: dict[KycIdType, tuple[str, KycLevel]] = {
    KycIdType.NIN: ("NG", KycLevel.TIER2),
    KycIdType.BVN: ("NG", KycLevel.TIER3),
    KycIdType.KENYAN_ID: ("KE", KycLevel.TIER2),
    KycIdType.NIDA: ("TZ", KycLevel.TIER1),
    KycIdType.GHANA_CARD: ("GH", KycLevel.TIER2),
}


class SmileIdAdapter:
    """Simulated identity verification."""

    name = "Smile ID Mobile SDK v10+"
    simulated = True

    async def verify(
        self,
        *,
        id_type: KycIdType,
        id_number: str,
        full_name: str,
        country: str,
    ) -> SmileIdResult:
        """Run a document + liveness check.

        The verdict is derived deterministically from the ID number so the same
        seeded user always gets the same outcome across restarts, and so the
        demo can include a submission that lands in REVIEW rather than every
        one sailing through.
        """
        await asyncio.sleep(settings.scaled(1.8))

        digest = hashlib.sha256(f"{id_type}{id_number}".encode()).digest()
        confidence = 72.0 + (digest[0] / 255.0) * 27.5  # 72.0 .. 99.5
        liveness = digest[1] % 100 != 0  # ~1% liveness failures

        expected_country, level = ID_TYPE_RULES[id_type]
        country_matches = expected_country == country.upper()

        if not liveness:
            decision = "REJECT"
            granted = KycLevel.NONE
        elif not country_matches:
            # A Kenyan ID presented by a Nigerian account is not fraud on its
            # own, but it is not an automatic pass either.
            decision = "REVIEW"
            granted = KycLevel.TIER1
        elif confidence >= 92.0:
            decision = "APPROVE"
            granted = level
        else:
            decision = "REVIEW"
            granted = KycLevel.TIER1

        return SmileIdResult(
            job_id=f"smile_{secrets.token_hex(8)}",
            liveness_passed=liveness,
            confidence=round(confidence, 2),
            auto_decision=decision,
            granted_level=granted,
        )
