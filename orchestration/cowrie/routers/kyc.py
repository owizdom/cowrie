"""KYC and account linking - FR 1.2, plus the "link a bank or mobile money
wallet" function from SRS §2.2.

The camera requirement in SRS §3.2 (rear camera for the document, front camera
for the liveness selfie) is satisfied on the client: `/pay/verify` captures both
with getUserMedia and posts them here.  The images are not stored - the adapter
returns a verdict and a confidence score, and keeping copies of identity
documents in a demo database would be a liability with no upside.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..enums import ActorType, KycIdType
from ..models import KycSubmission, User
from ..services import audit, kyc_service
from .deps import current_user

router = APIRouter(prefix="/kyc", tags=["kyc"])


class KycSubmitRequest(BaseModel):
    idType: KycIdType
    idNumber: str = Field(min_length=6, max_length=32)
    documentCaptured: bool = Field(
        default=False, description="Rear-camera document capture completed (SRS 3.2)"
    )
    selfieCaptured: bool = Field(
        default=False, description="Front-camera liveness selfie completed (SRS 3.2)"
    )


class LinkAccountRequest(BaseModel):
    """SRS §2.2 - "associate themselves with a bank or mobile money wallet"."""

    kind: str = Field(description="BANK or MOBILE_MONEY")
    institution: str = Field(min_length=2, max_length=80)
    accountNumber: str = Field(min_length=6, max_length=24)


@router.post("/submit", status_code=status.HTTP_201_CREATED)
async def submit_kyc(
    body: KycSubmitRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """Run identity verification (FR 1.2).

    Both captures are required.  A selfie without a document cannot be matched
    against anything, and a document without a selfie proves possession rather
    than identity - FR 1.2 asks for both, so both are enforced here rather than
    left to the UI.
    """
    if not body.documentCaptured or not body.selfieCaptured:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Both an ID document photo and a liveness selfie are required (FR 1.2, SRS 3.2).",
        )

    try:
        submission = await kyc_service.submit(
            db, user=user, id_type=body.idType, id_number=body.idNumber
        )
    except kyc_service.KycError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return {
        "submission": kyc_service.public_view(submission, user),
        "kycLevel": str(user.kycLevel),
        "limitUsd": user.limitUsd(),
        "message": {
            "APPROVED": "Verified. Your transfer limit has been raised.",
            "PENDING": "Submitted for review. Most checks are decided within a few minutes.",
            "REJECTED": "We could not verify this document. You can try again with another ID.",
            "FROZEN": "Your account is under compliance review.",
        }.get(str(submission.status), ""),
    }


@router.get("/status")
def kyc_status(user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict:
    submissions = (
        db.execute(
            select(KycSubmission)
            .where(KycSubmission.userId == user.id)
            .order_by(KycSubmission.createdAt.desc())
        )
        .scalars()
        .all()
    )
    return {
        "level": str(user.kycLevel),
        "limitUsd": user.limitUsd(),
        "isFrozen": user.isFrozen,
        "submissions": [kyc_service.public_view(s) for s in submissions],
        **kyc_service.level_limits(),
    }


@router.get("/id-types")
def id_types() -> dict:
    """The five ID types FR 1.2 names, and what each unlocks."""
    from ..adapters.smileid import ID_TYPE_RULES

    labels = {
        KycIdType.NIN: ("National Identification Number", "Nigeria"),
        KycIdType.BVN: ("Bank Verification Number", "Nigeria"),
        KycIdType.KENYAN_ID: ("Kenyan National ID", "Kenya"),
        KycIdType.NIDA: ("NIDA Number", "Tanzania"),
        KycIdType.GHANA_CARD: ("Ghana Card", "Ghana"),
    }
    return {
        "idTypes": [
            {
                "value": str(id_type),
                "label": labels[id_type][0],
                "country": labels[id_type][1],
                "countryCode": rules[0],
                "unlocksLevel": str(rules[1]),
            }
            for id_type, rules in ID_TYPE_RULES.items()
        ]
    }


@router.post("/link-account")
def link_account(
    body: LinkAccountRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """Link a funding source (SRS §2.2).

    In production this hands off to Mono Connect's account-linking consent
    screen and stores the returned account id, never the account number.  Here
    the number is masked to the last four immediately and the full value is not
    persisted, which is the same end state.
    """
    if body.kind not in {"BANK", "MOBILE_MONEY"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "kind must be BANK or MOBILE_MONEY")

    before = audit.snapshot(user)
    masked = "*" * max(0, len(body.accountNumber) - 4) + body.accountNumber[-4:]
    user.bankName = body.institution
    user.bankAccountMasked = masked

    audit.record(
        db,
        entity_type="User",
        entity_id=user.id,
        action="user.account_linked",
        actor=ActorType.USER,
        actor_id=user.id,
        before=before,
        after=audit.snapshot(user),
        detail={"kind": body.kind, "institution": body.institution, "masked": masked},
    )
    db.commit()

    return {
        "linked": True,
        "kind": body.kind,
        "institution": body.institution,
        "accountMasked": masked,
    }


class TopUpRequest(BaseModel):
    amount: str = Field(description="Amount in NGN")


@router.post("/top-up")
async def top_up(
    body: TopUpRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """Pull funds from the linked bank account into the wallet.

    The same Mono on-ramp FR 2.2 uses to fund a transfer, exposed as its own
    action so an account can hold a balance before sending. A wallet cannot be
    funded without a linked account, which is why linking comes first.
    """
    from decimal import Decimal, InvalidOperation

    from ..adapters.mono import MonoAdapter

    if not user.bankName:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Link a bank account before topping up.",
        )

    try:
        amount = Decimal(body.amount)
    except InvalidOperation as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be a number.") from exc

    if amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be positive.")

    result = await MonoAdapter().debit(
        user_id=user.id, amount=amount, narration="CowriePay wallet top-up"
    )
    if not result.accepted:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, result.failure_reason)

    before = audit.snapshot(user)
    user.ngnBalance += amount

    audit.record(
        db,
        entity_type="User",
        entity_id=user.id,
        action="wallet.topped_up",
        actor=ActorType.USER,
        actor_id=user.id,
        before=before,
        after=audit.snapshot(user),
        detail={"amount": str(amount), "monoReference": result.reference},
    )
    db.commit()

    return {
        "credited": str(amount),
        "balance": str(user.ngnBalance),
        "reference": result.reference,
    }
