"""KYC Service - FR 1.1, FR 1.2 and the review side of FR 5.2.

FR 1.2: "Verify identity with a government ID (NIN, BVN, Kenyan National ID,
NIDA, or Ghana Card) plus a selfie, using Smile ID to confirm the person is
real and matches the ID. Transaction limits can also scale with the
verification level."

The use case diagram makes "Verify identity (KYC)" an <<include>> of "Register
account", and makes "Screen against sanctions" an <<include>> of KYC.  That
chain is implemented literally: registering submits a KYC job, and a KYC
decision screens the person before it can approve them.

Decision routing
----------------
Smile ID returns APPROVE, REVIEW or REJECT.  Cowrie does not simply trust the
first: an automatic approval still lands as an APPROVED submission, but
anything else goes to the human queue in the admin console, which is what the
"KYC review queue" in SRS 3.1 is for.  An analyst can then approve, reject or
freeze, and every one of those actions is written to the audit log by the
caller, because FR 5.2 requires "every action permanently logged".
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.smileid import SmileIdAdapter
from ..enums import ActorType, KycIdType, KycStatus
from ..models import KycSubmission, User
from ..security import encrypt_id_number, id_number_tail
from . import audit
from .sanctions import service as sanctions_service

smile = SmileIdAdapter()


class KycError(Exception):
    pass


async def submit(
    db: Session,
    *,
    user: User,
    id_type: KycIdType,
    id_number: str,
    trigger: str = "SIGNUP",
) -> KycSubmission:
    """Run a verification and file the submission.

    The ID number is encrypted before it is stored and is never returned by any
    endpoint - the class diagram marks -idNumberEncrypted private, and the only
    thing that leaves this service is the last four characters.
    """
    if not id_number or len(id_number.strip()) < 6:
        raise KycError("A valid government ID number is required.")

    # <<include>> Screen against sanctions
    screening = sanctions_service.screen_user(db, user, trigger=trigger)

    result = await smile.verify(
        id_type=id_type,
        id_number=id_number,
        full_name=user.fullName,
        country=user.country,
    )

    submission = KycSubmission(
        userId=user.id,
        provider=result.provider,
        idType=id_type,
        status=KycStatus.PENDING,
        confidenceScore=result.confidence,
        livenessPassed=result.liveness_passed,
        requestedLevel=result.granted_level,
    )
    submission._idNumberEncrypted = encrypt_id_number(id_number.strip())
    db.add(submission)
    db.flush()

    # A sanctions hit overrides whatever the identity check concluded: the
    # person may well be exactly who they say they are.
    if not screening.passed:
        submission.freeze(by="system", reason=screening.reason)
        user.isFrozen = True
        action = "kyc.frozen"
    elif result.auto_decision == "APPROVE":
        submission.approve(by=f"{result.provider} (auto)")
        user.raiseLimit(result.granted_level)
        action = "kyc.approved"
    elif result.auto_decision == "REJECT":
        submission.reject(by=f"{result.provider} (auto)", reason="Liveness check failed")
        action = "kyc.rejected"
    else:
        # Left PENDING for the human queue.
        action = "kyc.submitted"

    audit.record(
        db,
        entity_type="KycSubmission",
        entity_id=submission.id,
        action=action,
        actor=ActorType.SYSTEM,
        actor_id=result.provider,
        after=audit.snapshot(submission),
        detail={
            "jobId": result.job_id,
            "confidence": result.confidence,
            "autoDecision": result.auto_decision,
            "idTail": id_number_tail(submission._idNumberEncrypted),
            "sanctionsPassed": screening.passed,
        },
    )
    db.commit()
    return submission


def decide(
    db: Session,
    *,
    submission: KycSubmission,
    decision: str,
    admin_email: str,
    reason: str = "",
) -> KycSubmission:
    """An analyst approves, rejects or freezes a queued submission (FR 5.2)."""
    if submission.status != KycStatus.PENDING:
        raise KycError(f"This submission was already {submission.status}.")

    before = audit.snapshot(submission)
    user = db.get(User, submission.userId)

    match decision.upper():
        case "APPROVE":
            submission.approve(by=admin_email)
            if user:
                user.raiseLimit(submission.requestedLevel)
            action = "kyc.approved"
        case "REJECT":
            submission.reject(by=admin_email, reason=reason or "Did not meet verification standard")
            action = "kyc.rejected"
        case "FREEZE":
            submission.freeze(by=admin_email, reason=reason or "Escalated for compliance review")
            if user:
                user.isFrozen = True
            action = "kyc.frozen"
        case _:
            raise KycError("decision must be APPROVE, REJECT or FREEZE")

    audit.record(
        db,
        entity_type="KycSubmission",
        entity_id=submission.id,
        action=action,
        actor=ActorType.ADMIN,
        actor_id=admin_email,
        before=before,
        after=audit.snapshot(submission),
        detail={"reason": reason},
    )
    db.commit()
    return submission


def queue(db: Session, *, status: KycStatus | None = None, limit: int = 100) -> list[KycSubmission]:
    stmt = select(KycSubmission).order_by(KycSubmission.createdAt.desc()).limit(limit)
    if status is not None:
        stmt = stmt.where(KycSubmission.status == status)
    return list(db.execute(stmt).scalars().all())


def public_view(submission: KycSubmission, user: User | None = None) -> dict:
    """Serialise a submission for the admin queue.

    Returns the ID tail rather than the ID.  There is no endpoint anywhere that
    returns the full number, by design.
    """
    return {
        "id": submission.id,
        "createdAt": submission.createdAt.isoformat(),
        "provider": submission.provider,
        "status": str(submission.status),
        "idType": str(submission.idType),
        "idTail": id_number_tail(submission._idNumberEncrypted),
        "confidenceScore": float(submission.confidenceScore),
        "livenessPassed": submission.livenessPassed,
        "requestedLevel": str(submission.requestedLevel),
        "decidedAt": submission.decidedAt.isoformat() if submission.decidedAt else None,
        "decidedBy": submission.decidedBy,
        "rejectionReason": submission.rejectionReason,
        "user": {
            "id": user.id,
            "fullName": user.fullName,
            "phone": user.phone,
            "country": user.country,
            "kycLevel": str(user.kycLevel),
            "isFrozen": user.isFrozen,
        }
        if user
        else None,
    }


def level_limits() -> dict:
    from ..config import settings

    return {
        "levels": [
            {
                "level": level,
                "limitUsd": limit,
                "unlockedBy": _unlock_hint(level),
            }
            for level, limit in settings.tier_limits_usd.items()
        ]
    }


def _unlock_hint(level: str) -> str:
    return {
        "NONE": "No verification yet",
        "TIER1": "Phone and email verified",
        "TIER2": "Government ID + selfie (NIN, Kenyan ID, Ghana Card)",
        "TIER3": "BVN with bank record match",
    }.get(level, "")


__all__ = ["KycError", "decide", "level_limits", "public_view", "queue", "submit"]
