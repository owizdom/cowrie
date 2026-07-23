"""Public transparency page - SRS §3.1.

"The Cowrie public transparency page (read-only mode) reveals the live supply of
cUSDC, the reserve breakdown, attestation report, anchor proof, and the contract
address."

All five, and no authentication: a transparency page that requires a login is
not one. It is also the honest place to state what this build actually is, so
the regulatory-position block is served from here rather than buried in a
README nobody reading the site will open.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..adapters.chain import get_chain
from ..config import settings
from ..db import get_session
from ..enums import TransactionState
from ..models import AuditLogEntry, CusdcReserve, Transaction
from ..services import audit, reserve_service
from ..services.quote_engine import engine as quote_engine

router = APIRouter(prefix="/transparency", tags=["transparency"])


@router.get("")
async def transparency(db: Session = Depends(get_session)) -> dict:
    """Everything the public page renders, in one call."""
    chain = get_chain()
    health = await chain.health()
    supply = await chain.total_supply()
    reserve = await reserve_service.bank.reserve_balance()

    latest = db.execute(
        select(CusdcReserve).order_by(CusdcReserve.attestationDate.desc()).limit(1)
    ).scalar_one_or_none()

    settled = (
        db.execute(select(Transaction).where(Transaction.state == TransactionState.SETTLED))
        .scalars()
        .all()
    )
    volume_ngn = sum((t.sourceAmount for t in settled), Decimal("0"))
    fees_ngn = sum((t.fees.total() for t in settled), Decimal("0"))
    durations = sorted(
        (t.settledAt - t.createdAt).total_seconds() for t in settled if t.settledAt and t.createdAt
    )

    anchored = db.execute(
        select(func.count()).select_from(AuditLogEntry).where(AuditLogEntry.anchorTxHash != "")
    ).scalar_one()

    return {
        # 1. live supply
        "supply": {
            "cusdcSupply": str(supply),
            "symbol": "cUSDC",
            "decimals": 6,
            "network": "Base",
            "chainId": settings.chain_id,
        },
        # 2. reserve breakdown
        "reserve": {
            "usdBalance": str(reserve),
            "cusdcSupply": str(supply),
            "coverageRatio": str(
                (reserve / supply).quantize(Decimal("0.000001")) if supply else Decimal("0")
            ),
            "coveragePercent": str(
                ((reserve / supply) * 100).quantize(Decimal("0.01")) if supply else Decimal("0")
            ),
            "isFullyBacked": reserve >= supply,
            "bankingPartner": reserve_service.bank.partner,
            "custodyModel": "1:1 USD held in a segregated trust account",
        },
        # 3. attestation report
        "attestation": {
            "latest": {
                "date": latest.attestationDate.isoformat(),
                "attestor": latest.attestor,
                "usdBalance": str(latest.usdBalance),
                "cusdcSupply": str(latest.cusdcSupply),
                "coverageRatio": str(latest.coverageRatio()),
                "reportUrl": latest.reportUrl,
            }
            if latest
            else None,
            "history": reserve_service.attestation_history(db, limit=12),
            "cadence": "Monthly, by an independent third-party attestor",
        },
        # 4. anchor proof
        "anchorProof": {
            "anchoredEntries": anchored,
            "latestAnchorTxHash": latest.anchorTxHash if latest else "",
            "mechanism": (
                "Each audit entry commits to the hash of the entry before it. The head hash of "
                "each batch is written on-chain, so altering any historical entry would also "
                "require rewriting a block."
            ),
            "chainIntegrity": audit.verify_chain(db),
        },
        # 5. contract addresses
        "contracts": {
            "cUSDC": health.get("addresses", {}).get("CUSDC") or settings.cusdc_address,
            "cNGN": health.get("addresses", {}).get("CNGN") or settings.cngn_address,
            "CowrieBridge": health.get("addresses", {}).get("CowrieBridge") or settings.bridge_address,
            "network": health["network"],
            "chainMode": health["mode"],
            "contractsDeployed": health["contractsDeployed"],
        },
        # corridor performance, published rather than claimed
        "corridor": {
            "pair": f"{settings.corridor_source} -> {settings.corridor_destination}",
            "midMarketRate": str(quote_engine.mid_market_rate()),
            "settledCount": len(settled),
            "volumeNgn": str(volume_ngn),
            "totalFeesNgn": str(fees_ngn),
            "averageCostPercent": str(
                ((fees_ngn / volume_ngn) * 100).quantize(Decimal("0.01"))
                if volume_ngn
                else Decimal("0")
            ),
            "medianSettlementSeconds": round(durations[len(durations) // 2], 2) if durations else 0,
            "targetCostPercent": "1.00",
            "benchmarkSubSaharanAfrica": "7.4",
            "benchmarkSource": "World Bank, Remittance Prices Worldwide, Issue 53 (Q1 2025)",
        },
        # the honest position
        "disclosure": {
            "buildType": "Prototype with seeded demonstration data",
            "statements": [
                "No real money moves through this system.",
                "cUSDC is not issued on Base mainnet. The contracts compile and pass their tests, "
                "and run on a local development chain.",
                "No banking partner holds reserves. The reserve figures are seeded.",
                "Mono, Safaricom Daraja and Smile ID are simulated. No live credential for any of "
                "them exists in this build.",
                "Cowrie does not hold VASP registration with the Nigeria SEC or the Kenya CMA.",
                "Attestations shown here are generated by the demo, not by an auditor.",
            ],
            "whatIsReal": [
                "The settlement state machine, including every refund path.",
                "The hash-chained audit log and its verification.",
                "The fee model and the sub-1% corridor arithmetic.",
                "The Solidity contracts, their tests, and their behaviour on a local chain.",
                "Sanctions screening logic and the enforcement path behind it.",
            ],
            "asOf": datetime.now(UTC).isoformat(),
        },
    }


@router.get("/supply")
async def supply() -> dict:
    """Machine-readable supply endpoint, for anyone tracking the token."""
    chain = get_chain()
    total = await chain.total_supply()
    reserve = await reserve_service.bank.reserve_balance()
    return {
        "symbol": "cUSDC",
        "totalSupply": str(total),
        "reserveUsd": str(reserve),
        "coverageRatio": str((reserve / total).quantize(Decimal("0.000001")) if total else 0),
        "asOf": datetime.now(UTC).isoformat(),
        "simulated": True,
    }
