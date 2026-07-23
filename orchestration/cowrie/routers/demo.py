"""Demo controls.

These endpoints exist so the prototype can demonstrate the *whole* state machine
diagram rather than only its happy path. A demo that can only show a transfer
succeeding has not demonstrated NFR 3, because NFR 3 is a claim about what
happens when things fail.

Every scenario maps to one labelled arrow in docs/uml/cowrie_state.puml:

    HAPPY            ... -> Settled
    SANCTIONS_HOLD   Authorized -> Failed         "sanctions hold"
    MONO_ERROR       Authorized -> Failed         "Mono error"
    ONRAMP_TIMEOUT   OnRampPending -> Refunding   "timeout > 10 min"
    CHAIN_ROLLBACK   Bridging -> Refunding        "chain rollback"
    PAYOUT_FAILED    OffRampPending -> Refunding  "payout failed / timeout"

This module is registered only when COWRIE_ENVIRONMENT is 'demo', which it
always is in this build. In a real deployment it would not be mounted at all,
and main.py enforces that rather than relying on a convention.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..enums import ALLOWED_TRANSITIONS, DemoScenario, TransactionState
from ..models import Transaction, User
from ..services.notifications import hub

router = APIRouter(prefix="/demo", tags=["demo"])


SCENARIO_DESCRIPTIONS = {
    DemoScenario.HAPPY: {
        "label": "Successful transfer",
        "arrow": "OffRampPending -> Settled",
        "expect": "Settles in about 30 seconds after 12 confirmations, recipient credited on M-Pesa.",
        "requirement": "FR 2.1-2.3, NFR 1",
    },
    DemoScenario.SANCTIONS_HOLD: {
        "label": "Sanctions hit",
        "arrow": "Authorized -> Failed",
        "expect": "Blocked at authorisation. Nothing is debited. The screening result is recorded.",
        "requirement": "FR 1.3, NFR 4",
    },
    DemoScenario.MONO_ERROR: {
        "label": "Bank debit declined",
        "arrow": "Authorized -> Failed",
        "expect": "Mono refuses the debit. The transfer ends terminal with nothing taken.",
        "requirement": "FR 2.2",
    },
    DemoScenario.ONRAMP_TIMEOUT: {
        "label": "On-ramp timeout",
        "arrow": "OnRampPending -> Refunding -> Refunded",
        "expect": "The naira is debited, the on-ramp stalls, and the money is returned.",
        "requirement": "FR 2.4, NFR 3",
    },
    DemoScenario.CHAIN_ROLLBACK: {
        "label": "Chain reorganisation",
        "arrow": "Bridging -> Refunding -> Refunded",
        "expect": "Confirmations start accruing, the chain rolls back, and the sender is refunded.",
        "requirement": "FR 3.3, NFR 3",
    },
    DemoScenario.PAYOUT_FAILED: {
        "label": "M-Pesa payout failure",
        "arrow": "OffRampPending -> Refunding -> Refunded",
        "expect": "The bridge settles but Daraja rejects the payout, so the naira comes back.",
        "requirement": "FR 2.3, NFR 3",
    },
}


@router.get("/scenarios")
def scenarios() -> dict:
    """The scenario switch shown in CowriePay's demo panel."""
    return {
        "scenarios": [
            {"value": str(key), **value} for key, value in SCENARIO_DESCRIPTIONS.items()
        ],
        "note": (
            "Choose a scenario before confirming a transfer. Each one drives the transaction "
            "down a different arrow of the state machine diagram."
        ),
    }


@router.get("/state-machine")
def state_machine() -> dict:
    """The transition table the code actually enforces.

    Served from `enums.ALLOWED_TRANSITIONS` rather than hard-coded here, so this
    endpoint cannot claim a transition the code would refuse.
    """
    return {
        "states": [str(s) for s in TransactionState],
        "transitions": [
            {"from": str(state), "to": sorted(str(t) for t in targets)}
            for state, targets in ALLOWED_TRANSITIONS.items()
        ],
        "terminal": [str(s) for s, t in ALLOWED_TRANSITIONS.items() if not t],
        "source": "docs/uml/cowrie_state.puml",
    }


@router.get("/config")
def demo_config() -> dict:
    """The timings and thresholds the demo runs at, so the video can cite them."""
    return {
        "environment": settings.environment,
        "chainMode": settings.chain_mode,
        "demoSpeed": settings.demo_speed,
        "timings": {
            "quoteLockSeconds": settings.quote_lock_seconds,
            "requiredConfirmations": settings.required_confirmations,
            "blockSeconds": settings.base_block_seconds,
            "expectedBridgeSeconds": settings.required_confirmations * settings.base_block_seconds,
            "stuckCancelSeconds": settings.stuck_cancel_seconds,
            "stuckRefundSeconds": settings.stuck_refund_seconds,
        },
        "pricing": {
            "fxSpreadBps": settings.fx_spread_bps,
            "liquiditySpreadBps": settings.liquidity_spread_bps,
            "cowrieFeeBps": settings.cowrie_fee_bps,
            "totalBps": settings.fx_spread_bps + settings.liquidity_spread_bps + settings.cowrie_fee_bps,
            "networkGasUsd": settings.network_gas_usd,
        },
        "credentials": {
            "note": "Seeded accounts. See the README.",
            "cowriepay": {"phone": "+2348012345678", "pin": "123456"},
            "admin": {"email": "amara@cowrie.demo", "password": "cowrie-demo"},
            "regulator": {"regulator": "SEC_NIGERIA", "accessCode": "sec-ng-demo"},
        },
    }


@router.post("/accelerate/{transfer_id}")
async def accelerate(transfer_id: str, db: Session = Depends(get_session)) -> dict:
    """Make a stuck transfer immediately eligible for cancellation (FR 2.4).

    FR 2.4 puts the cancel button at 5 minutes and the auto-refund at 10. Both
    are correct and both are far too long to wait for on camera, so this pushes
    a transfer's clock back rather than changing the thresholds - the rule under
    test stays exactly as specified.
    """
    from datetime import timedelta

    tx = db.get(Transaction, transfer_id)
    if tx is None:
        return {"error": "Transfer not found"}

    tx.stateEnteredAt = tx.stateEnteredAt - timedelta(seconds=settings.stuck_cancel_seconds + 5)
    db.commit()
    await hub.push_transaction(tx, "transaction.state_changed", {"accelerated": True})

    return {
        "id": tx.id,
        "state": str(tx.state),
        "isStuck": tx.isStuck(),
        "note": "Clock moved back past the 5 minute threshold; the cancel button is now live.",
    }


@router.get("/status")
def demo_status(db: Session = Depends(get_session)) -> dict:
    """Counts by state, for a quick read on what the demo database contains."""
    counts = dict(
        db.execute(select(Transaction.state, func.count()).group_by(Transaction.state)).all()
    )
    users = db.execute(select(func.count()).select_from(User)).scalar_one()
    return {
        "users": users,
        "transactionsByState": {str(state): count for state, count in counts.items()},
        "total": sum(counts.values()),
    }
