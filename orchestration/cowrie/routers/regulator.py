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

What the signature actually covers
----------------------------------
The hash is taken over the CSV body byte-for-byte - the header row and the data
rows, with the `#` comment block excluded - and that exact body is stored on the
export row. Two things follow, and both are the point:

  * A verifier can reproduce the hash. Strip every line beginning with `#`,
    SHA-256 the rest as UTF-8, and compare. `GET /exports/{id}/verify` runs that
    procedure server-side so the instruction in the guide is executable rather
    than merely stated.

  * The report cannot drift after it is signed. Re-deriving the rows at download
    time would let a transfer that was in flight at signing appear later with a
    different state, a settledAt and an M-Pesa receipt - the same period, a
    different document, one hash. The stored body is served verbatim instead.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..enums import ActorType, AdminRole
from ..models import AdminUser, RegulatorExport, Transaction, User
from ..security import constant_time_equals, sha256_hex, sign_with_platform_key
from ..services import audit, reserve_service
from .deps import current_regulator, regulator_or_officer, require_role

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


def _render_csv(rows: list[dict]) -> str:
    """Render the report body: one header row, then the data. No comment lines.

    This is the material the signature covers, so it has exactly one producer.
    Two call sites rendering "the same" CSV independently is how the hash and
    the document drift apart.

    `lineterminator` is pinned because `csv.writer` defaults to CRLF while the
    comment block above it is written with LF - a verifier splitting on newlines
    would otherwise hash bytes that differ from the ones on the wire.
    """
    if not rows:
        return ""

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


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

    Officer role or above. The report is rendered once, the rendered bytes are
    hashed, the hash is signed, and the bytes themselves are stored - so the
    document a regulator downloads later is the document that was signed, not a
    fresh rendering that happens to cover the same period.
    """
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    rows = _report_rows(db, start, end)

    # Hash the CSV the regulator actually receives. Hashing a JSON view of the
    # same rows would attest to a document nobody is ever handed, and could not
    # be recomputed from the download.
    body = _render_csv(rows)
    content_hash = sha256_hex(body)
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
        csvBody=body,
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
        "signatureCovers": (
            "The CSV body byte-for-byte (header row + data rows), excluding the "
            "'#' metadata block. SHA-256, UTF-8."
        ),
        "signatureAssurance": "demo-signed",
        "signatureNote": (
            "Signed with an application key, not hardware. NFR 2 requires an HSM; "
            "this build has none, and the label says so."
        ),
        "downloadUrl": f"/regulator/exports/{record.id}/download",
        "verifyUrl": f"/regulator/exports/{record.id}/verify",
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


def _load_export(db: Session, export_id: str) -> RegulatorExport:
    record = db.get(RegulatorExport, export_id)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Export not found")
    return record


def _export_body(record: RegulatorExport, db: Session) -> tuple[str, str]:
    """Return (body, assurance).

    Rows written before the body was stored have nothing to serve verbatim, so
    they are re-derived and labelled for what they are. Letting a legacy row
    present itself as verifiable would be the same dishonesty the stored body
    exists to remove.

    The test is `is None`, not truthiness: a report covering a period with no
    transactions has an empty body, and that is a perfectly well-signed empty
    report - `sha256("")` is a real answer to a real question. Only a row that
    predates the column, which `_sync_columns` back-filled as NULL, is legacy.
    """
    if record.csvBody is not None:
        return record.csvBody, "demo-signed"
    return (
        _render_csv(_report_rows(db, record.periodStart, record.periodEnd)),
        "unverifiable-legacy",
    )


@router.get("/exports/{export_id}/download")
def download_export(
    export_id: str,
    db: Session = Depends(get_session),
    session: dict = Depends(regulator_or_officer),
) -> StreamingResponse:
    """Download a report as CSV, with its signature in the header block.

    Authenticated: this is the pseudonymised transaction register, and the
    surrounding module is read-only *by audience*, not public. A regulator
    session or an Officer-and-above admin session both open it (SRS §2.3).

    The body is the one that was signed, served verbatim - see the module
    docstring for why it is not re-derived here.
    """
    record = _load_export(db, export_id)
    body, assurance = _export_body(record, db)

    buffer = io.StringIO()
    regulator_name = REGULATORS.get(record.regulator, {}).get("name", record.regulator)
    buffer.write(f"# Cowrie transaction report - {regulator_name}\n")
    buffer.write(f"# Period: {record.periodStart.isoformat()} to {record.periodEnd.isoformat()}\n")
    buffer.write(f"# Rows: {record.rowCount}\n")
    buffer.write(f"# Content SHA-256: {record.contentHash}\n")
    buffer.write(f"# Signature: {record.signature}\n")
    buffer.write(f"# Signature assurance: {assurance} (application key, not an HSM)\n")
    buffer.write(f"# Generated: {record.createdAt.isoformat()} by {record.generatedBy}\n")
    buffer.write("# To verify: discard every line beginning with '#', then SHA-256 the\n")
    buffer.write("#            remainder as UTF-8 and compare with Content SHA-256 above.\n")
    buffer.write("#\n")
    buffer.write(body)

    filename = f"cowrie-{record.regulator.lower()}-{record.periodStart:%Y%m%d}-{record.periodEnd:%Y%m%d}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exports/{export_id}/verify")
def verify_export(
    export_id: str,
    db: Session = Depends(get_session),
    session: dict = Depends(regulator_or_officer),
) -> dict:
    """Run the verification the guide describes, server-side.

    An instruction a regulator cannot execute is not an assurance. This
    recomputes the hash over the stored body and re-derives the signature, and
    reports both outcomes separately: a content mismatch means the report was
    altered, a signature mismatch means the report was signed by something other
    than this platform key.
    """
    record = _load_export(db, export_id)
    body, assurance = _export_body(record, db)

    recomputed = sha256_hex(body)
    expected_signature = sign_with_platform_key(record.contentHash)

    return {
        "id": record.id,
        "regulator": record.regulator,
        "contentHash": record.contentHash,
        "recomputedHash": recomputed,
        "matches": constant_time_equals(recomputed, record.contentHash),
        "signatureValid": constant_time_equals(expected_signature, record.signature),
        "signatureAssurance": assurance,
        "bytesVerified": len(body.encode()),
        "procedure": (
            "SHA-256 over the CSV body (header row + data rows) as UTF-8, "
            "excluding every line beginning with '#'."
        ),
        "note": (
            "The stored body is served byte-for-byte, so this result also holds "
            "for the file returned by the download endpoint."
        )
        if record.csvBody is not None
        else (
            "This export predates body storage: it is re-derived at read time "
            "and cannot be meaningfully verified."
        ),
    }


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
                "title": "3. How reports are signed, and how to check one",
                "body": (
                    "Each export carries a SHA-256 hash of its contents and a signature over that "
                    "hash. The hash covers the CSV body byte-for-byte - the header row and the "
                    "data rows - and excludes the '#' metadata block above them. To verify a "
                    "report you have been sent: discard every line beginning with '#', SHA-256 "
                    "the remainder as UTF-8, and compare the result with the Content SHA-256 in "
                    "the header. GET /regulator/exports/{id}/verify performs the same check "
                    "server-side and reports the content and signature results separately. "
                    "The body is stored at the moment it is signed and served unchanged "
                    "afterwards, so a report cannot quietly differ from the hash that attests to "
                    "it. In this build the signature is an application key rather than hardware, "
                    "and every export says so in its own metadata."
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
