"""Admin & Compliance Console - FR 5.1, FR 5.2, FR 5.3.

Every route carries an RBAC gate from SRS §2.3, and the gates are not uniform:

    Support    read the feed, read queues
    Reviewer   + decide KYC submissions
    Officer    + freeze users, resolve disputes, generate regulator exports
    Engineer   + treasury operations (mint, burn, attest, anchor)
    Admin      + grant roles

The console shows an operator everything and lets them attempt anything, but the
API refuses what their role does not permit - so a mis-rendered button is a
confusing click, never a privilege escalation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.chain import get_chain
from ..config import settings
from ..db import get_session
from ..enums import (
    ActorType,
    AdminRole,
    DisputeStatus,
    KycStatus,
    RiskLevel,
    TransactionState,
)
from ..middleware.timing import performance
from ..models import (
    AdminUser,
    AuditLogEntry,
    Dispute,
    KycSubmission,
    SanctionsScreening,
    Transaction,
    User,
    utcnow,
)
from ..services import audit, kyc_service, monitoring, reserve_service
from .deps import require_role

router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# FR 5.1 - transaction monitoring
# ---------------------------------------------------------------------------


def _row(tx: Transaction, user: User | None) -> dict:
    return {
        "id": tx.id,
        "reference": tx.reference,
        "state": str(tx.state),
        "createdAt": tx.createdAt.isoformat(),
        "settledAt": tx.settledAt.isoformat() if tx.settledAt else None,
        "corridor": f"{tx.sourceCurrency}->{tx.destinationCurrency}",
        "sourceAmount": str(tx.sourceAmount),
        "sourceCurrency": tx.sourceCurrency,
        "destinationAmount": str(tx.destinationAmount),
        "destinationCurrency": tx.destinationCurrency,
        "usdEquivalent": str(
            (tx.sourceAmount / Decimal(str(settings.mid_market_ngn_per_usd))).quantize(Decimal("0.01"))
        ),
        "fees": tx.fees.as_dict(),
        "riskLevel": str(tx.riskLevel),
        "riskFlags": tx.riskFlags or [],
        "channel": tx.channel,
        "recipient": {"name": tx.recipientName, "msisdn": tx.recipientMsisdn},
        "mpesaReceipt": tx.mpesaReceipt,
        "onchainTxHash": tx.onchainRecord.txHash if tx.onchainRecord else "",
        "confirmations": tx.onchainRecord.confirmations if tx.onchainRecord else 0,
        "failureReason": tx.failureReason,
        "isStuck": tx.isStuck(),
        "sender": {
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


@router.get("/overview")
def overview(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
) -> dict:
    """The figures across the top of the console."""
    pending_kyc = db.execute(
        select(KycSubmission).where(KycSubmission.status == KycStatus.PENDING)
    ).scalars().all()
    open_disputes = db.execute(
        select(Dispute).where(Dispute.status.in_([DisputeStatus.OPEN, DisputeStatus.ESCALATED]))
    ).scalars().all()

    return {
        "transactions": monitoring.feed_summary(db),
        "queues": {"pendingKyc": len(pending_kyc), "openDisputes": len(open_disputes)},
        "audit": audit.stats(db),
        # NFR 1 is a number, so it is measured and shown rather than claimed.
        "performance": performance.summary(),
        "chainMode": settings.chain_mode,
        "environment": settings.environment,
    }


@router.get("/transactions")
def transactions(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
    # The four filter chips named in SRS §3.1.
    state: TransactionState | None = None,
    corridor: str | None = Query(default=None, description="e.g. NGN->KES"),
    minUsd: float | None = Query(default=None, description="Transaction size filter"),
    risk: RiskLevel | None = Query(default=None, description="Risk score filter"),
    limit: int = Query(default=100, le=500),
) -> dict:
    """Live transaction feed with the four filter chips (FR 5.1, SRS §3.1)."""
    stmt = select(Transaction).order_by(Transaction.createdAt.desc()).limit(limit)

    if state is not None:
        stmt = stmt.where(Transaction.state == state)
    if risk is not None:
        stmt = stmt.where(Transaction.riskLevel == risk)
    if corridor:
        source, _, destination = corridor.partition("->")
        stmt = stmt.where(
            Transaction.sourceCurrency == source.strip(),
            Transaction.destinationCurrency == destination.strip(),
        )
    if minUsd is not None:
        threshold = Decimal(str(minUsd)) * Decimal(str(settings.mid_market_ngn_per_usd))
        stmt = stmt.where(Transaction.sourceAmount >= threshold)

    rows = db.execute(stmt).scalars().all()
    users = {u.id: u for u in db.execute(select(User)).scalars().all()}

    return {
        "transactions": [_row(t, users.get(t.senderId or "")) for t in rows],
        "filters": {
            "states": [str(s) for s in TransactionState],
            "corridors": ["NGN->KES"],
            "riskLevels": [str(r) for r in RiskLevel],
        },
        "count": len(rows),
    }


@router.get("/transactions/{transaction_id}")
def transaction_detail(
    transaction_id: str,
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
) -> dict:
    tx = db.get(Transaction, transaction_id)
    if tx is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")

    user = db.get(User, tx.senderId) if tx.senderId else None
    trail = (
        db.execute(
            select(AuditLogEntry)
            .where(AuditLogEntry.entityId == tx.id)
            .order_by(AuditLogEntry.seq.asc())
        )
        .scalars()
        .all()
    )
    screenings = (
        db.execute(select(SanctionsScreening).where(SanctionsScreening.transactionId == tx.id))
        .scalars()
        .all()
    )

    return {
        "transaction": _row(tx, user),
        "auditTrail": [
            {
                "seq": e.seq,
                "action": e.action,
                "actor": str(e.actor),
                "actorId": e.actorId,
                "ts": e.ts.isoformat(),
                "detail": e.detail,
                "anchorTxHash": e.anchorTxHash,
            }
            for e in trail
        ],
        "sanctionsScreenings": [
            {
                "trigger": s.trigger,
                "passed": s.passed,
                "listsChecked": s.listsChecked,
                "matchedName": s.matchedName,
                "matchScore": float(s.matchScore),
                "createdAt": s.createdAt.isoformat(),
            }
            for s in screenings
        ],
    }


# ---------------------------------------------------------------------------
# FR 5.2 - KYC review queue
# ---------------------------------------------------------------------------


class KycDecision(BaseModel):
    decision: str = Field(description="APPROVE | REJECT | FREEZE")
    reason: str = ""


@router.get("/kyc")
def kyc_queue(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
    status_filter: KycStatus | None = Query(default=None, alias="status"),
) -> dict:
    """KYC review queue with provider confidence scores (SRS §3.1)."""
    submissions = kyc_service.queue(db, status=status_filter)
    users = {u.id: u for u in db.execute(select(User)).scalars().all()}
    return {
        "submissions": [kyc_service.public_view(s, users.get(s.userId)) for s in submissions],
        "counts": {
            str(s): len(kyc_service.queue(db, status=s)) for s in KycStatus
        },
    }


@router.post("/kyc/{submission_id}/decide")
def decide_kyc(
    submission_id: str,
    body: KycDecision,
    admin: AdminUser = Depends(require_role(AdminRole.REVIEWER)),
    db: Session = Depends(get_session),
) -> dict:
    """Approve, reject or freeze a submission (FR 5.2).

    Reviewer or above.  Every decision is written to the hash-chained log by
    kyc_service, which is the "permanently logged" half of FR 5.2.
    """
    submission = db.get(KycSubmission, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")

    try:
        submission = kyc_service.decide(
            db,
            submission=submission,
            decision=body.decision,
            admin_email=admin.email,
            reason=body.reason,
        )
    except kyc_service.KycError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    user = db.get(User, submission.userId)
    return kyc_service.public_view(submission, user)


# ---------------------------------------------------------------------------
# FR 5.2 - disputes
# ---------------------------------------------------------------------------


class DisputeDecision(BaseModel):
    action: str = Field(description="RESOLVE | REJECT | ESCALATE")
    resolution: str = ""


@router.get("/disputes")
def disputes(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
    status_filter: DisputeStatus | None = Query(default=None, alias="status"),
) -> dict:
    stmt = select(Dispute).order_by(Dispute.createdAt.desc())
    if status_filter:
        stmt = stmt.where(Dispute.status == status_filter)

    rows = db.execute(stmt).scalars().all()
    users = {u.id: u for u in db.execute(select(User)).scalars().all()}
    transactions = {t.id: t for t in db.execute(select(Transaction)).scalars().all()}

    return {
        "disputes": [
            {
                "id": d.id,
                "subject": d.subject,
                "body": d.body,
                "status": str(d.status),
                "createdAt": d.createdAt.isoformat(),
                "resolution": d.resolution,
                "resolvedBy": d.resolvedBy,
                "user": {
                    "id": users[d.userId].id,
                    "fullName": users[d.userId].fullName,
                    "phone": users[d.userId].phone,
                }
                if d.userId in users
                else None,
                "transaction": {
                    "reference": transactions[d.transactionId].reference,
                    "state": str(transactions[d.transactionId].state),
                    "amount": str(transactions[d.transactionId].sourceAmount),
                }
                if d.transactionId in transactions
                else None,
            }
            for d in rows
        ]
    }


@router.post("/disputes/{dispute_id}/decide")
def decide_dispute(
    dispute_id: str,
    body: DisputeDecision,
    admin: AdminUser = Depends(require_role(AdminRole.OFFICER)),
    db: Session = Depends(get_session),
) -> dict:
    """Resolve, reject or escalate a dispute (FR 5.2).

    FR 5.2 names four verbs - approve, reject, freeze, escalate.  Approve and
    freeze belong to KYC submissions; resolve and escalate belong to disputes.
    """
    dispute = db.get(Dispute, dispute_id)
    if dispute is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Dispute not found")

    before = audit.snapshot(dispute)
    match body.action.upper():
        case "RESOLVE":
            dispute.status = DisputeStatus.RESOLVED
        case "REJECT":
            dispute.status = DisputeStatus.REJECTED
        case "ESCALATE":
            dispute.status = DisputeStatus.ESCALATED
        case _:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "action must be RESOLVE, REJECT or ESCALATE"
            )

    dispute.resolution = body.resolution
    dispute.resolvedBy = admin.email
    dispute.resolvedAt = utcnow()

    audit.record(
        db,
        entity_type="Dispute",
        entity_id=dispute.id,
        action=f"dispute.{body.action.lower()}",
        actor=ActorType.ADMIN,
        actor_id=admin.email,
        before=before,
        after=audit.snapshot(dispute),
        detail={"resolution": body.resolution},
    )
    db.commit()

    return {"id": dispute.id, "status": str(dispute.status), "resolvedBy": dispute.resolvedBy}


# ---------------------------------------------------------------------------
# freeze / unfreeze a user (Officer)
# ---------------------------------------------------------------------------


@router.post("/users/{user_id}/freeze")
def freeze_user(
    user_id: str,
    reason: str = Query(default="Compliance review"),
    admin: AdminUser = Depends(require_role(AdminRole.OFFICER)),
    db: Session = Depends(get_session),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    before = audit.snapshot(user)
    user.isFrozen = True
    audit.record(
        db,
        entity_type="User",
        entity_id=user.id,
        action="user.frozen",
        actor=ActorType.ADMIN,
        actor_id=admin.email,
        before=before,
        after=audit.snapshot(user),
        detail={"reason": reason},
    )
    db.commit()
    return {"id": user.id, "isFrozen": True, "reason": reason}


@router.post("/users/{user_id}/unfreeze")
def unfreeze_user(
    user_id: str,
    admin: AdminUser = Depends(require_role(AdminRole.OFFICER)),
    db: Session = Depends(get_session),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    before = audit.snapshot(user)
    user.isFrozen = False
    audit.record(
        db,
        entity_type="User",
        entity_id=user.id,
        action="user.unfrozen",
        actor=ActorType.ADMIN,
        actor_id=admin.email,
        before=before,
        after=audit.snapshot(user),
    )
    db.commit()
    return {"id": user.id, "isFrozen": False}


@router.get("/users")
def users(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
) -> dict:
    rows = db.execute(select(User).order_by(User.createdAt.desc())).scalars().all()
    return {
        "users": [
            {
                "id": u.id,
                "fullName": u.fullName,
                "phone": u.phone,
                "email": u.email,
                "country": u.country,
                "kycLevel": str(u.kycLevel),
                "limitUsd": u.limitUsd(),
                "isFrozen": u.isFrozen,
                "ngnBalance": str(u.ngnBalance),
                "createdAt": u.createdAt.isoformat(),
            }
            for u in rows
        ]
    }


# ---------------------------------------------------------------------------
# FR 5.3 - cUSDC reserve dashboard and treasury operations
# ---------------------------------------------------------------------------


class MintRequest(BaseModel):
    amount: str
    usdDepositReference: str = Field(
        default="", description="Banking partner's confirmation of the matching USD deposit"
    )
    approvals: int = Field(default=3, description="Treasury signatures held (NFR 2 needs >= 3 of 5)")


class BurnRequest(BaseModel):
    amount: str
    approvals: int = 3


@router.get("/reserve")
async def reserve(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
) -> dict:
    """Live supply, reserve balance and coverage ratio (FR 5.3)."""
    data = await reserve_service.dashboard(db)
    data["attestations"] = reserve_service.attestation_history(db)
    return data


@router.post("/reserve/mint")
async def mint(
    body: MintRequest,
    admin: AdminUser = Depends(require_role(AdminRole.ENGINEER)),
    db: Session = Depends(get_session),
) -> dict:
    """Mint cUSDC (FR 3.2).

    Refuses without a confirmed USD deposit reference, and refuses below the
    3-of-5 treasury threshold.  Both refusals are audited.
    """
    try:
        movement = await reserve_service.mint(
            db,
            amount=Decimal(body.amount),
            usd_deposit_reference=body.usdDepositReference,
            performed_by=admin.email,
            approvals=body.approvals,
        )
    except reserve_service.ReserveError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return {
        "id": movement.id,
        "kind": movement.kind,
        "amount": str(movement.amount),
        "txHash": movement.txHash,
        "supplyAfter": str(movement.supplyAfter),
        "approvals": f"{movement.approvals}/{reserve_service.TOTAL_SIGNERS}",
    }


@router.post("/reserve/burn")
async def burn(
    body: BurnRequest,
    admin: AdminUser = Depends(require_role(AdminRole.ENGINEER)),
    db: Session = Depends(get_session),
) -> dict:
    try:
        movement = await reserve_service.burn(
            db,
            amount=Decimal(body.amount),
            performed_by=admin.email,
            approvals=body.approvals,
        )
    except reserve_service.ReserveError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return {
        "id": movement.id,
        "kind": movement.kind,
        "amount": str(movement.amount),
        "txHash": movement.txHash,
        "supplyAfter": str(movement.supplyAfter),
    }


@router.post("/reserve/attest")
async def attest(
    admin: AdminUser = Depends(require_role(AdminRole.ENGINEER)),
    db: Session = Depends(get_session),
) -> dict:
    """Publish a reserve attestation, anchored on-chain."""
    row = await reserve_service.publish_attestation(db, performed_by=admin.email)
    return {
        "id": row.id,
        "attestationDate": row.attestationDate.isoformat(),
        "usdBalance": str(row.usdBalance),
        "cusdcSupply": str(row.cusdcSupply),
        "coverageRatio": str(row.coverageRatio()),
        "isFullyBacked": row.isFullyBacked(),
        "attestor": row.attestor,
        "anchorTxHash": row.anchorTxHash,
    }


@router.get("/reserve/reconcile")
async def reconcile(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
) -> dict:
    """Reconcile on-chain supply against off-chain reserves (SRS §2.2, 1c).

    The check that matters for a stablecoin: does the token supply the chain
    reports actually match the dollars the bank says it holds?  A drift here is
    the single most serious failure this system can have, so it is a first-class
    endpoint rather than a figure derived inside the dashboard.
    """
    chain = get_chain()
    onchain_supply = await chain.total_supply()
    offchain_reserve = await reserve_service.bank.reserve_balance()
    drift = offchain_reserve - onchain_supply

    return {
        "onchainSupply": str(onchain_supply),
        "offchainReserveUsd": str(offchain_reserve),
        "drift": str(drift),
        "coverageRatio": str(
            (offchain_reserve / onchain_supply).quantize(Decimal("0.000001"))
            if onchain_supply
            else Decimal("0")
        ),
        "isFullyBacked": offchain_reserve >= onchain_supply,
        "reconciledAt": datetime.now(UTC).isoformat(),
        "chainMode": getattr(chain, "mode", "simulated"),
        "verdict": "BACKED" if offchain_reserve >= onchain_supply else "UNDER-COLLATERALISED",
    }


# ---------------------------------------------------------------------------
# NFR 5 - audit log
# ---------------------------------------------------------------------------


@router.get("/audit")
def audit_log(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
    limit: int = Query(default=100, le=1000),
    entityType: str | None = None,
) -> dict:
    stmt = select(AuditLogEntry).order_by(AuditLogEntry.seq.desc()).limit(limit)
    if entityType:
        stmt = stmt.where(AuditLogEntry.entityType == entityType)

    rows = db.execute(stmt).scalars().all()
    return {
        "entries": [
            {
                "seq": e.seq,
                "entityType": e.entityType,
                "entityId": e.entityId,
                "action": e.action,
                "actor": str(e.actor),
                "actorId": e.actorId,
                "ts": e.ts.isoformat(),
                "entryHash": e.entryHash,
                "prevLogHash": e._prevLogHash,
                "anchorTxHash": e.anchorTxHash,
                "detail": e.detail,
            }
            for e in rows
        ],
        "stats": audit.stats(db),
    }


@router.get("/audit/verify")
def verify_audit(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
) -> dict:
    """AuditLogEntry.verifyChain() (NFR 5).

    Walks the whole chain and reports the exact sequence number of any break.
    """
    return audit.verify_chain(db)


@router.post("/audit/anchor")
async def anchor_audit(
    admin: AdminUser = Depends(require_role(AdminRole.ENGINEER)),
    db: Session = Depends(get_session),
) -> dict:
    """Anchor pending audit entries on-chain (NFR 5)."""
    return await audit.anchor_pending(db, get_chain())


# ---------------------------------------------------------------------------
# sanctions watch (FR 1.3 visibility)
# ---------------------------------------------------------------------------


@router.get("/sanctions")
def sanctions_watch(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
    limit: int = Query(default=100, le=500),
) -> dict:
    rows = (
        db.execute(
            select(SanctionsScreening).order_by(SanctionsScreening.createdAt.desc()).limit(limit)
        )
        .scalars()
        .all()
    )
    users = {u.id: u for u in db.execute(select(User)).scalars().all()}
    hits = [s for s in rows if not s.passed]

    return {
        "screenings": [
            {
                "id": s.id,
                "trigger": s.trigger,
                "passed": s.passed,
                "listsChecked": s.listsChecked,
                "matchedName": s.matchedName,
                "matchScore": float(s.matchScore),
                "createdAt": s.createdAt.isoformat(),
                "user": {
                    "id": users[s.userId].id,
                    "fullName": users[s.userId].fullName,
                    "isFrozen": users[s.userId].isFrozen,
                }
                if s.userId in users
                else None,
            }
            for s in rows
        ],
        "summary": {"total": len(rows), "hits": len(hits), "lists": ["OFAC", "UN", "EU"]},
    }


@router.post("/sanctions/refresh")
def refresh_sanctions(
    admin: AdminUser = Depends(require_role(AdminRole.OFFICER)),
    db: Session = Depends(get_session),
) -> dict:
    """Run the daily re-screen on demand (FR 1.3)."""
    from ..services.sanctions import service as sanctions_service

    result = sanctions_service.daily_refresh(db)
    db.commit()
    return result


@router.get("/performance")
def performance_report(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
) -> dict:
    """NFR 1, measured.

    Two different budgets: API latency (this process) and end-to-end corridor
    latency (the whole journey including the chain wait). Both are reported,
    because meeting one and missing the other would be a misleading pass.
    """
    settled = (
        db.execute(
            select(Transaction).where(
                Transaction.state == TransactionState.SETTLED,
                Transaction.createdAt >= datetime.now(UTC) - timedelta(days=7),
            )
        )
        .scalars()
        .all()
    )
    durations = sorted(
        (t.settledAt - t.createdAt).total_seconds() for t in settled if t.settledAt and t.createdAt
    )

    def pct(p: float) -> float:
        if not durations:
            return 0.0
        return round(durations[min(len(durations) - 1, int(len(durations) * p))], 2)

    return {
        "api": performance.summary(),
        "corridor": {
            "samples": len(durations),
            "medianSeconds": pct(0.5),
            "p95Seconds": pct(0.95),
            "maxSeconds": round(durations[-1], 2) if durations else 0.0,
            "targetTypicalSeconds": 30,
            "targetWorstCaseSeconds": 60,
            "withinTypical": sum(1 for d in durations if d <= 30),
            "withinWorstCase": sum(1 for d in durations if d <= 60),
        },
    }


# ---------------------------------------------------------------------------
# SRS 2.3 - "Admin (role grants)"
# ---------------------------------------------------------------------------


class NewOperator(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    fullName: str = Field(min_length=2, max_length=160)
    role: AdminRole = AdminRole.SUPPORT
    password: str = Field(min_length=8, max_length=128)




@router.get("/team")
def team(
    admin: AdminUser = Depends(require_role(AdminRole.SUPPORT)),
    db: Session = Depends(get_session),
) -> dict:
    rows = db.execute(select(AdminUser).order_by(AdminUser.createdAt)).scalars().all()
    return {
        "team": [
            {
                "id": a.id,
                "email": a.email,
                "fullName": a.fullName,
                "role": str(a.role),
                "createdAt": a.createdAt.isoformat(),
            }
            for a in rows
        ]
    }


@router.post("/team", status_code=status.HTTP_201_CREATED)
def create_operator(
    body: NewOperator,
    admin: AdminUser = Depends(require_role(AdminRole.ADMIN)),
    db: Session = Depends(get_session),
) -> dict:
    """Create a console operator.

    Admin role only. SRS 2.3 gives role grants to the Admin privilege and to no
    other, which is why this is not a public sign-up: an open registration form
    on a compliance console would hand anyone the transaction register.
    """
    from ..security import hash_secret as _hash

    if db.execute(select(AdminUser).where(AdminUser.email == body.email)).scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "That email already has console access.")

    operator = AdminUser(email=body.email, fullName=body.fullName, role=body.role)
    operator._passwordHash = _hash(body.password)
    db.add(operator)
    db.flush()

    audit.record(
        db,
        entity_type="AdminUser",
        entity_id=operator.id,
        action="admin.role_granted",
        actor=ActorType.ADMIN,
        actor_id=admin.email,
        after={"email": body.email, "role": str(body.role)},
    )
    db.commit()

    return {"id": operator.id, "email": operator.email, "role": str(operator.role)}
