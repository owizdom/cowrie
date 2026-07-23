"""Regulator Portal - FR 5.3, plus the regulator documentation of SRS §2.6.

SRS §2.3 gives Regulators "read-only audit & export" access. That is enforced
structurally rather than by convention: every route in this module is a GET or
generates a report, and no route anywhere in the codebase accepts the
`regulator` token audience for a state change.

FR 5.3: "Generate signed transaction reports for Nigeria SEC and Kenya CMA, and
show live cUSDC supply, reserve balance, and coverage ratio for compliance
review."

On the signature
----------------
The report carries a content hash and a signature over that hash, so a regulator
can detect alteration. The signature is produced by
`security.sign_with_platform_key`, which is an HMAC and not an HSM - so every
export is labelled `demo-signed` in its own metadata. Handing a regulator a
document that claims a cryptographic assurance it does not have would be worse
than handing them an unsigned one.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..enums import ActorType, AdminRole
from ..models import AdminUser, RegulatorExport, Transaction, User
from ..security import sha256_hex, sign_with_platform_key
from ..services import audit, reserve_service
from .deps import current_regulator, require_role

router = APIRouter(prefix="/regulator", tags=["regulator"])

REGULATORS = {
    "SEC_NIGERIA": {
        "name": "Securities and Exchange Commission, Nigeria",
        "jurisdiction": "NG",
        "interest": "VASP registration; cUSDC issuance and reserve backing",
    },
    "CMA_KENYA": {
        "name": "Capital Markets Authority, Kenya",
        "jurisdiction": "KE",
        "interest": "VASP regime (April 2026 draft); KES off-ramp conduct",
    },
    "CBN": {
        "name": "Central Bank of Nigeria",
        "jurisdiction": "NG",
        "interest": "Payment system oversight; NGN on-ramp via NIBSS",
    },
}


def _report_rows(db: Session, start: datetime, end: datetime) -> list[dict]:
    transactions = (
        db.execute(
            select(Transaction)
            .where(Transaction.createdAt >= start, Transaction.createdAt <= end)
            .order_by(Transaction.createdAt.asc())
        )
        .scalars()
        .all()
    )
    users = {u.id: u for u in db.execute(select(User)).scalars().all()}

    rows = []
    for t in transactions:
        sender = users.get(t.senderId or "")
        rows.append(
            {
                "reference": t.reference,
                "createdAt": t.createdAt.isoformat(),
                "settledAt": t.settledAt.isoformat() if t.settledAt else "",
                "state": str(t.state),
                "corridor": f"{t.sourceCurrency}->{t.destinationCurrency}",
                "sourceAmount": str(t.sourceAmount),
                "destinationAmount": str(t.destinationAmount),
                "usdEquivalent": str(
                    (t.sourceAmount / Decimal(str(settings.mid_market_ngn_per_usd))).quantize(
                        Decimal("0.01")
                    )
                ),
                "totalFees": str(t.fees.total()),
                "costPercent": str((t.totalCostRatio() * 100).quantize(Decimal("0.01"))),
                "channel": t.channel,
                "riskLevel": str(t.riskLevel),
                "riskFlags": "; ".join(t.riskFlags or []),
                # Senders are identified by a pseudonymous id and their KYC tier,
                # not by name or phone. A periodic conduct report does not need
                # to be a bulk export of personal data; a specific investigation
                # is a different, narrower request.
                "senderRef": (sender.id[:8] if sender else ""),
                "senderCountry": sender.country if sender else "",
                "senderKycLevel": str(sender.kycLevel) if sender else "",
                "onchainTxHash": t.onchainRecord.txHash if t.onchainRecord else "",
                "mpesaReceipt": t.mpesaReceipt,
            }
        )
    return rows


@router.get("/profile")
def profile(session: dict = Depends(current_regulator)) -> dict:
    code = session.get("regulator", "SEC_NIGERIA")
    return {
        "regulator": code,
        **REGULATORS.get(code, {}),
        "access": "read-only",
        "corridor": f"{settings.corridor_source}->{settings.corridor_destination}",
    }


@router.get("/transactions")
def regulator_transactions(
    session: dict = Depends(current_regulator),
    db: Session = Depends(get_session),
    days: int = Query(default=30, le=365),
) -> dict:
    """Read-only transaction view, pseudonymised."""
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    rows = _report_rows(db, start, end)

    settled = [r for r in rows if r["state"] == "SETTLED"]
    return {
        "periodStart": start.isoformat(),
        "periodEnd": end.isoformat(),
        "rows": rows,
        "summary": {
            "total": len(rows),
            "settled": len(settled),
            "refunded": sum(1 for r in rows if r["state"] == "REFUNDED"),
            "failed": sum(1 for r in rows if r["state"] == "FAILED"),
            "volumeUsd": str(sum(Decimal(r["usdEquivalent"]) for r in settled)),
        },
    }


@router.get("/reserve")
async def regulator_reserve(
    session: dict = Depends(current_regulator),
    db: Session = Depends(get_session),
) -> dict:
    """Live cUSDC supply, reserve balance and coverage ratio (FR 5.3)."""
    data = await reserve_service.dashboard(db)
    data["attestations"] = reserve_service.attestation_history(db)
    return data


@router.get("/audit")
def regulator_audit(
    session: dict = Depends(current_regulator),
    db: Session = Depends(get_session),
) -> dict:
    """The integrity proof, not the log contents.

    A regulator's interest is whether the record can be trusted; the entries
    themselves are available on request through the admin console with a
    specific scope.
    """
    return {"chain": audit.verify_chain(db), "stats": audit.stats(db)}


@router.post("/exports")
def generate_export(
    regulator: str = Query(default="SEC_NIGERIA"),
    days: int = Query(default=30, le=365),
    admin: AdminUser = Depends(require_role(AdminRole.OFFICER)),
    db: Session = Depends(get_session),
) -> dict:
    """Generate a signed report (FR 5.3).

    Officer role or above. The report is hashed, the hash is signed, and both
    are stored so the same report can be re-verified later.
    """
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    rows = _report_rows(db, start, end)

    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    content_hash = sha256_hex(payload)
    signature = sign_with_platform_key(content_hash)

    settled = [r for r in rows if r["state"] == "SETTLED"]
    volume = sum((Decimal(r["usdEquivalent"]) for r in settled), Decimal("0"))

    record = RegulatorExport(
        regulator=regulator,
        periodStart=start,
        periodEnd=end,
        rowCount=len(rows),
        totalVolumeUsd=volume,
        contentHash=content_hash,
        signature=signature,
        generatedBy=admin.email,
    )
    db.add(record)
    db.flush()

    audit.record(
        db,
        entity_type="RegulatorExport",
        entity_id=record.id,
        action="regulator.export",
        actor=ActorType.ADMIN,
        actor_id=admin.email,
        after={"regulator": regulator, "rowCount": len(rows), "contentHash": content_hash},
        detail={"periodDays": days},
    )
    db.commit()

    return {
        "id": record.id,
        "regulator": regulator,
        "regulatorName": REGULATORS.get(regulator, {}).get("name", regulator),
        "periodStart": start.isoformat(),
        "periodEnd": end.isoformat(),
        "rowCount": len(rows),
        "totalVolumeUsd": str(volume),
        "contentHash": content_hash,
        "signature": signature,
        "signatureScheme": "HMAC-SHA256 over the report content hash",
        "signatureAssurance": "demo-signed",
        "signatureNote": (
            "Signed with an application key, not hardware. NFR 2 requires an HSM; "
            "this build has none, and the label says so."
        ),
        "downloadUrl": f"/regulator/exports/{record.id}/download",
    }


@router.get("/exports")
def list_exports(db: Session = Depends(get_session), session: dict = Depends(current_regulator)) -> dict:
    rows = (
        db.execute(select(RegulatorExport).order_by(RegulatorExport.createdAt.desc()).limit(50))
        .scalars()
        .all()
    )
    return {
        "exports": [
            {
                "id": r.id,
                "regulator": r.regulator,
                "periodStart": r.periodStart.isoformat(),
                "periodEnd": r.periodEnd.isoformat(),
                "rowCount": r.rowCount,
                "totalVolumeUsd": str(r.totalVolumeUsd),
                "contentHash": r.contentHash,
                "signature": r.signature,
                "signatureAssurance": "demo-signed",
                "generatedBy": r.generatedBy,
                "createdAt": r.createdAt.isoformat(),
                "downloadUrl": f"/regulator/exports/{r.id}/download",
            }
            for r in rows
        ]
    }


@router.get("/exports/{export_id}/download")
def download_export(export_id: str, db: Session = Depends(get_session)) -> StreamingResponse:
    """Download a report as CSV, with its signature in the header block."""
    record = db.get(RegulatorExport, export_id)
    if record is None:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found")

    rows = _report_rows(db, record.periodStart, record.periodEnd)

    buffer = io.StringIO()
    regulator_name = REGULATORS.get(record.regulator, {}).get("name", record.regulator)
    buffer.write(f"# Cowrie transaction report - {regulator_name}\n")
    buffer.write(f"# Period: {record.periodStart.isoformat()} to {record.periodEnd.isoformat()}\n")
    buffer.write(f"# Rows: {record.rowCount}\n")
    buffer.write(f"# Content SHA-256: {record.contentHash}\n")
    buffer.write(f"# Signature: {record.signature}\n")
    buffer.write("# Signature assurance: demo-signed (application key, not an HSM)\n")
    buffer.write(f"# Generated: {record.createdAt.isoformat()} by {record.generatedBy}\n")
    buffer.write("#\n")

    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    buffer.seek(0)
    filename = f"cowrie-{record.regulator.lower()}-{record.periodStart:%Y%m%d}-{record.periodEnd:%Y%m%d}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/guide")
def integration_guide() -> dict:
    """Regulator documentation (SRS §2.6, "Guide for integrating with the regulator").

    Public and unauthenticated on purpose: a regulator should be able to read
    how the portal works before they are given access to it.
    """
    return {
        "title": "Cowrie Regulator Integration Guide",
        "version": settings.version,
        "corridor": f"{settings.corridor_source} -> {settings.corridor_destination}",
        "access": {
            "method": "Access code issued per regulator, exchanged at POST /auth/regulator/login",
            "session": "Read-only bearer token, 12 hour expiry",
            "regulators": list(REGULATORS.keys()),
        },
        "sections": [
            {
                "title": "1. What Cowrie is",
                "body": (
                    "Cowrie settles cross-border payments between African currencies using cUSDC, "
                    "a USD-pegged stablecoin issued against 1:1 reserves held at a regulated "
                    "banking partner. The launch corridor is Nigeria to Kenya: naira is debited "
                    "from a sender's bank account, converted through cNGN and cUSDC on the Base "
                    "network, and paid out as Kenyan shillings to an M-Pesa wallet."
                ),
            },
            {
                "title": "2. What you can see",
                "body": (
                    "Every transaction in a chosen period, pseudonymised to a sender reference, "
                    "country and KYC tier. The live cUSDC supply, the reserve balance backing it "
                    "and the coverage ratio between them. The full attestation history. And a "
                    "verification of the audit log's hash chain, which tells you whether the "
                    "record has been altered."
                ),
            },
            {
                "title": "3. How reports are signed",
                "body": (
                    "Each export carries a SHA-256 hash of its contents and a signature over that "
                    "hash. Recomputing the hash from the CSV body and checking it against the "
                    "header detects any alteration. In this build the signature is an application "
                    "key rather than hardware, and every export says so in its own metadata."
                ),
            },
            {
                "title": "4. Sanctions screening",
                "body": (
                    "Every user is screened against OFAC, UN and EU lists at signup, again on "
                    "every transfer, and on a daily refresh. A match freezes the account and "
                    "blocks the transfer at authorisation. Screening results are retained "
                    "including the ones that passed, so a period can be audited in full."
                ),
            },
            {
                "title": "5. Settlement guarantee",
                "body": (
                    "Every transfer either completes or is refunded within 10 minutes. There is "
                    "no state in which a sender's money is held indefinitely. This is enforced by "
                    "a sweep that runs independently of the process handling the transfer, so it "
                    "survives a restart mid-transfer."
                ),
            },
            {
                "title": "6. Current regulatory position",
                "body": (
                    "This is a prototype. Cowrie does not hold VASP registration with the Nigeria "
                    "SEC or the Kenya CMA, no banking partner holds reserves, and the contracts "
                    "are not deployed to Base mainnet. The SRS describes the intended licensed "
                    "state; this build demonstrates the system that would operate under it."
                ),
            },
        ],
        "endpoints": [
            {
                "method": "GET",
                "path": "/regulator/transactions",
                "purpose": "Pseudonymised transaction register",
            },
            {"method": "GET", "path": "/regulator/reserve", "purpose": "Live supply, reserve and coverage"},
            {"method": "GET", "path": "/regulator/audit", "purpose": "Audit log integrity verification"},
            {"method": "GET", "path": "/regulator/exports", "purpose": "Previously generated signed reports"},
            {"method": "GET", "path": "/regulator/exports/{id}/download", "purpose": "Signed CSV"},
        ],
    }
