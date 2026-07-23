"""CowriePay transfers - FR 2.1 through FR 2.4.

Covers six of the nine CowriePay user functions in SRS §2.2: request a quote,
send, check the status of transfers, cancel a stuck transfer, check history,
and export statements.

The send flow is four steps, which is what NFR 6 allows ("3 taps or 4 steps"):

    1. POST /quotes                 amount + recipient -> itemised quote
    2. POST /transfers              accept the quote -> transaction in QUOTED
    3. POST /transfers/{id}/confirm PIN (+ second factor if large) -> AUTHORIZED
    4. the driver runs; the client watches /ws for state changes

Step 4 is not a request.  SRS §3.4 puts transaction status on a WebSocket, so
the client is pushed each state change rather than polling; the polling endpoint
exists only as a fallback for a client whose socket dropped.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..enums import IN_FLIGHT_STATES, DemoScenario, TransactionState
from ..models import Transaction, User
from ..services import transfer_service
from ..services.otp import requires_step_up
from ..services.otp import service as otp_service
from ..services.quote_engine import Quote
from ..services.quote_engine import engine as quote_engine
from .deps import current_user

router = APIRouter(tags=["cowriepay"])

#: Quotes are held here between step 1 and step 2.  They are short-lived by
#: definition (60 seconds, FR 2.1), so they never reach the database - a row
#: that is always deleted within a minute is a table that only ever costs.
_quotes: dict[str, Quote] = {}


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------


class QuoteRequest(BaseModel):
    amount: str = Field(description="Amount in NGN, as a decimal string")

    @field_validator("amount")
    @classmethod
    def _decimal(cls, v: str) -> str:
        try:
            value = Decimal(v)
        except InvalidOperation as exc:
            raise ValueError("amount must be a number") from exc
        if value <= 0:
            raise ValueError("amount must be positive")
        if value > Decimal("50000000"):
            raise ValueError("amount exceeds the corridor maximum")
        return v


class CreateTransfer(BaseModel):
    quoteId: str
    recipientName: str = Field(min_length=2, max_length=160)
    recipientMsisdn: str = Field(min_length=9, max_length=24)
    scenario: DemoScenario = DemoScenario.HAPPY
    """Demo-only.  Chooses which branch of the state machine this transfer
    takes, so every arrow on the diagram is demonstrable."""

    @field_validator("recipientMsisdn")
    @classmethod
    def _kenyan_msisdn(cls, v: str) -> str:
        cleaned = v.replace(" ", "").replace("-", "")
        if not cleaned.startswith("+254"):
            raise ValueError("Recipient must be a Kenyan M-Pesa number (+254...) on this corridor")
        return cleaned


class ConfirmTransfer(BaseModel):
    pin: str = Field(min_length=6, max_length=6)
    stepUpChallengeId: str | None = None
    stepUpCode: str | None = None


def _serialise(tx: Transaction) -> dict:
    """One transaction, with every fee on its own line (NFR 6)."""
    record = tx.onchainRecord
    return {
        "id": tx.id,
        "reference": tx.reference,
        "state": str(tx.state),
        "createdAt": tx.createdAt.isoformat(),
        "settledAt": tx.settledAt.isoformat() if tx.settledAt else None,
        "source": {"amount": str(tx.sourceAmount), "currency": tx.sourceCurrency},
        "destination": {"amount": str(tx.destinationAmount), "currency": tx.destinationCurrency},
        "fees": tx.fees.as_dict(),
        "fxRate": str(tx.fxRate),
        "recipient": {"name": tx.recipientName, "msisdn": tx.recipientMsisdn},
        "channel": tx.channel,
        "monoReference": tx.monoReference,
        "mpesaReceipt": tx.mpesaReceipt,
        "failureReason": tx.failureReason,
        "riskLevel": str(tx.riskLevel),
        "riskFlags": tx.riskFlags or [],
        "isStuck": tx.isStuck(),
        "canCancel": tx.state in IN_FLIGHT_STATES and tx.isStuck(),
        "secondsInState": round(tx.secondsInState(), 1),
        "costPercent": str((tx.totalCostRatio() * 100).quantize(Decimal("0.01"))),
        "onchain": {
            "txHash": record.txHash,
            "blockNumber": record.blockNumber,
            "confirmations": record.confirmations,
            "requiredConfirmations": settings.required_confirmations,
            "contractAddress": record.contractAddress,
            "isFinal": record.isFinal(),
            "rolledBack": record.rolledBack,
            "chainMode": record.chainMode,
            "cngnAmount": str(record.cngnAmount),
            "cusdcAmount": str(record.cusdcAmount),
        }
        if record
        else None,
    }


# ---------------------------------------------------------------------------
# step 1: quote (FR 2.1)
# ---------------------------------------------------------------------------


@router.post("/quotes")
def create_quote(body: QuoteRequest, user: User = Depends(current_user)) -> dict:
    """Price a transfer, itemised, locked for 60 seconds.

    Returns every fee separately.  There is no field in this response that
    bundles them, because NFR 6 forbids it.
    """
    try:
        quote = quote_engine.quote(source_amount=Decimal(body.amount))
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    _quotes[quote.id] = quote
    _prune_quotes()

    payload = quote.as_dict()
    payload["requiresSecondFactor"] = requires_step_up(float(quote.source.amount))
    payload["limitUsd"] = user.limitUsd()
    payload["withinLimit"] = float(quote.usdEquivalent) <= user.limitUsd()
    return payload


def _prune_quotes() -> None:
    for key in [k for k, v in _quotes.items() if v.isExpired()]:
        del _quotes[key]


# ---------------------------------------------------------------------------
# step 2: create (Created -> Quoted)
# ---------------------------------------------------------------------------


@router.post("/transfers", status_code=status.HTTP_201_CREATED)
def create_transfer(
    body: CreateTransfer,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    quote = _quotes.get(body.quoteId)
    if quote is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That quote has expired. Request a new one.")
    if quote.isExpired():
        del _quotes[body.quoteId]
        raise HTTPException(status.HTTP_410_GONE, "That quote has expired. Request a new one.")

    tx = transfer_service.create_transfer(
        db,
        user=user,
        quote=quote,
        recipient_name=body.recipientName,
        recipient_msisdn=body.recipientMsisdn,
        channel="COWRIEPAY",
        scenario=body.scenario,
    )

    response = _serialise(tx)
    response["quoteExpiresAt"] = quote.expiresAt.isoformat()
    response["secondsRemaining"] = quote.secondsRemaining()

    # FR 2.2 - large transfers need a second factor as well as the PIN.
    if requires_step_up(float(tx.sourceAmount)):
        challenge_id, code = otp_service.issue(purpose="STEP_UP", identifier=tx.id)
        response["stepUp"] = {
            "required": True,
            "challengeId": challenge_id,
            "reason": (
                f"Transfers of ${tx.sourceAmount / Decimal(str(settings.mid_market_ngn_per_usd)):,.0f} "
                "or more need a second factor (FR 2.2)."
            ),
            "demoCode": code,
            "demoNote": "Returned only because this build has no SMS provider wired.",
        }
    else:
        response["stepUp"] = {"required": False}

    return response


# ---------------------------------------------------------------------------
# step 3: confirm (Quoted -> Authorized)
# ---------------------------------------------------------------------------


@router.post("/transfers/{transfer_id}/confirm")
async def confirm_transfer(
    transfer_id: str,
    body: ConfirmTransfer,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """Confirm with the 6-digit PIN, plus a second factor when required.

    On success the transfer is AUTHORIZED and the background driver takes it the
    rest of the way; the client watches the WebSocket from here.
    """
    tx = db.get(Transaction, transfer_id)
    if tx is None or tx.senderId != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfer not found")

    # FR 2.2 second factor, checked before the PIN so a large transfer cannot be
    # confirmed by PIN alone even momentarily.
    if requires_step_up(float(tx.sourceAmount)):
        if not body.stepUpChallengeId or not body.stepUpCode:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "This transfer needs a second factor as well as your PIN (FR 2.2).",
            )
        try:
            challenge = otp_service.verify(
                challenge_id=body.stepUpChallengeId, code=body.stepUpCode
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc)) from exc
        if challenge.identifier != tx.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "That code belongs to a different transfer.")

    try:
        tx = await transfer_service.authorize(db, tx=tx, user=user, pin=body.pin)
    except transfer_service.TransferError as exc:
        db.refresh(tx)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    # Hand off to the background driver: steps 10-24 of the sequence diagram.
    transfer_service.launch(tx.id)

    response = _serialise(tx)
    response["message"] = "Confirmed. Watch /ws for live status."
    return response


# ---------------------------------------------------------------------------
# FR 2.4: cancel a stuck transfer
# ---------------------------------------------------------------------------


@router.post("/transfers/{transfer_id}/cancel")
async def cancel_transfer(
    transfer_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """The "Cancel and refund" button (FR 2.4).

    Only available once the transfer has been pending past the threshold; the
    service enforces that rather than trusting the UI to hide the button.
    """
    tx = db.get(Transaction, transfer_id)
    if tx is None or tx.senderId != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfer not found")

    try:
        tx = await transfer_service.cancel_and_refund(db, tx, actor_id=user.id)
    except transfer_service.TransferError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc

    return _serialise(tx)


# ---------------------------------------------------------------------------
# status and history
# ---------------------------------------------------------------------------


@router.get("/transfers/{transfer_id}")
def get_transfer(
    transfer_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """Polling fallback for a client whose WebSocket dropped."""
    tx = db.get(Transaction, transfer_id)
    if tx is None or tx.senderId != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfer not found")
    return _serialise(tx)


@router.get("/transfers")
def list_transfers(
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
    state: TransactionState | None = None,
    limit: int = Query(default=50, le=200),
) -> dict:
    """Transaction history (SRS §2.2, "check history")."""
    stmt = (
        select(Transaction)
        .where(Transaction.senderId == user.id)
        .order_by(Transaction.createdAt.desc())
        .limit(limit)
    )
    if state is not None:
        stmt = stmt.where(Transaction.state == state)

    rows = db.execute(stmt).scalars().all()
    settled = [t for t in rows if t.state == TransactionState.SETTLED]

    return {
        "transfers": [_serialise(t) for t in rows],
        "summary": {
            "count": len(rows),
            "settled": len(settled),
            "totalSentNgn": str(sum((t.sourceAmount for t in settled), Decimal("0"))),
            "totalReceivedKes": str(sum((t.destinationAmount for t in settled), Decimal("0"))),
            "totalFeesNgn": str(sum((t.fees.total() for t in settled), Decimal("0"))),
        },
    }


@router.get("/transfers/export/statement.csv")
def export_statement(
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> StreamingResponse:
    """Export statement (SRS §2.2 and the "View history / export statement" use case).

    CSV rather than PDF: a statement's job is to be reconciled against a bank
    record, and a spreadsheet does that better than a rendered document.
    """
    rows = (
        db.execute(
            select(Transaction)
            .where(Transaction.senderId == user.id)
            .order_by(Transaction.createdAt.desc())
        )
        .scalars()
        .all()
    )

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "Reference", "Created (UTC)", "Settled (UTC)", "State",
            "Sent", "Currency", "Received", "Currency",
            "FX spread", "Network gas", "Liquidity spread", "Cowrie fee", "Total fees",
            "Cost %", "FX rate", "Recipient", "M-Pesa receipt", "On-chain tx",
        ]
    )
    for t in rows:
        fees = t.fees
        writer.writerow(
            [
                t.reference,
                t.createdAt.strftime("%Y-%m-%d %H:%M:%S"),
                t.settledAt.strftime("%Y-%m-%d %H:%M:%S") if t.settledAt else "",
                str(t.state),
                f"{t.sourceAmount:.2f}", t.sourceCurrency,
                f"{t.destinationAmount:.2f}", t.destinationCurrency,
                f"{fees.fxSpread:.2f}", f"{fees.networkGas:.2f}",
                f"{fees.liquiditySpread:.2f}", f"{fees.cowrieFee:.2f}", f"{fees.total():.2f}",
                f"{t.totalCostRatio() * 100:.2f}",
                f"{t.fxRate:.6f}",
                t.recipientName,
                t.mpesaReceipt,
                t.onchainRecord.txHash if t.onchainRecord else "",
            ]
        )

    buffer.seek(0)
    filename = f"cowrie-statement-{user.phone.lstrip('+')}-{datetime.now(UTC):%Y%m%d}.csv"
    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/corridor")
def corridor_info() -> dict:
    """Live corridor pricing, for the Home screen and the marketing page."""
    mid = quote_engine.mid_market_rate()
    sample = quote_engine.quote(source_amount=Decimal("100000"))
    return {
        "source": settings.corridor_source,
        "destination": settings.corridor_destination,
        "midMarketRate": str(mid),
        "quoteLockSeconds": settings.quote_lock_seconds,
        "feeSchedule": {
            "fxSpreadBps": settings.fx_spread_bps,
            "liquiditySpreadBps": settings.liquidity_spread_bps,
            "cowrieFeeBps": settings.cowrie_fee_bps,
            "networkGasUsd": settings.network_gas_usd,
            "allInPercent": str((sample.costRatio() * 100).quantize(Decimal("0.01"))),
        },
        "benchmark": {
            "subSaharanAfricaAverage": "7.4",
            "globalAverage": "6.2",
            "unSdgTarget": "3.0",
            "source": "World Bank Remittance Prices Worldwide, Issue 53 (Q1 2025)",
        },
        "settlement": {
            "requiredConfirmations": settings.required_confirmations,
            "blockSeconds": settings.base_block_seconds,
            "targetSeconds": 30,
        },
    }
