"""cUSDC issuance and reserve management - FR 3.2, FR 5.3.

FR 3.2: "Only create new cUSDC after the banking partner confirms a matching
USD deposit. Destroy cUSDC when redeemed for USD. Reject any attempt to create
cUSDC without verified dollar backing."

The third sentence is the one that decides this module's shape.  `mint` asks
the banking partner adapter to confirm the deposit and returns a refusal if it
does not, before any chain call is made.  There is no code path that mints
without that confirmation, and the test suite asserts it.

FR 5.3 also requires a live view of supply, reserve balance and coverage ratio,
which is what `dashboard` returns and what both the admin console and the
public transparency page render.

NFR 2 requires >= 3 of 5 signatures for treasury movement.  The multisig lives
in cusdc/CowrieTreasury.sol; this service records how many approvals a movement
carried, and refuses below the threshold.  In simulated mode the approvals are
recorded rather than cryptographically verified, and the UI says so.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..adapters.banking_partner import BankingPartnerAdapter
from ..adapters.chain import get_chain
from ..enums import ActorType
from ..models import CusdcReserve, ReserveMovement
from . import audit

bank = BankingPartnerAdapter()

#: NFR 2 - "any movement of the treasury requires the signature of a minimum of
#: 3 out of 5 approved signatories".
REQUIRED_APPROVALS = 3
TOTAL_SIGNERS = 5


class ReserveError(Exception):
    """A refusal that must be shown to the operator verbatim."""


async def mint(
    db: Session,
    *,
    amount: Decimal,
    usd_deposit_reference: str,
    performed_by: str,
    approvals: int = REQUIRED_APPROVALS,
) -> ReserveMovement:
    """Issue cUSDC against a confirmed USD deposit.

    Order of checks is the requirement, in order:
      1. treasury approval threshold (NFR 2)
      2. banking partner confirms the matching USD deposit (FR 3.2)
      3. only then does anything touch the chain
    """
    if amount <= 0:
        raise ReserveError("Mint amount must be positive.")

    if approvals < REQUIRED_APPROVALS:
        raise ReserveError(
            f"Treasury movement needs at least {REQUIRED_APPROVALS} of {TOTAL_SIGNERS} "
            f"signatures; this request carries {approvals} (NFR 2)."
        )

    confirmation = await bank.confirm_deposit(amount=amount, reference=usd_deposit_reference)
    if not confirmation.confirmed:
        # FR 3.2, third sentence.  The refusal is audited: an attempt to issue
        # unbacked cUSDC is exactly the event a regulator would want a record of.
        audit.record(
            db,
            entity_type="CusdcReserve",
            entity_id="-",
            action="cusdc.mint_refused",
            actor=ActorType.ADMIN,
            actor_id=performed_by,
            detail={"amount": str(amount), "reason": confirmation.reason},
        )
        db.commit()
        raise ReserveError(confirmation.reason)

    chain = get_chain()
    tx_hash = await chain.mint_cusdc(amount=amount, attestation_ref=usd_deposit_reference)
    supply = await chain.total_supply()

    movement = ReserveMovement(
        kind="MINT",
        amount=amount,
        usdDepositReference=usd_deposit_reference,
        txHash=tx_hash,
        performedBy=performed_by,
        approvals=approvals,
        supplyAfter=supply,
    )
    db.add(movement)
    bank._usd_on_hand += amount
    db.flush()

    audit.record(
        db,
        entity_type="CusdcReserve",
        entity_id=movement.id,
        action="cusdc.minted",
        actor=ActorType.ADMIN,
        actor_id=performed_by,
        after={"amount": str(amount), "supplyAfter": str(supply), "txHash": tx_hash},
        detail={"depositReference": usd_deposit_reference, "approvals": approvals},
    )
    db.commit()
    return movement


async def burn(
    db: Session,
    *,
    amount: Decimal,
    performed_by: str,
    approvals: int = REQUIRED_APPROVALS,
) -> ReserveMovement:
    """Destroy cUSDC on redemption and pay the USD out (FR 3.2, sentence two)."""
    if amount <= 0:
        raise ReserveError("Burn amount must be positive.")

    if approvals < REQUIRED_APPROVALS:
        raise ReserveError(
            f"Treasury movement needs at least {REQUIRED_APPROVALS} of {TOTAL_SIGNERS} "
            f"signatures; this request carries {approvals} (NFR 2)."
        )

    chain = get_chain()
    current = await chain.total_supply()
    if amount > current:
        raise ReserveError(f"Cannot burn {amount}; circulating supply is {current}.")

    tx_hash = await chain.burn_cusdc(amount=amount)
    wire = await bank.redeem(amount=amount)
    supply = await chain.total_supply()

    movement = ReserveMovement(
        kind="BURN",
        amount=amount,
        usdDepositReference=wire,
        txHash=tx_hash,
        performedBy=performed_by,
        approvals=approvals,
        supplyAfter=supply,
    )
    db.add(movement)
    bank._usd_on_hand -= amount
    db.flush()

    audit.record(
        db,
        entity_type="CusdcReserve",
        entity_id=movement.id,
        action="cusdc.burned",
        actor=ActorType.ADMIN,
        actor_id=performed_by,
        after={"amount": str(amount), "supplyAfter": str(supply), "txHash": tx_hash},
        detail={"redemptionWire": wire, "approvals": approvals},
    )
    db.commit()
    return movement


async def publish_attestation(
    db: Session,
    *,
    performed_by: str,
    period: str | None = None,
) -> CusdcReserve:
    """The monthly outside-auditor statement (use case "Publish reserve attestation").

    Anchored on-chain so the published figure cannot be quietly revised later,
    which is the same mechanism NFR 5 uses for the audit log.
    """
    chain = get_chain()
    supply = await chain.total_supply()
    usd = await bank.reserve_balance()
    period = period or datetime.now(UTC).strftime("%Y-%m")

    report = await bank.request_attestation(period=period, usd_balance=usd)
    anchor_tx = await chain.anchor(f"attestation:{period}:{usd}:{supply}")

    row = CusdcReserve(
        attestationDate=datetime.now(UTC),
        usdBalance=usd,
        cusdcSupply=supply,
        attestor=report.attestor,
        bankingPartner=bank.partner,
        reportUrl=report.report_url,
        anchorTxHash=anchor_tx,
    )
    db.add(row)
    db.flush()

    audit.record(
        db,
        entity_type="CusdcReserve",
        entity_id=row.id,
        action="reserve.attested",
        actor=ActorType.ADMIN,
        actor_id=performed_by,
        after=audit.snapshot(row),
        detail={"period": period, "coverageRatio": str(row.coverageRatio())},
    )
    db.commit()
    return row


async def dashboard(db: Session) -> dict:
    """Live reserve view for FR 5.3, the admin console and the transparency page."""
    chain = get_chain()
    supply = await chain.total_supply()
    usd = await bank.reserve_balance()

    latest = db.execute(
        select(CusdcReserve).order_by(desc(CusdcReserve.attestationDate)).limit(1)
    ).scalar_one_or_none()

    coverage = (usd / supply) if supply else Decimal("0")

    movements = (
        db.execute(select(ReserveMovement).order_by(desc(ReserveMovement.createdAt)).limit(20))
        .scalars()
        .all()
    )

    minted_total = db.execute(
        select(func.coalesce(func.sum(ReserveMovement.amount), 0)).where(ReserveMovement.kind == "MINT")
    ).scalar_one()
    burned_total = db.execute(
        select(func.coalesce(func.sum(ReserveMovement.amount), 0)).where(ReserveMovement.kind == "BURN")
    ).scalar_one()

    return {
        "cusdcSupply": str(supply),
        "usdReserve": str(usd),
        "coverageRatio": str(coverage.quantize(Decimal("0.000001"))),
        "coveragePercent": str((coverage * 100).quantize(Decimal("0.01"))),
        "isFullyBacked": usd >= supply,
        "bankingPartner": bank.partner,
        "attestor": bank.attestor,
        "simulated": True,
        "contract": {
            "symbol": "cUSDC",
            "decimals": 6,
            "network": "Base",
            "address": (await chain.health()).get("addresses", {}).get("CUSDC")
            or __import__("cowrie.config", fromlist=["settings"]).settings.cusdc_address,
        },
        "totals": {"minted": str(minted_total), "burned": str(burned_total)},
        "latestAttestation": {
            "date": latest.attestationDate.isoformat(),
            "usdBalance": str(latest.usdBalance),
            "cusdcSupply": str(latest.cusdcSupply),
            "coverageRatio": str(latest.coverageRatio()),
            "attestor": latest.attestor,
            "reportUrl": latest.reportUrl,
            "anchorTxHash": latest.anchorTxHash,
        }
        if latest
        else None,
        "movements": [
            {
                "id": m.id,
                "kind": m.kind,
                "amount": str(m.amount),
                "reference": m.usdDepositReference,
                "txHash": m.txHash,
                "performedBy": m.performedBy,
                "approvals": f"{m.approvals}/{TOTAL_SIGNERS}",
                "supplyAfter": str(m.supplyAfter),
                "createdAt": m.createdAt.isoformat(),
            }
            for m in movements
        ],
    }


def attestation_history(db: Session, limit: int = 24) -> list[dict]:
    rows = (
        db.execute(select(CusdcReserve).order_by(desc(CusdcReserve.attestationDate)).limit(limit))
        .scalars()
        .all()
    )
    return [
        {
            "id": r.id,
            "date": r.attestationDate.isoformat(),
            "usdBalance": str(r.usdBalance),
            "cusdcSupply": str(r.cusdcSupply),
            "coverageRatio": str(r.coverageRatio()),
            "coveragePercent": str((r.coverageRatio() * 100).quantize(Decimal("0.01"))),
            "isFullyBacked": r.isFullyBacked(),
            "attestor": r.attestor,
            "bankingPartner": r.bankingPartner,
            "reportUrl": r.reportUrl,
            "anchorTxHash": r.anchorTxHash,
        }
        for r in rows
    ]
