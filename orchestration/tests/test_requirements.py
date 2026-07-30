"""Requirement tests.

Each test names the requirement it holds the system to, so a failure reports
which part of the SRS broke rather than which function did.

These are not exhaustive unit tests. They cover the claims that would be
embarrassing to get wrong: the fee arithmetic, the state machine's refusal to
make illegal moves, the settlement guarantee, the mint gate, the audit chain,
and the idempotency of the institutional API.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cowrie.config import settings
from cowrie.enums import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    ActorType,
    DemoScenario,
    KycLevel,
    TransactionState,
)
from cowrie.models import Transaction
from cowrie.services import audit, transfer_service
from cowrie.services.quote_engine import engine as quote_engine

# ---------------------------------------------------------------------------
# FR 2.1 / NFR 6 - the quote
# ---------------------------------------------------------------------------


class TestQuoting:
    def test_fr21_quote_is_itemised_into_four_components(self):
        """NFR 6: every fee on its own line, never bundled."""
        quote = quote_engine.quote(source_amount=Decimal("100000"))
        fees = quote.fees

        assert fees.fxSpread > 0
        assert fees.networkGas > 0
        assert fees.liquiditySpread > 0
        assert fees.cowrieFee > 0
        assert fees.total() == (
            fees.fxSpread + fees.networkGas + fees.liquiditySpread + fees.cowrieFee
        )

    def test_fr21_quote_locks_for_sixty_seconds(self):
        quote = quote_engine.quote(source_amount=Decimal("50000"))
        assert 58 <= quote.secondsRemaining() <= 60
        assert not quote.isExpired()

    def test_hypothesis_all_in_cost_is_under_one_percent(self):
        """The SRS hypothesis: settlement "at a rate that is less than 1% in fees".

        Checked across the corridor's realistic range rather than at one amount,
        because a percentage claim that only holds at a convenient size is not a
        claim worth making. The fixed network gas dominates at tiny amounts, so
        the floor is where this is tightest.
        """
        for amount in ["10000", "50000", "100000", "500000", "2000000"]:
            quote = quote_engine.quote(source_amount=Decimal(amount))
            assert quote.costRatio() < Decimal("0.01"), (
                f"{amount} NGN costs {quote.costRatio() * 100:.3f}%, over the 1% target"
            )

    def test_recipient_amount_is_exactly_what_arrives(self):
        """FR 2.1: "the exact amount the recipient will receive"."""
        quote = quote_engine.quote(source_amount=Decimal("100000"))
        net = quote.source.amount - quote.fees.total()
        expected = (net / quote.midMarketRate).quantize(Decimal("0.01"))
        assert quote.destination.amount == expected

    def test_reverse_quote_round_trips(self):
        """A quote priced backwards from the payout lands on the same payout."""
        reverse = quote_engine.quote_for_destination(destination_amount=Decimal("8000"))
        assert abs(reverse.destination.amount - Decimal("8000")) <= Decimal("1.00")

    def test_zero_and_negative_amounts_are_refused(self):
        for bad in ["0", "-100"]:
            with pytest.raises(ValueError):
                quote_engine.quote(source_amount=Decimal(bad))

    def test_amount_below_network_cost_is_refused(self):
        """A transfer that cannot cover its own gas must not be quoted."""
        with pytest.raises(ValueError):
            quote_engine.quote(source_amount=Decimal("1"))


# ---------------------------------------------------------------------------
# The state machine diagram
# ---------------------------------------------------------------------------


class TestStateMachine:
    def test_every_state_on_the_diagram_exists(self):
        expected = {
            "CREATED", "QUOTED", "AUTHORIZED", "ONRAMP_PENDING", "BRIDGING",
            "OFFRAMP_PENDING", "SETTLED", "REFUNDING", "REFUNDED", "FAILED", "CANCELLED",
        }
        assert {str(s) for s in TransactionState} == expected

    def test_terminal_states_have_no_exits(self):
        for state in TERMINAL_STATES:
            assert ALLOWED_TRANSITIONS[state] == set(), f"{state} should be terminal"

    def test_nfr3_every_non_terminal_state_can_reach_a_terminal_one(self):
        """NFR 3: no transfer is left in the system.

        Proved as a reachability property over the transition table rather than
        by running transfers: if any state could not reach a terminal state, some
        transfer could be stranded there forever, and no amount of testing the
        happy path would reveal it.
        """
        for start in TransactionState:
            seen, frontier = {start}, [start]
            while frontier:
                current = frontier.pop()
                for nxt in ALLOWED_TRANSITIONS.get(current, set()):
                    if nxt not in seen:
                        seen.add(nxt)
                        frontier.append(nxt)
            assert seen & TERMINAL_STATES, f"{start} cannot reach any terminal state"

    def test_nfr3_every_in_flight_state_has_a_refund_path(self):
        """Money in flight must always have a way back to the sender."""
        for state in (
            TransactionState.ONRAMP_PENDING,
            TransactionState.BRIDGING,
            TransactionState.OFFRAMP_PENDING,
        ):
            assert TransactionState.REFUNDING in ALLOWED_TRANSITIONS[state], (
                f"{state} has no refund exit"
            )

    @pytest.mark.asyncio
    async def test_illegal_transition_is_refused(self, db, user):
        """The diagram is enforced, not merely documented."""
        quote = quote_engine.quote(source_amount=Decimal("50000"))
        tx = transfer_service.create_transfer(
            db, user=user, quote=quote, recipient_name="R", recipient_msisdn="+254700000000"
        )
        assert tx.state == TransactionState.QUOTED

        # QUOTED -> SETTLED is not an arrow on the diagram.
        with pytest.raises(transfer_service.TransferError, match="illegal transition"):
            await transfer_service.transition(db, tx, TransactionState.SETTLED)

    @pytest.mark.asyncio
    async def test_terminal_states_cannot_be_moved(self, db, user):
        quote = quote_engine.quote(source_amount=Decimal("50000"))
        tx = transfer_service.create_transfer(
            db, user=user, quote=quote, recipient_name="R", recipient_msisdn="+254700000000"
        )
        await transfer_service.transition(db, tx, TransactionState.CANCELLED)

        with pytest.raises(transfer_service.TransferError):
            await transfer_service.transition(db, tx, TransactionState.AUTHORIZED)


# ---------------------------------------------------------------------------
# FR 2.2 - authorisation
# ---------------------------------------------------------------------------


class TestAuthorisation:
    @pytest.mark.asyncio
    async def test_fr22_wrong_pin_is_rejected(self, db, user):
        quote = quote_engine.quote(source_amount=Decimal("50000"))
        tx = transfer_service.create_transfer(
            db, user=user, quote=quote, recipient_name="R", recipient_msisdn="+254700000000"
        )
        with pytest.raises(transfer_service.TransferError, match="Incorrect PIN"):
            await transfer_service.authorize(db, tx=tx, user=user, pin="999999")

        assert tx.state == TransactionState.QUOTED, "a bad PIN must not advance the transfer"

    @pytest.mark.asyncio
    async def test_fr13_sanctions_hit_blocks_the_transfer(self, db, user):
        """FR 1.3: a match stops the transfer at authorisation."""
        quote = quote_engine.quote(source_amount=Decimal("50000"))
        tx = transfer_service.create_transfer(
            db, user=user, quote=quote, recipient_name="R",
            recipient_msisdn="+254700000000", scenario=DemoScenario.SANCTIONS_HOLD,
        )
        with pytest.raises(transfer_service.TransferError, match="Sanctions hold"):
            await transfer_service.authorize(db, tx=tx, user=user, pin="123456")

        assert tx.state == TransactionState.FAILED

    @pytest.mark.asyncio
    async def test_fr12_transfer_above_the_tier_limit_is_refused(self, db, user):
        """FR 1.2: limits scale with verification level."""
        user.kycLevel = KycLevel.TIER1  # $200 ceiling
        db.commit()

        # 2,000,000 NGN is roughly $1,300 at the seeded rate.
        quote = quote_engine.quote(source_amount=Decimal("2000000"))
        tx = transfer_service.create_transfer(
            db, user=user, quote=quote, recipient_name="R", recipient_msisdn="+254700000000"
        )
        with pytest.raises(transfer_service.TransferError, match="limit"):
            await transfer_service.authorize(db, tx=tx, user=user, pin="123456")

        assert tx.state == TransactionState.FAILED

    @pytest.mark.asyncio
    async def test_expired_quote_cancels_rather_than_settling(self, db, user):
        from datetime import UTC, datetime, timedelta

        quote = quote_engine.quote(source_amount=Decimal("50000"))
        tx = transfer_service.create_transfer(
            db, user=user, quote=quote, recipient_name="R", recipient_msisdn="+254700000000"
        )
        tx.quoteExpiresAt = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

        with pytest.raises(transfer_service.TransferError, match="expired"):
            await transfer_service.authorize(db, tx=tx, user=user, pin="123456")

        assert tx.state == TransactionState.CANCELLED


# ---------------------------------------------------------------------------
# the corridor, end to end
# ---------------------------------------------------------------------------


class TestSettlement:
    @pytest.mark.asyncio
    async def test_happy_path_settles(self, db, user, chain):
        tx = await _drive(db, user, DemoScenario.HAPPY)

        assert tx.state == TransactionState.SETTLED
        assert tx.mpesaReceipt, "FR 2.3 requires the M-Pesa receipt to be recorded"
        assert tx.onchainRecord is not None
        assert tx.onchainRecord.isFinal()
        assert tx.onchainRecord.confirmations >= settings.required_confirmations

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "scenario,expected",
        [
            (DemoScenario.MONO_ERROR, TransactionState.FAILED),
            (DemoScenario.CHAIN_ROLLBACK, TransactionState.REFUNDED),
            (DemoScenario.PAYOUT_FAILED, TransactionState.REFUNDED),
            (DemoScenario.ONRAMP_TIMEOUT, TransactionState.REFUNDED),
        ],
    )
    async def test_nfr3_every_failure_reaches_a_terminal_state(
        self, db, user, chain, scenario, expected
    ):
        """NFR 3: a transfer either completes or refunds. Never neither."""
        tx = await _drive(db, user, scenario)

        assert tx.state == expected, f"{scenario} ended in {tx.state}"
        assert tx.state in TERMINAL_STATES
        assert tx.failureReason, "a non-settled transfer must say why"

    @pytest.mark.asyncio
    async def test_nfr3_refund_returns_the_money(self, db, user, chain):
        """A refund is not just a status change - the balance must come back."""
        before = user.ngnBalance
        tx = await _drive(db, user, DemoScenario.PAYOUT_FAILED)

        db.refresh(user)
        assert tx.state == TransactionState.REFUNDED
        assert user.ngnBalance == before, "the sender must be made whole"

    @pytest.mark.asyncio
    async def test_failed_debit_never_takes_money(self, db, user, chain):
        before = user.ngnBalance
        tx = await _drive(db, user, DemoScenario.MONO_ERROR)

        db.refresh(user)
        assert tx.state == TransactionState.FAILED
        assert user.ngnBalance == before

    @pytest.mark.asyncio
    async def test_fr33_settlement_waits_for_twelve_confirmations(self, db, user, chain):
        tx = await _drive(db, user, DemoScenario.HAPPY)
        assert tx.onchainRecord.confirmations >= 12


async def _drive(db, user, scenario: DemoScenario) -> Transaction:
    """Run one transfer to a terminal state."""
    quote = quote_engine.quote(source_amount=Decimal("50000"))
    tx = transfer_service.create_transfer(
        db, user=user, quote=quote, recipient_name="Mary Wanjiru",
        recipient_msisdn="+254712345678", scenario=scenario,
    )

    try:
        await transfer_service.authorize(db, tx=tx, user=user, pin="123456")
    except transfer_service.TransferError:
        db.refresh(tx)
        return tx

    await transfer_service.drive(tx.id)

    # The driver uses its own sessions, so this one must re-read.
    db.expire_all()
    return db.get(Transaction, tx.id)


# ---------------------------------------------------------------------------
# NFR 5 - the audit log
# ---------------------------------------------------------------------------


class TestAuditLog:
    def test_nfr5_chain_verifies_when_untouched(self, db, user):
        for i in range(5):
            audit.record(
                db, entity_type="User", entity_id=user.id, action=f"test.{i}",
                actor=ActorType.SYSTEM, after={"i": i},
            )
        db.commit()

        result = audit.verify_chain(db)
        assert result["valid"], result["reason"]
        assert result["entriesChecked"] == 5

    def test_nfr5_editing_an_entry_breaks_the_chain(self, db, user):
        for i in range(5):
            audit.record(
                db, entity_type="User", entity_id=user.id, action=f"test.{i}",
                actor=ActorType.SYSTEM, after={"i": i},
            )
        db.commit()

        from sqlalchemy import select

        from cowrie.models import AuditLogEntry

        entry = db.execute(select(AuditLogEntry).where(AuditLogEntry.seq == 3)).scalar_one()
        entry.action = "test.TAMPERED"
        db.commit()

        result = audit.verify_chain(db)
        assert not result["valid"]
        assert result["brokenAtSeq"] == 3, "verification should point at the edited row"

    def test_nfr5_deleting_an_entry_breaks_the_chain(self, db, user):
        for i in range(5):
            audit.record(
                db, entity_type="User", entity_id=user.id, action=f"test.{i}",
                actor=ActorType.SYSTEM, after={"i": i},
            )
        db.commit()

        from sqlalchemy import select

        from cowrie.models import AuditLogEntry

        entry = db.execute(select(AuditLogEntry).where(AuditLogEntry.seq == 2)).scalar_one()
        db.delete(entry)
        db.commit()

        assert not audit.verify_chain(db)["valid"]

    def test_nfr5_secrets_never_enter_the_log(self, db, user):
        """The log must not become a second copy of the credentials."""
        snapshot = audit.snapshot(user)
        for forbidden in ("pin_hash", "_pinHash", "key_hash", "id_number_encrypted"):
            assert forbidden not in snapshot

    @pytest.mark.asyncio
    async def test_nfr5_settlement_is_fully_audited(self, db, user, chain):
        tx = await _drive(db, user, DemoScenario.HAPPY)

        from sqlalchemy import select

        from cowrie.models import AuditLogEntry

        actions = [
            e.action
            for e in db.execute(
                select(AuditLogEntry)
                .where(AuditLogEntry.entityId == tx.id)
                .order_by(AuditLogEntry.seq)
            ).scalars().all()
        ]
        for expected in (
            "transaction.created", "transaction.quoted", "transaction.authorized",
            "transaction.onramp_pending", "transaction.bridging",
            "transaction.offramp_pending", "transaction.settled",
        ):
            assert expected in actions, f"{expected} missing from the audit trail"

        assert audit.verify_chain(db)["valid"]


# ---------------------------------------------------------------------------
# FR 3.2 - the mint gate
# ---------------------------------------------------------------------------


class TestReserve:
    @pytest.mark.asyncio
    async def test_fr32_mint_without_a_deposit_reference_is_refused(self, db, chain):
        from cowrie.services import reserve_service

        with pytest.raises(reserve_service.ReserveError, match="deposit reference"):
            await reserve_service.mint(
                db, amount=Decimal("1000"), usd_deposit_reference="", performed_by="test"
            )

    @pytest.mark.asyncio
    async def test_nfr2_mint_below_the_multisig_threshold_is_refused(self, db, chain):
        """NFR 2: treasury movement needs at least 3 of 5 signatures."""
        from cowrie.services import reserve_service

        with pytest.raises(reserve_service.ReserveError, match="signatures"):
            await reserve_service.mint(
                db, amount=Decimal("1000"), usd_deposit_reference="WIRE-1",
                performed_by="test", approvals=2,
            )

    @pytest.mark.asyncio
    async def test_fr32_mint_with_backing_succeeds(self, db, chain):
        from cowrie.services import reserve_service

        before = await chain.total_supply()
        movement = await reserve_service.mint(
            db, amount=Decimal("1000"), usd_deposit_reference="WIRE-OK",
            performed_by="test", approvals=3,
        )
        after = await chain.total_supply()

        assert movement.kind == "MINT"
        assert after == before + Decimal("1000")

    @pytest.mark.asyncio
    async def test_fr32_cannot_burn_more_than_supply(self, db, chain):
        from cowrie.services import reserve_service

        supply = await chain.total_supply()
        with pytest.raises(reserve_service.ReserveError, match="Cannot burn"):
            await reserve_service.burn(
                db, amount=supply + Decimal("1"), performed_by="test", approvals=3
            )


# ---------------------------------------------------------------------------
# FR 4 - the institutional API
# ---------------------------------------------------------------------------


class TestPartnerApi:
    def test_fr41_write_without_an_idempotency_key_is_refused(self, client, db):
        key = _api_key(db)
        response = client.post(
            "/v1/payment_intents",
            headers={"X-API-Key": key},
            json={
                "amount": "50000", "recipientName": "Mary Wanjiru",
                "recipientMsisdn": "+254712345678",
            },
        )
        assert response.status_code == 400
        assert "Idempotency-Key" in response.json()["detail"]

    def test_fr41_repeating_an_idempotency_key_does_not_duplicate(self, client, db):
        key = _api_key(db)
        body = {
            "amount": "50000", "recipientName": "Mary Wanjiru",
            "recipientMsisdn": "+254712345678",
        }
        headers = {"X-API-Key": key, "Idempotency-Key": "idem-fixed-001"}

        first = client.post("/v1/payment_intents", headers=headers, json=body)
        second = client.post("/v1/payment_intents", headers=headers, json=body)

        assert first.status_code == 201
        assert second.json()["id"] == first.json()["id"], "a repeat must return the original"

    def test_fr41_invalid_key_is_rejected(self, client):
        response = client.post(
            "/v1/payment_intents",
            headers={"X-API-Key": "ck_sandbox_deadbeef", "Idempotency-Key": "x"},
            json={"amount": "1000", "recipientName": "Ada Lovelace", "recipientMsisdn": "+254700000000"},
        )
        assert response.status_code == 401

    def test_unsupported_corridor_is_refused(self, client, db):
        key = _api_key(db)
        response = client.post(
            "/v1/payment_intents",
            headers={"X-API-Key": key, "Idempotency-Key": "corridor-1"},
            json={
                "amount": "50000", "sourceCurrency": "GHS", "destinationCurrency": "KES",
                "recipientName": "Ada Lovelace", "recipientMsisdn": "+254700000000",
            },
        )
        assert response.status_code == 400
        assert "corridor" in response.json()["detail"].lower()


def _api_key(db) -> str:
    from cowrie.models import ApiKey
    from cowrie.security import hash_secret

    plaintext = "ck_sandbox_" + "a" * 32
    key = ApiKey(
        partnerId="partner-test", scopes="payments:read payments:write",
        partnerName="Test Partner", prefix="ck_sandbox_aaaaaa", environment="sandbox",
    )
    key._keyHash = hash_secret(plaintext)
    db.add(key)
    db.commit()
    return plaintext


class TestNgnOffRamp:
    """SRS 1.4: the off-ramp is Daraja to M-Pesa *and* Mono payout to bank."""

    def _session(self, client) -> dict:
        start = client.post(
            "/auth/register/start",
            json={
                "fullName": "Ngn Withdrawer", "phone": "+2348077777777",
                "email": "withdraw@example.com", "country": "NG", "pin": "654321",
            },
        ).json()
        token = client.post(
            "/auth/register/verify",
            json={"challengeId": start["challengeId"], "code": start["code"]},
        ).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_withdrawal_requires_a_linked_account(self, client):
        auth = self._session(client)
        response = client.post("/kyc/withdraw", headers=auth, json={"amount": "1000"})
        assert response.status_code == 409

    def test_withdrawal_returns_ngn_to_the_bank(self, client):
        auth = self._session(client)
        client.post(
            "/kyc/link-account",
            headers=auth,
            json={"kind": "BANK", "institution": "GTB", "accountNumber": "0123454417"},
        )
        client.post("/kyc/top-up", headers=auth, json={"amount": "100000"})

        response = client.post("/kyc/withdraw", headers=auth, json={"amount": "40000"})
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["balance"] == "60000.000000"
        assert body["sessionId"], "a NIBSS session id is what the bank statement shows"
        assert body["destination"]["account"].endswith("4417")

    def test_a_top_up_appears_in_the_activity_feed(self, client):
        """Money arriving has to be visible.

        A top-up moved `ngnBalance` and wrote an audit entry, and the history
        screen reads transfers - so the balance changed with nothing on screen
        to explain it.
        """
        auth = self._session(client)
        client.post(
            "/kyc/link-account",
            headers=auth,
            json={"kind": "BANK", "institution": "Guaranty Trust Bank", "accountNumber": "0123454417"},
        )
        client.post("/kyc/top-up", headers=auth, json={"amount": "75000"})

        feed = client.get("/activity", headers=auth).json()["activity"]
        topups = [row for row in feed if row["type"] == "TOPUP"]

        assert len(topups) == 1, "the top-up should be in the feed"
        assert topups[0]["amount"] == "75000.000000"
        assert topups[0]["balanceAfter"] == "75000.000000"
        assert topups[0]["counterparty"]["institution"] == "Guaranty Trust Bank"

    def test_activity_interleaves_transfers_and_wallet_movements(self, client):
        """One chronological feed, not two disconnected lists."""
        auth = self._session(client)
        client.post(
            "/kyc/link-account",
            headers=auth,
            json={"kind": "BANK", "institution": "GTB", "accountNumber": "0123454417"},
        )
        client.post("/kyc/top-up", headers=auth, json={"amount": "200000"})
        client.post("/kyc/withdraw", headers=auth, json={"amount": "20000"})

        quote = client.post("/quotes", headers=auth, json={"amount": "50000"}).json()
        client.post(
            "/transfers",
            headers=auth,
            json={
                "quoteId": quote["id"], "recipientName": "Mary Wanjiru",
                "recipientMsisdn": "+254712345678",
            },
        )

        feed = client.get("/activity", headers=auth).json()["activity"]
        kinds = [row["type"] for row in feed]

        assert set(kinds) == {"TOPUP", "WITHDRAWAL", "TRANSFER"}
        # Newest first, so the transfer created last leads.
        assert kinds[0] == "TRANSFER"
        timestamps = [row["createdAt"] for row in feed]
        assert timestamps == sorted(timestamps, reverse=True), "the feed must be chronological"

    def test_cannot_withdraw_more_than_the_balance(self, client):
        auth = self._session(client)
        client.post(
            "/kyc/link-account",
            headers=auth,
            json={"kind": "BANK", "institution": "GTB", "accountNumber": "0123454417"},
        )
        client.post("/kyc/top-up", headers=auth, json={"amount": "5000"})

        response = client.post("/kyc/withdraw", headers=auth, json={"amount": "9000"})
        assert response.status_code == 402
        # The balance must be untouched by a refused withdrawal.
        assert client.get("/auth/me", headers=auth).json()["user"]["ngnBalance"] == "5000.000000"


class TestWebhookEvents:
    """FR 4.3 names four events. All four must be reachable from real code."""

    def test_fr43_every_subscribable_event_has_an_emitter(self):
        """A partner must not be able to subscribe to something that never fires.

        `webhooks.EVENTS` is the subscription allowlist, and its own docstring
        says it exists so that cannot happen. Two of the four named events were
        in the set with no caller anywhere, which broke exactly that promise.
        """
        import inspect

        from cowrie.routers import partner
        from cowrie.services import kyc_service, transfer_service, webhooks

        sources = "\n".join(
            inspect.getsource(m) for m in (transfer_service, kyc_service, webhooks, partner)
        )
        for event in webhooks.EVENTS:
            assert f'"{event}"' in sources, (
                f"{event} is subscribable but nothing in the codebase emits it"
            )

    def test_fr43_payout_completed_is_distinct_from_payment_settled(self):
        """They are different moments and both are required by name."""
        import inspect

        from cowrie.services import transfer_service

        source = inspect.getsource(transfer_service)
        assert '"payout.completed"' in source
        assert '"payment.settled"' in source

    def test_fr43_kyc_events_do_not_leak_between_partners(self, db, user):
        """A partner hears about a person only if it moved money for them."""
        from cowrie.services.webhooks import partners_for_user

        # A consumer who has never transacted through the API reaches nobody.
        assert partners_for_user(db, user.id) == set()

    def test_fr43_kyc_audience_is_the_partner_that_transacted(self, client, db):
        """The audience is derived from the partner's own payment intents."""
        from sqlalchemy import select

        from cowrie.models import ApiKey, PaymentIntent, Transaction
        from cowrie.services.webhooks import partners_for_user

        secret = _api_key(db)
        response = client.post(
            "/v1/payment_intents",
            headers={"X-API-Key": secret, "Idempotency-Key": "kyc-audience-1"},
            json={
                "amount": "50000", "recipientName": "Mary Wanjiru",
                "recipientMsisdn": "+254712345678",
            },
        )
        assert response.status_code == 201, response.text

        db.expire_all()
        intent = db.execute(
            select(PaymentIntent).where(PaymentIntent.idempotencyKey == "kyc-audience-1")
        ).scalar_one()
        tx = db.get(Transaction, intent.transactionId)
        key = db.get(ApiKey, intent.apiKeyId)

        assert partners_for_user(db, tx.senderId) == {key.partnerId}


# ---------------------------------------------------------------------------
# FR 1.1 - registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_fr11_no_account_exists_before_the_code_is_verified(self, client, db):
        from sqlalchemy import func, select

        from cowrie.models import User

        before = db.execute(select(func.count()).select_from(User)).scalar_one()

        response = client.post(
            "/auth/register/start",
            json={
                "fullName": "New Person", "phone": "+2348099999999",
                "email": "new@example.com", "country": "NG", "pin": "654321",
            },
        )
        assert response.status_code == 202

        db.expire_all()
        after = db.execute(select(func.count()).select_from(User)).scalar_one()
        assert after == before, "FR 1.1 requires verification before the account is created"

    def test_fr11_account_is_created_once_the_code_is_verified(self, client):
        start = client.post(
            "/auth/register/start",
            json={
                "fullName": "New Person", "phone": "+2348099999998",
                "email": "new2@example.com", "country": "NG", "pin": "654321",
            },
        ).json()

        response = client.post(
            "/auth/register/verify",
            json={"challengeId": start["challengeId"], "code": start["code"]},
        )
        assert response.status_code == 201
        assert response.json()["user"]["phone"] == "+2348099999998"

    def test_fr11_wrong_code_creates_nothing(self, client):
        start = client.post(
            "/auth/register/start",
            json={
                "fullName": "New Person", "phone": "+2348099999997",
                "email": "new3@example.com", "country": "NG", "pin": "654321",
            },
        ).json()

        response = client.post(
            "/auth/register/verify",
            json={"challengeId": start["challengeId"], "code": "000000"},
        )
        assert response.status_code == 400

    def test_a_single_use_code_cannot_be_replayed(self, client):
        start = client.post(
            "/auth/register/start",
            json={
                "fullName": "New Person", "phone": "+2348099999996",
                "email": "new4@example.com", "country": "NG", "pin": "654321",
            },
        ).json()

        payload = {"challengeId": start["challengeId"], "code": start["code"]}
        assert client.post("/auth/register/verify", json=payload).status_code == 201
        assert client.post("/auth/register/verify", json=payload).status_code == 400


# ---------------------------------------------------------------------------
# SRS 3.4 - rate limiting
# ---------------------------------------------------------------------------


class TestRateLimits:
    def test_unauthenticated_tier_is_ten_per_second(self, client):
        from cowrie.services.cache import cache

        cache._local.clear()

        statuses = [client.get("/corridor").status_code for _ in range(15)]
        assert 429 in statuses, "the 10/s unauthenticated limit should engage"
        assert statuses[0] == 200

    def test_health_is_never_rate_limited(self, client):
        """A health check that can be rate-limited takes the service down with it."""
        from cowrie.services.cache import cache

        cache._local.clear()
        statuses = [client.get("/health").status_code for _ in range(30)]
        assert all(s == 200 for s in statuses)


# ---------------------------------------------------------------------------
# NFR 7 / disclosure
# ---------------------------------------------------------------------------


class TestDisclosure:
    def test_transparency_states_the_build_is_a_prototype(self, client):
        body = client.get("/transparency").json()
        disclosure = body["disclosure"]

        assert "Prototype" in disclosure["buildType"]
        assert any("No real money" in s for s in disclosure["statements"])
        assert any("VASP" in s for s in disclosure["statements"])

    def test_state_machine_endpoint_matches_the_code(self, client):
        """The published transition table must be the one actually enforced."""
        body = client.get("/demo/state-machine").json()

        published = {t["from"]: set(t["to"]) for t in body["transitions"]}
        actual = {
            str(state): {str(t) for t in targets}
            for state, targets in ALLOWED_TRANSITIONS.items()
        }
        assert published == actual


# ---------------------------------------------------------------------------
# SRS 3.3 - key rotation
# ---------------------------------------------------------------------------


class TestKeyRotation:
    def test_keys_are_issued_with_a_ninety_day_life(self, client):
        """SRS 3.3: "API keys ... are rotated every 90 days"."""
        response = client.post(
            "/v1/partners",
            json={
                "organisation": "Rotation Ltd",
                "fullName": "Rota Tor",
                "email": "rota@example.com",
            },
        )
        assert response.status_code == 201

        from datetime import UTC, datetime

        expires = datetime.fromisoformat(response.json()["expiresAt"])
        days = (expires - datetime.now(UTC)).days
        assert 88 <= days <= 90, f"expected a ~90 day life, got {days}"

    def test_an_expired_key_is_refused(self, client, db):
        """An expired key must stop working, or the rotation is decorative."""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import select

        from cowrie.models import ApiKey

        created = client.post(
            "/v1/partners",
            json={
                "organisation": "Expiry Ltd",
                "fullName": "Ex Piry",
                "email": "ex@example.com",
            },
        ).json()
        secret = created["secretKey"]

        assert client.get("/v1/stats?days=1", headers={"X-API-Key": secret}).status_code == 200

        # Wind the clock past the ninety days.
        prefix = "_".join(secret.split("_")[:2]) + "_" + secret.split("_")[2][:6]
        for row in db.execute(select(ApiKey).where(ApiKey.prefix == prefix)).scalars().all():
            row.expiresAt = datetime.now(UTC) - timedelta(days=1)
        db.commit()

        response = client.get("/v1/stats?days=1", headers={"X-API-Key": secret})
        assert response.status_code == 401
        assert "expired" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# FR 5.3 - the signed regulator export
# ---------------------------------------------------------------------------


def _admin_token(client, db, role) -> str:
    """Create a console operator at `role` and sign in."""
    from cowrie.models import AdminUser
    from cowrie.security import hash_secret

    email = f"{str(role).lower()}@exports.example.com"
    operator = AdminUser(email=email, fullName=f"{role} Operator", role=role)
    operator._passwordHash = hash_secret("cowrie-demo")
    db.add(operator)
    db.commit()

    response = client.post(
        "/auth/admin/login", json={"email": email, "password": "cowrie-demo"}
    )
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _regulator_token(client, regulator: str = "SEC_NIGERIA") -> str:
    response = client.post(
        "/auth/regulator/register",
        json={
            "fullName": f"Auditor {regulator}",
            "email": f"{regulator.lower()}@regulators.example.com",
            "regulator": regulator,
            "password": "regulator-demo",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


def _generate_export(client, token: str) -> dict:
    response = client.post(
        "/regulator/exports?regulator=SEC_NIGERIA&days=30",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _signed_body(document: str) -> str:
    """The verification recipe from the guide, reimplemented independently.

    Deliberately not calling a helper from the router: a check that shares its
    implementation with the thing it checks proves only that the code agrees
    with itself. This is what a regulator would write.
    """
    return "".join(
        line for line in document.splitlines(keepends=True) if not line.startswith("#")
    )


def _header_field(document: str, label: str) -> str:
    for line in document.splitlines():
        if line.startswith(f"# {label}:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"'{label}' missing from the export header")


class TestRegulatorExport:
    def test_fr53_download_requires_a_session(self, client, db):
        """The pseudonymised register is not public.

        Every other regulator route refuses an anonymous caller; the download
        used to be the one that did not.
        """
        from cowrie.enums import AdminRole

        officer = _admin_token(client, db, AdminRole.OFFICER)
        export = _generate_export(client, officer)
        url = export["downloadUrl"]

        assert client.get(url).status_code == 401, "an anonymous caller must not read the register"

        # SRS 2.3 gives export sight to Regulators and to Officer-and-above.
        regulator = _regulator_token(client)
        assert client.get(url, headers={"Authorization": f"Bearer {regulator}"}).status_code == 200
        assert client.get(url, headers={"Authorization": f"Bearer {officer}"}).status_code == 200

    def test_fr53_a_regulator_cannot_read_another_jurisdictions_export(self, client, db, user):
        """One country's filing history is not another country's business.

        The export download was authenticated but never scoped, so a CMA_KENYA
        session could read a report addressed to the Nigeria SEC. Verified live
        before the fix: HTTP 200 and the full pseudonymised register.
        """
        from cowrie.enums import AdminRole

        _one_transaction(db, user)
        officer = _admin_token(client, db, AdminRole.OFFICER)
        export = _generate_export(client, officer)  # regulator=SEC_NIGERIA

        kenya = {"Authorization": f"Bearer {_regulator_token(client, 'CMA_KENYA')}"}

        # 404 rather than 403: a 403 would confirm the report exists.
        assert client.get(export["downloadUrl"], headers=kenya).status_code == 404
        assert client.get(export["verifyUrl"], headers=kenya).status_code == 404

        # And it must not be enumerable either.
        listed = client.get("/regulator/exports", headers=kenya).json()["exports"]
        assert all(row["id"] != export["id"] for row in listed)
        assert all(row["regulator"] == "CMA_KENYA" for row in listed)

    def test_fr53_the_addressed_regulator_can_read_its_own_export(self, client, db, user):
        """Scoping must not lock out the body the report is addressed to."""
        from cowrie.enums import AdminRole

        _one_transaction(db, user)
        officer = _admin_token(client, db, AdminRole.OFFICER)
        export = _generate_export(client, officer)

        sec = {"Authorization": f"Bearer {_regulator_token(client, 'SEC_NIGERIA')}"}
        assert client.get(export["downloadUrl"], headers=sec).status_code == 200
        assert client.get(export["verifyUrl"], headers=sec).json()["matches"] is True
        assert any(
            row["id"] == export["id"]
            for row in client.get("/regulator/exports", headers=sec).json()["exports"]
        )

    def test_fr53_an_officer_still_reads_any_export(self, client, db, user):
        """The admin who generates reports keeps sight of all of them (SRS 2.3)."""
        from cowrie.enums import AdminRole

        _one_transaction(db, user)
        officer = _admin_token(client, db, AdminRole.OFFICER)
        auth = {"Authorization": f"Bearer {officer}"}
        export = _generate_export(client, officer)

        assert client.get(export["downloadUrl"], headers=auth).status_code == 200
        assert any(
            row["id"] == export["id"]
            for row in client.get("/regulator/exports", headers=auth).json()["exports"]
        )

    def test_fr53_support_role_cannot_download_an_export(self, client, db):
        """RBAC is not bypassed by holding any admin token."""
        from cowrie.enums import AdminRole

        officer = _admin_token(client, db, AdminRole.OFFICER)
        export = _generate_export(client, officer)

        support = _admin_token(client, db, AdminRole.SUPPORT)
        response = client.get(
            export["downloadUrl"], headers={"Authorization": f"Bearer {support}"}
        )
        assert response.status_code == 403

    def test_fr53_signature_covers_the_delivered_csv_body(self, client, db, user):
        """The hash in the header must be reproducible from the file itself.

        Previously the hash was taken over a JSON view of the rows while the
        download rendered CSV, so this comparison could never succeed and the
        verification instruction in the guide was impossible to follow.
        """
        import hashlib

        from cowrie.enums import AdminRole

        # A settled transfer, so the report has real rows rather than a header.
        _one_transaction(db, user)

        officer = _admin_token(client, db, AdminRole.OFFICER)
        export = _generate_export(client, officer)
        auth = {"Authorization": f"Bearer {officer}"}

        document = client.get(export["downloadUrl"], headers=auth).text
        body = _signed_body(document)
        recomputed = hashlib.sha256(body.encode()).hexdigest()

        assert recomputed == _header_field(document, "Content SHA-256")
        assert recomputed == export["contentHash"]
        assert body.strip(), "the report should carry rows, not just a header block"

    def test_fr53_an_empty_period_is_still_a_signed_report(self, client, db):
        """A report covering no transactions is signed, not "unverifiable".

        `sha256("")` is a real answer to a real question - the regulator asked
        what happened in a period and the answer is "nothing". Treating the
        empty body as "no body was stored" would label a correct report as
        unverifiable, which is the opposite of the point.
        """
        from cowrie.enums import AdminRole

        officer = _admin_token(client, db, AdminRole.OFFICER)
        export = _generate_export(client, officer)
        auth = {"Authorization": f"Bearer {officer}"}

        assert export["rowCount"] == 0

        verdict = client.get(export["verifyUrl"], headers=auth).json()
        assert verdict["signatureAssurance"] == "demo-signed"
        assert verdict["matches"] is True
        assert verdict["signatureValid"] is True

    def test_fr53_verify_endpoint_agrees_with_the_document(self, client, db, user):
        _one_transaction(db, user)

        from cowrie.enums import AdminRole

        officer = _admin_token(client, db, AdminRole.OFFICER)
        export = _generate_export(client, officer)
        auth = {"Authorization": f"Bearer {officer}"}

        verdict = client.get(export["verifyUrl"], headers=auth).json()
        assert verdict["matches"] is True
        assert verdict["signatureValid"] is True
        assert verdict["recomputedHash"] == export["contentHash"]

    @pytest.mark.asyncio
    async def test_fr53_a_signed_report_does_not_change_afterwards(self, client, db, user, chain):
        """The body is frozen at signing time.

        A transfer inside the reporting period keeps moving after the report is
        signed. If the rows were re-derived on download, the same export would
        render a different document later - same period, same signature,
        different contents.
        """
        from cowrie.enums import AdminRole, TransactionState

        quote = quote_engine.quote(source_amount=Decimal("50000"))
        tx = transfer_service.create_transfer(
            db, user=user, quote=quote, recipient_name="Mary Wanjiru",
            recipient_msisdn="+254712345678",
        )
        await transfer_service.authorize(db, tx=tx, user=user, pin="123456")
        transaction_id = tx.id

        officer = _admin_token(client, db, AdminRole.OFFICER)
        auth = {"Authorization": f"Bearer {officer}"}
        export = _generate_export(client, officer)
        before = client.get(export["downloadUrl"], headers=auth).text
        assert "AUTHORIZED" in before

        # Carry the same transfer to a terminal state.
        await transfer_service.drive(transaction_id)
        db.expire_all()
        assert db.get(Transaction, transaction_id).state == TransactionState.SETTLED

        after = client.get(export["downloadUrl"], headers=auth).text
        assert after == before, "a signed report must not change after it was signed"
        assert client.get(export["verifyUrl"], headers=auth).json()["matches"] is True


def _one_transaction(db, user) -> Transaction:
    """A transaction inside the reporting period, so an export has a row.

    The report covers every transaction in the window whatever its state, so
    this does not need to settle - and staying synchronous keeps it usable from
    the non-async tests.
    """
    quote = quote_engine.quote(source_amount=Decimal("50000"))
    return transfer_service.create_transfer(
        db, user=user, quote=quote, recipient_name="Mary Wanjiru",
        recipient_msisdn="+254712345678",
    )


# ---------------------------------------------------------------------------
# Disclosure: the demo must not advertise credentials that do not work
# ---------------------------------------------------------------------------


class TestDemoCredentials:
    def test_demo_config_advertises_only_working_credentials(self, client, db):
        """A credential printed by the running system must authenticate.

        The seeder was emptied and the advertised sign-ins were left behind, so
        two of the three published logins failed against a fresh database. This
        holds the endpoint to the rule that made them wrong: anything it marks
        `provisioned` has to actually work.
        """
        from cowrie.seed import provision

        provision()

        access = client.get("/demo/config").json()["access"]
        surfaces = {k: v for k, v in access.items() if isinstance(v, dict)}
        assert surfaces, "the endpoint should describe how to reach each surface"

        for name, entry in surfaces.items():
            if not entry.get("provisioned"):
                # A surface with no seeded account must say how to get one
                # rather than naming a login that does not exist.
                assert entry.get("howTo"), f"{name} is not provisioned and offers no route in"
                assert "pin" not in entry and "password" not in entry, (
                    f"{name} is not provisioned but publishes a credential"
                )
                continue

            assert name == "admin", f"unexpected provisioned surface: {name}"
            response = client.post(
                "/auth/admin/login",
                json={"email": entry["email"], "password": entry["password"]},
            )
            assert response.status_code == 200, (
                f"/demo/config advertises {entry['email']}, which does not authenticate"
            )


# ---------------------------------------------------------------------------
# Input hardening - a client mistake must never read as a server failure
# ---------------------------------------------------------------------------


#: Every spelling of a value that Decimal accepts but a ledger cannot hold.
#: `Decimal("NaN")` parses without raising and only throws on comparison, which
#: is why these reached a 500 rather than a 4xx.
NON_FINITE = ["NaN", "nan", "-NaN", "sNaN", "Infinity", "-Infinity", "1e999"]


class TestInputHardening:
    def _consumer(self, client) -> dict:
        start = client.post(
            "/auth/register/start",
            json={
                "fullName": "Edge Case", "phone": "+2348055500001",
                "email": "edge@example.com", "country": "NG", "pin": "123456",
            },
        ).json()
        token = client.post(
            "/auth/register/verify",
            json={"challengeId": start["challengeId"], "code": start["code"]},
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        client.post(
            "/kyc/link-account",
            headers=auth,
            json={"kind": "BANK", "institution": "GTB", "accountNumber": "0123454417"},
        )
        client.post("/kyc/top-up", headers=auth, json={"amount": "100000"})
        return auth

    @pytest.mark.parametrize("amount", NON_FINITE)
    def test_non_finite_amounts_never_cause_a_server_error(self, client, db, amount):
        """NaN and the infinities are refused on every endpoint that takes money."""
        from cowrie.enums import AdminRole

        auth = self._consumer(client)
        engineer = {"Authorization": f"Bearer {_admin_token(client, db, AdminRole.ENGINEER)}"}
        key = _api_key(db)

        cases = [
            ("/quotes", auth, {"amount": amount}),
            ("/kyc/top-up", auth, {"amount": amount}),
            ("/kyc/withdraw", auth, {"amount": amount}),
            ("/admin/reserve/mint", engineer, {"amount": amount, "usdDepositReference": "W-1"}),
            ("/admin/reserve/burn", engineer, {"amount": amount}),
        ]
        for path, headers, body in cases:
            response = client.post(path, headers=headers, json=body)
            assert 400 <= response.status_code < 500, (
                f"{path} answered {response.status_code} for amount={amount!r}; "
                "a malformed amount is the caller's mistake, not a server failure"
            )

        # Partner surface takes its amount the same way.
        response = client.post(
            "/v1/payment_intents",
            headers={"X-API-Key": key, "Idempotency-Key": f"nonfinite-{amount}"},
            json={
                "amount": amount, "recipientName": "Mary Wanjiru",
                "recipientMsisdn": "+254712345678",
            },
        )
        assert 400 <= response.status_code < 500

        # And as a query parameter.
        assert 400 <= client.get(f"/v1/quotes?amount={amount}", headers={"X-API-Key": key}).status_code < 500

    def test_a_leaked_exception_class_is_not_an_error_message(self, client, db):
        """`{"detail":"[<class 'decimal.InvalidOperation'>]"}` is not a message."""
        key = _api_key(db)
        body = client.get("/v1/quotes?amount=NaN", headers={"X-API-Key": key}).text
        assert "InvalidOperation" not in body
        assert "class" not in body

    def test_negative_paging_is_refused(self, client, db, user):
        """A negative LIMIT reached Postgres and answered 500."""
        from cowrie.enums import AdminRole

        auth = self._consumer(client)
        admin = {"Authorization": f"Bearer {_admin_token(client, db, AdminRole.ADMIN)}"}
        key = {"X-API-Key": _api_key(db)}

        for path, headers in [
            ("/transfers?limit=-1", auth),
            ("/activity?limit=-1", auth),
            ("/admin/transactions?limit=-1", admin),
            ("/admin/audit?limit=-5", admin),
            ("/admin/sanctions?limit=-1", admin),
            ("/v1/payment_intents?limit=-1", key),
            ("/v1/webhooks/deliveries?limit=-1", key),
        ]:
            response = client.get(path, headers=headers)
            assert response.status_code == 422, (
                f"{path} answered {response.status_code}, expected 422"
            )

    def test_a_negative_window_is_refused(self, client, db):
        """A negative `days` silently inverted the period instead of failing."""
        from cowrie.enums import AdminRole

        officer = {"Authorization": f"Bearer {_admin_token(client, db, AdminRole.OFFICER)}"}
        assert client.post(
            "/regulator/exports?regulator=SEC_NIGERIA&days=-30", headers=officer
        ).status_code == 422
        assert client.get(
            "/v1/stats?days=-1", headers={"X-API-Key": _api_key(db)}
        ).status_code == 422

    def test_a_null_byte_in_a_query_parameter_is_refused(self, client, db):
        """Postgres cannot store NUL, so it must not reach the driver."""
        from cowrie.enums import AdminRole

        admin = {"Authorization": f"Bearer {_admin_token(client, db, AdminRole.ADMIN)}"}
        response = client.get("/admin/audit?entityType=%00", headers=admin)
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request"

    def test_an_error_response_carries_the_json_envelope(self, client):
        """The 400 shape matches what the rest of the API returns."""
        response = client.get("/corridor?x=%00")
        assert response.status_code == 400
        assert "error" in response.json()
        assert {"type", "message"} <= set(response.json()["error"])


class TestCache:
    def test_rate_limiting_survives_a_missing_cache(self, client):
        """SRS 3.3 names Redis, but its absence must degrade rather than break."""
        from cowrie.services.cache import cache

        assert cache.backend in {"redis", "in-process"}
        assert client.get("/health").status_code == 200
