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
            json={"challengeId": start["challengeId"], "code": start["demoCode"]},
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

        payload = {"challengeId": start["challengeId"], "code": start["demoCode"]}
        assert client.post("/auth/register/verify", json=payload).status_code == 201
        assert client.post("/auth/register/verify", json=payload).status_code == 400


# ---------------------------------------------------------------------------
# SRS 3.4 - rate limiting
# ---------------------------------------------------------------------------


class TestRateLimits:
    def test_unauthenticated_tier_is_ten_per_second(self, client):
        from cowrie.middleware.ratelimit import window

        window._hits.clear()

        statuses = [client.get("/corridor").status_code for _ in range(15)]
        assert 429 in statuses, "the 10/s unauthenticated limit should engage"
        assert statuses[0] == 200

    def test_health_is_never_rate_limited(self, client):
        """A health check that can be rate-limited takes the service down with it."""
        from cowrie.middleware.ratelimit import window

        window._hits.clear()
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
