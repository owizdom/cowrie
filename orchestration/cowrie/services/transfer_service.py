"""Transfer Service - the orchestrator of the corridor.

This module is the executable form of two diagrams:

    docs/uml/cowrie_sequence.puml   the 24 numbered messages of one NGN->KES
                                    transfer, in order
    docs/uml/cowrie_state.puml      the eleven states and every labelled arrow
                                    between them

Every state change goes through `transition()`, which refuses any move that is
not an arrow on the state machine diagram.  That is the point: the diagram is
not documentation of the code, it is a table the code is checked against
(enums.ALLOWED_TRANSITIONS), so the two cannot drift.

The happy path, with its sequence-diagram step numbers:

    Created                                     sender starts transfer
    -> Quoted           steps 1-4               Quote Engine, locked 60s
    -> Authorized       steps 5-9               PIN + sanctions + persist
    -> OnRampPending    steps 10-11             Mono debits NGN
    -> Bridging         steps 12-15             bridge cNGN->cUSDC, 12 confs
    -> OffRampPending   step 16                 Daraja B2C submitted
    -> Settled          steps 17-20             M-Pesa credited, receipt pushed

and the four escape hatches that make NFR 3 true:

    Authorized      -> Failed      sanctions hold / Mono error
    OnRampPending   -> Refunding   timeout > 10 min
    Bridging        -> Refunding   chain rollback
    OffRampPending  -> Refunding   payout failed / timeout
    Refunding       -> Refunded    NGN returned to sender    steps 21-24
    Quoted          -> Cancelled   quote expires (> 60s)

Concurrency note
----------------
The driver runs as a background asyncio task per transfer and opens a short
session for each step rather than holding one open across the whole flow.  A
transfer takes ~30 seconds of mostly waiting; holding a database transaction
open for that long would block the admin console's live feed, and on SQLite it
would block everything.
"""

from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..adapters.chain import get_chain
from ..adapters.daraja import DarajaAdapter
from ..adapters.mono import MonoAdapter
from ..config import settings
from ..db import session_scope
from ..enums import (
    ALLOWED_TRANSITIONS,
    IN_FLIGHT_STATES,
    ActorType,
    DemoScenario,
    IntentStatus,
    TransactionState,
)
from ..models import PaymentIntent, Transaction, User, utcnow
from ..security import verify_secret
from . import audit, monitoring
from .notifications import hub
from .quote_engine import Quote
from .quote_engine import engine as quote_engine
from .sanctions import service as sanctions_service

mono = MonoAdapter()
daraja = DarajaAdapter()


class TransferError(Exception):
    """A refusal the caller should surface to the user as-is."""


def _reference() -> str:
    return f"CWR-{secrets.token_hex(3).upper()}"


# ---------------------------------------------------------------------------
# state transitions
# ---------------------------------------------------------------------------


async def transition(
    db: Session,
    tx: Transaction,
    to_state: TransactionState,
    *,
    actor: ActorType = ActorType.SYSTEM,
    actor_id: str = "state-machine",
    reason: str = "",
    detail: dict | None = None,
) -> None:
    """Move a transaction to `to_state`, or refuse.

    Three things happen atomically from the caller's point of view: the state
    is checked against the diagram, the change is written to the hash-chained
    audit log (NFR 5), and the new state is pushed to the sender and the admin
    feed over WebSocket.

    An illegal transition raises rather than logging a warning, because a
    payment system that quietly accepts an impossible state change is a payment
    system that loses money.
    """
    allowed = ALLOWED_TRANSITIONS.get(tx.state, set())
    if to_state not in allowed:
        raise TransferError(
            f"illegal transition {tx.state} -> {to_state}; "
            f"the state machine allows {sorted(str(s) for s in allowed) or 'nothing (terminal state)'}"
        )

    before = audit.snapshot(tx)
    tx.state = to_state
    tx.stateEnteredAt = utcnow()
    if reason:
        tx.failureReason = reason
    if to_state == TransactionState.SETTLED:
        tx.settledAt = utcnow()

    audit.record(
        db,
        entity_type="Transaction",
        entity_id=tx.id,
        action=f"transaction.{str(to_state).lower()}",
        actor=actor,
        actor_id=actor_id,
        before=before,
        after=audit.snapshot(tx),
        detail={"reason": reason, **(detail or {})},
    )
    db.commit()

    await hub.push_transaction(
        tx,
        event="transaction.state_changed",
        extra={"reason": reason, **(detail or {})},
    )


# ---------------------------------------------------------------------------
# step 1-4: quote  (Created -> Quoted)
# ---------------------------------------------------------------------------


def create_transfer(
    db: Session,
    *,
    user: User,
    quote: Quote,
    recipient_name: str,
    recipient_msisdn: str,
    channel: str = "COWRIEPAY",
    scenario: DemoScenario = DemoScenario.HAPPY,
) -> Transaction:
    """Persist a quoted transfer.

    The transaction is created in CREATED and immediately moved to QUOTED,
    which mirrors the diagram: `[*] --> Created : sender starts transfer` then
    `Created --> Quoted : request quote (rate locked 60s)`.  Both states are
    real and both are logged, even though the app passes through CREATED in
    microseconds - collapsing them would make the audit trail lie about what
    happened.
    """
    tx = Transaction(
        reference=_reference(),
        senderId=user.id,
        state=TransactionState.CREATED,
        fxRate=quote.fxRate,
        sourceAmount=quote.source.amount,
        sourceCurrency=quote.source.currency,
        destinationAmount=quote.destination.amount,
        destinationCurrency=quote.destination.currency,
        feeFxSpread=quote.fees.fxSpread,
        feeNetworkGas=quote.fees.networkGas,
        feeLiquiditySpread=quote.fees.liquiditySpread,
        feeCowrie=quote.fees.cowrieFee,
        recipientName=recipient_name,
        recipientMsisdn=recipient_msisdn,
        quoteExpiresAt=quote.expiresAt,
        channel=channel,
        demoScenario=str(scenario),
    )
    db.add(tx)
    db.flush()

    audit.record(
        db,
        entity_type="Transaction",
        entity_id=tx.id,
        action="transaction.created",
        actor=ActorType.USER,
        actor_id=user.id,
        after=audit.snapshot(tx),
        detail={"quoteId": quote.id, "channel": channel},
    )

    # Created -> Quoted, synchronously and without the async transition helper
    # because nothing is listening on the socket yet.
    tx.state = TransactionState.QUOTED
    tx.stateEnteredAt = utcnow()
    audit.record(
        db,
        entity_type="Transaction",
        entity_id=tx.id,
        action="transaction.quoted",
        actor=ActorType.SYSTEM,
        actor_id="quote-engine",
        after=audit.snapshot(tx),
        detail={"fxRate": str(quote.fxRate), "expiresAt": quote.expiresAt.isoformat()},
    )
    db.commit()
    return tx


# ---------------------------------------------------------------------------
# step 5-9: authorize  (Quoted -> Authorized | Failed | Cancelled)
# ---------------------------------------------------------------------------


async def authorize(
    db: Session,
    *,
    tx: Transaction,
    user: User,
    pin: str,
) -> Transaction:
    """Confirm a transfer with the sender's 6-digit PIN.

    Sequence diagram steps 6-9: confirmTransfer(quoteId, PIN), screen against
    OFAC/UN/EU, then create the transaction in AUTHORIZED.

    Order matters and is deliberate.  The quote expiry is checked first (a
    stale price must never be honoured), then the PIN (authentication before
    anything expensive), then sanctions (FR 1.3), then the balance.  A sanctions
    hit is recorded even though the transfer is refused, because a refused
    attempt by a listed person is precisely what a regulator wants to see.
    """
    if tx.state != TransactionState.QUOTED:
        raise TransferError(f"transfer is {tx.state}, not awaiting confirmation")

    # -- quote expiry: Quoted -> Cancelled ---------------------------------
    if tx.quoteExpiresAt and datetime.now(UTC) >= tx.quoteExpiresAt:
        await transition(
            db,
            tx,
            TransactionState.CANCELLED,
            reason="Quote expired before confirmation (FR 2.1 locks the rate for 60 seconds)",
        )
        raise TransferError("This quote has expired. Request a new one to see the current rate.")

    # -- PIN (FR 2.2) -------------------------------------------------------
    if not verify_secret(pin, user._pinHash):
        audit.record(
            db,
            entity_type="Transaction",
            entity_id=tx.id,
            action="transaction.pin_rejected",
            actor=ActorType.USER,
            actor_id=user.id,
            detail={"reference": tx.reference},
        )
        db.commit()
        raise TransferError("Incorrect PIN.")

    if user.isFrozen:
        await transition(
            db, tx, TransactionState.AUTHORIZED, reason=""
        )
        await transition(
            db,
            tx,
            TransactionState.FAILED,
            reason="Account is frozen pending compliance review",
        )
        raise TransferError("This account is frozen pending compliance review.")

    scenario = DemoScenario(tx.demoScenario)

    # -- sanctions screening (FR 1.3) --------------------------------------
    screening = sanctions_service.screen_user(
        db,
        user,
        trigger="TRANSFER",
        transaction_id=tx.id,
        force_hit=(scenario is DemoScenario.SANCTIONS_HOLD),
    )

    # The transfer becomes AUTHORIZED first even when it is about to fail,
    # because the state machine has no Quoted -> Failed arrow: the only route
    # to Failed is through Authorized.  Following the diagram exactly is worth
    # one extra row in the log.
    await transition(db, tx, TransactionState.AUTHORIZED, actor=ActorType.USER, actor_id=user.id)

    if not screening.passed:
        await transition(db, tx, TransactionState.FAILED, reason=screening.reason)
        raise TransferError(screening.reason)

    # -- limits (FR 1.2) and balance ---------------------------------------
    usd_value = tx.sourceAmount / Decimal(str(settings.mid_market_ngn_per_usd))
    limit = Decimal(str(user.limitUsd()))
    if usd_value > limit:
        message = (
            f"This transfer is ${usd_value:,.2f}, above your {user.kycLevel} limit of "
            f"${limit:,.2f}. Complete the next verification level to raise it (FR 1.2)."
        )
        await transition(db, tx, TransactionState.FAILED, reason=message)
        raise TransferError(message)

    if user.ngnBalance < tx.sourceAmount:
        message = "Insufficient balance in the linked bank account."
        await transition(db, tx, TransactionState.FAILED, reason=message)
        raise TransferError(message)

    # -- risk scoring for the admin feed (FR 5.1) --------------------------
    level, flags = monitoring.score_transaction(db, tx, user)
    tx.riskLevel = level
    tx.riskFlags = flags
    db.commit()

    return tx


# ---------------------------------------------------------------------------
# steps 10-24: the driver  (Authorized -> ... -> Settled | Refunded)
# ---------------------------------------------------------------------------


async def drive(transaction_id: str) -> None:
    """Carry an authorized transfer to a terminal state.

    Runs as a background task.  Every failure path leads to a terminal state -
    there is no branch that leaves a transfer in flight, which is the whole
    content of NFR 3.  The bare `except` at the end is therefore not laziness:
    an unhandled exception here would strand a sender's money, so anything
    unexpected is converted into a refund.
    """
    try:
        await _drive_inner(transaction_id)
    except Exception as exc:  # noqa: BLE001 - see docstring
        await _emergency_refund(transaction_id, f"Unexpected settlement error: {exc}")


async def _drive_inner(transaction_id: str) -> None:
    chain = get_chain()

    # ---- steps 10-11: Mono debit ----------------------------------------
    #
    # The debit is attempted while the transfer is still AUTHORIZED, because the
    # state machine diagram has exactly one arrow for a failure here:
    #
    #     Authorized --> Failed : sanctions hold / Mono error
    #
    # Moving to OnRampPending first would make that arrow unreachable, since
    # OnRampPending's only failure exit is Refunding.  So the transfer enters
    # OnRampPending only once the bank has accepted the debit, which is also
    # what the state reads as: waiting for the funds, not waiting to ask.
    with session_scope() as db:
        tx = db.get(Transaction, transaction_id)
        if tx is None or tx.state != TransactionState.AUTHORIZED:
            return
        scenario = DemoScenario(tx.demoScenario)
        amount = tx.sourceAmount
        sender_id = tx.senderId

    debit = await mono.debit(
        user_id=sender_id or "",
        amount=amount,
        narration="Cowrie NGN->KES transfer",
        force_error=(scenario is DemoScenario.MONO_ERROR),
    )

    with session_scope() as db:
        tx = db.get(Transaction, transaction_id)
        if tx is None or tx.state != TransactionState.AUTHORIZED:
            return

        if not debit.accepted:
            # Authorized -> Failed. Nothing was debited, so there is nothing to
            # return and no refund leg is needed.
            await transition(db, tx, TransactionState.FAILED, reason=debit.failure_reason)
            _mark_intent(db, tx, IntentStatus.FAILED)
            await _fire_webhook(db, tx, "payment.failed")
            return

        # Authorized -> OnRampPending: the bank accepted, funds are in flight.
        await transition(db, tx, TransactionState.ONRAMP_PENDING, detail={"partner": mono.name})

        tx.monoReference = debit.reference
        user = db.get(User, tx.senderId) if tx.senderId else None
        if user:
            user.ngnBalance -= tx.sourceAmount
        db.commit()
        await hub.push_transaction(tx, "onramp.received", {"monoReference": debit.reference})

    # ---- the on-ramp timeout branch (OnRampPending -> Refunding) ---------
    if scenario is DemoScenario.ONRAMP_TIMEOUT:
        await asyncio.sleep(settings.scaled(6))
        with session_scope() as db:
            tx = db.get(Transaction, transaction_id)
            if tx and tx.state == TransactionState.ONRAMP_PENDING:
                await transition(
                    db,
                    tx,
                    TransactionState.REFUNDING,
                    reason="On-ramp did not settle within the 10 minute SLA (NFR 3)",
                )
                await _complete_refund(db, tx, debited=True)
        return

    # ---- steps 12-15: bridge  (OnRampPending -> Bridging) ----------------
    with session_scope() as db:
        tx = db.get(Transaction, transaction_id)
        if tx is None or tx.state != TransactionState.ONRAMP_PENDING:
            return
        cngn = tx.sourceAmount
        cusdc = (tx.sourceAmount / Decimal(str(settings.mid_market_ngn_per_usd))).quantize(
            Decimal("0.000001")
        )
        await transition(db, tx, TransactionState.BRIDGING, detail={"contract": settings.bridge_address})

    submission = await chain.submit_bridge(
        transfer_id=transaction_id, cngn_amount=cngn, cusdc_amount=cusdc
    )

    from ..models import OnchainRecord

    with session_scope() as db:
        tx = db.get(Transaction, transaction_id)
        if tx is None:
            return
        record = OnchainRecord(
            transactionId=tx.id,
            txHash=submission.tx_hash,
            blockNumber=submission.block_number,
            confirmations=0,
            contractAddress=submission.contract_address,
            chainMode=submission.mode,
            gasUsedUsd=submission.gas_used_usd,
            cngnAmount=submission.cngn_amount,
            cusdcAmount=submission.cusdc_amount,
        )
        db.add(record)
        db.commit()
        await hub.push_transaction(
            tx,
            "bridge.submitted",
            {
                "txHash": submission.tx_hash,
                "blockNumber": submission.block_number,
                "chainMode": submission.mode,
                "requiredConfirmations": settings.required_confirmations,
            },
        )

    if scenario is DemoScenario.CHAIN_ROLLBACK:
        # Let a few confirmations accrue first so the rollback is visibly a
        # reorg rather than an instant rejection.
        await asyncio.sleep(settings.scaled(settings.base_block_seconds * 4))
        if hasattr(chain, "force_rollback"):
            chain.force_rollback(submission.tx_hash)

    # ---- step 14: await >= 12 confirmations (FR 3.3) ---------------------
    deadline = asyncio.get_event_loop().time() + settings.scaled(
        settings.base_block_seconds * settings.required_confirmations * 4 + 30
    )
    final = False
    while asyncio.get_event_loop().time() < deadline:
        status = await chain.confirmation_status(submission)

        with session_scope() as db:
            tx = db.get(Transaction, transaction_id)
            if tx is None or tx.state != TransactionState.BRIDGING:
                return
            if tx.onchainRecord:
                tx.onchainRecord.confirmations = status.confirmations
                tx.onchainRecord.rolledBack = status.rolled_back
                db.commit()
            await hub.push_transaction(
                tx,
                "bridge.confirmation",
                {
                    "confirmations": status.confirmations,
                    "requiredConfirmations": settings.required_confirmations,
                    "headBlock": status.head_block,
                    "txHash": submission.tx_hash,
                },
            )

            if status.rolled_back:
                await transition(
                    db,
                    tx,
                    TransactionState.REFUNDING,
                    reason="Base reorganisation rolled the bridge transaction back (FR 3.3)",
                )
                await _complete_refund(db, tx, debited=True)
                return

        if status.final:
            final = True
            break

        await asyncio.sleep(settings.scaled(settings.base_block_seconds))

    if not final:
        with session_scope() as db:
            tx = db.get(Transaction, transaction_id)
            if tx and tx.state == TransactionState.BRIDGING:
                await transition(
                    db,
                    tx,
                    TransactionState.REFUNDING,
                    reason="Bridge did not reach 12 confirmations within the SLA (NFR 3)",
                )
                await _complete_refund(db, tx, debited=True)
        return

    # ---- step 16: Daraja payout  (Bridging -> OffRampPending) ------------
    with session_scope() as db:
        tx = db.get(Transaction, transaction_id)
        if tx is None or tx.state != TransactionState.BRIDGING:
            return
        payout_amount = tx.destinationAmount
        msisdn = tx.recipientMsisdn
        await transition(db, tx, TransactionState.OFFRAMP_PENDING, detail={"partner": daraja.name})

    payout = await daraja.payout(
        msisdn=msisdn,
        amount=payout_amount,
        remarks="Cowrie cross-border transfer",
        force_failure=(scenario is DemoScenario.PAYOUT_FAILED),
    )

    with session_scope() as db:
        tx = db.get(Transaction, transaction_id)
        if tx is None or tx.state != TransactionState.OFFRAMP_PENDING:
            return

        if not payout.credited:
            await transition(db, tx, TransactionState.REFUNDING, reason=payout.failure_reason)
            await _complete_refund(db, tx, debited=True)
            return

        # ---- steps 17-20: settled ---------------------------------------
        # FR 2.3: match the M-Pesa transaction ID to the on-chain record.
        tx.mpesaReceipt = payout.receipt
        db.commit()

        await transition(
            db,
            tx,
            TransactionState.SETTLED,
            detail={
                "mpesaReceipt": payout.receipt,
                "txHash": submission.tx_hash,
                "conversationId": payout.conversation_id,
            },
        )
        await hub.push_transaction(
            tx,
            "transfer.completed",
            {
                "mpesaReceipt": payout.receipt,
                "txHash": submission.tx_hash,
                "settledAt": tx.settledAt.isoformat() if tx.settledAt else None,
                "elapsedSeconds": round((tx.settledAt - tx.createdAt).total_seconds(), 1)
                if tx.settledAt
                else None,
            },
        )

        _mark_intent(db, tx, IntentStatus.SETTLED)
        await _fire_webhook(db, tx, "payment.settled")


# ---------------------------------------------------------------------------
# refund  (Refunding -> Refunded)
# ---------------------------------------------------------------------------


async def _complete_refund(db: Session, tx: Transaction, *, debited: bool) -> None:
    """Steps 21-24: return the NGN and tell the sender.

    `debited` distinguishes a refund of money that actually left the sender's
    account from the reversal of a debit that never succeeded.  Both end in
    REFUNDED so the sender sees one consistent outcome, but only the first
    moves money back.
    """
    if debited:
        result = await mono.refund(original_reference=tx.monoReference, amount=tx.sourceAmount)
        user = db.get(User, tx.senderId) if tx.senderId else None
        if user and result.refunded:
            user.ngnBalance += tx.sourceAmount
        db.commit()

    await transition(db, tx, TransactionState.REFUNDED)
    await hub.push_transaction(
        tx,
        "transfer.refunded",
        {
            "reason": tx.failureReason,
            "amountReturned": str(tx.sourceAmount),
            "currency": tx.sourceCurrency,
        },
    )
    _mark_intent(db, tx, IntentStatus.FAILED)
    await _fire_webhook(db, tx, "payment.failed")


async def _emergency_refund(transaction_id: str, reason: str) -> None:
    """Last resort when the driver itself fails.

    Moves whatever state the transfer is in towards a terminal one.  If it is
    already terminal there is nothing to do.
    """
    with session_scope() as db:
        tx = db.get(Transaction, transaction_id)
        if tx is None or tx.state not in IN_FLIGHT_STATES:
            return
        await transition(db, tx, TransactionState.REFUNDING, reason=reason)
        await _complete_refund(db, tx, debited=bool(tx.monoReference))


async def cancel_and_refund(db: Session, tx: Transaction, *, actor_id: str) -> Transaction:
    """FR 2.4 - the sender presses "Cancel and refund" on a stuck transfer.

    Only reachable once isStuck() is true, which the API enforces.  This is the
    <<extend>> relationship on the use case diagram: it hangs off the send flow
    rather than sitting inside it, because it only happens when something has
    gone wrong.
    """
    if tx.state not in IN_FLIGHT_STATES:
        raise TransferError(f"a transfer in {tx.state} cannot be cancelled")
    if not tx.isStuck():
        wait = int(settings.scaled(settings.stuck_cancel_seconds) - tx.secondsInState())
        raise TransferError(
            f"this transfer is still within its normal window; {wait}s until it can be cancelled"
        )

    await transition(
        db,
        tx,
        TransactionState.REFUNDING,
        actor=ActorType.USER,
        actor_id=actor_id,
        reason="Cancelled by sender after exceeding the pending threshold (FR 2.4)",
    )
    await _complete_refund(db, tx, debited=bool(tx.monoReference))
    return tx


# ---------------------------------------------------------------------------
# background sweeps
# ---------------------------------------------------------------------------


async def expire_quotes(db: Session) -> int:
    """Quoted -> Cancelled once the 60 second lock lapses (FR 2.1)."""
    now = datetime.now(UTC)
    stale = (
        db.execute(
            select(Transaction).where(
                Transaction.state == TransactionState.QUOTED,
                Transaction.quoteExpiresAt.is_not(None),
                Transaction.quoteExpiresAt < now,
            )
        )
        .scalars()
        .all()
    )
    for tx in stale:
        await transition(
            db, tx, TransactionState.CANCELLED, reason="Quote expired before confirmation (60s lock)"
        )
    return len(stale)


async def sweep_stuck(db: Session) -> int:
    """NFR 3 - auto-refund anything in flight past the 10 minute threshold.

    This is the guarantee the SRS says no other consumer product in Africa
    offers, so it runs on a timer rather than depending on the per-transfer
    driver still being alive.  If the process restarted mid-transfer, this sweep
    is what still returns the sender's money.
    """
    threshold = settings.scaled(settings.stuck_refund_seconds)
    refunded = 0

    candidates = (
        db.execute(select(Transaction).where(Transaction.state.in_(list(IN_FLIGHT_STATES))))
        .scalars()
        .all()
    )
    for tx in candidates:
        if tx.secondsInState() < threshold:
            continue
        await transition(
            db,
            tx,
            TransactionState.REFUNDING,
            reason=(
                f"Auto-refunded: exceeded the {settings.stuck_refund_seconds}s "
                "settlement guarantee (NFR 3)"
            ),
        )
        await _complete_refund(db, tx, debited=bool(tx.monoReference))
        refunded += 1

    return refunded


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _mark_intent(db: Session, tx: Transaction, status: IntentStatus) -> None:
    """Carry a terminal transaction state back to the API payment intent."""
    intent = db.execute(
        select(PaymentIntent).where(PaymentIntent.transactionId == tx.id)
    ).scalar_one_or_none()
    if intent:
        intent.status = status
        db.commit()


async def _fire_webhook(db: Session, tx: Transaction, event: str) -> None:
    """FR 4.3 - notify the partner that issued this transfer, if any."""
    intent = db.execute(
        select(PaymentIntent).where(PaymentIntent.transactionId == tx.id)
    ).scalar_one_or_none()
    if not intent:
        return

    from ..models import ApiKey
    from .webhooks import deliver

    api_key = db.get(ApiKey, intent.apiKeyId)
    if not api_key:
        return

    await deliver(
        db,
        partner_id=api_key.partnerId,
        event=event,
        payload={
            "id": intent.id,
            "object": "payment_intent",
            "status": str(intent.status),
            "reference": tx.reference,
            "partnerReference": intent.partnerReference,
            "sourceAmount": str(tx.sourceAmount),
            "sourceCurrency": tx.sourceCurrency,
            "destinationAmount": str(tx.destinationAmount),
            "destinationCurrency": tx.destinationCurrency,
            "recipient": {"name": tx.recipientName, "msisdn": tx.recipientMsisdn},
            "mpesaReceipt": tx.mpesaReceipt,
            "onchainTxHash": tx.onchainRecord.txHash if tx.onchainRecord else "",
            "failureReason": tx.failureReason,
        },
    )


def launch(transaction_id: str) -> None:
    """Start the driver as a fire-and-forget task, keeping a reference.

    asyncio only holds a weak reference to tasks, so a task with no strong
    reference anywhere can be garbage collected mid-await and silently stop a
    transfer.  _running exists solely to prevent that.
    """
    task = asyncio.create_task(drive(transaction_id))
    _running.add(task)
    task.add_done_callback(_running.discard)


_running: set[asyncio.Task] = set()


__all__ = [
    "TransferError",
    "authorize",
    "cancel_and_refund",
    "create_transfer",
    "drive",
    "expire_quotes",
    "launch",
    "quote_engine",
    "sweep_stuck",
    "transition",
]
