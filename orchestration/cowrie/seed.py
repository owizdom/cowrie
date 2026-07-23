"""Seeded demonstration data.

SRS §2.5 constraint 2: "cUSDC's behaviour ... is simulated with seeded demo data
across CowriePay, Cowrie API and the Admin Dashboard."  This module is that
seed.

Everything here is invented. The people do not exist, the sanctions entries are
fictional, and the transaction history is generated. What it is designed to do
is make every screen in the product show something worth looking at on first
load - an empty admin console demonstrates nothing.

Design of the seed
------------------
The history is generated backwards from now across 14 days, with a realistic
mix of outcomes: mostly settled, some refunded, a few failed, a couple flagged
for review. Timestamps are spread so the 24-hour figures on the admin overview
are non-trivial, and the settlement latencies are drawn around the ~26 second
mark the real state machine produces, so the NFR 1 numbers on the dashboard are
consistent with what a live transfer actually does.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from .config import settings
from .db import session_scope
from .enums import (
    ActorType,
    AdminRole,
    DisputeStatus,
    KycIdType,
    KycLevel,
    KycStatus,
    RiskLevel,
    TransactionState,
    WebhookStatus,
)
from .models import (
    AdminUser,
    ApiKey,
    CusdcReserve,
    Dispute,
    KycSubmission,
    OnchainRecord,
    ReserveMovement,
    SanctionsEntry,
    SanctionsScreening,
    Transaction,
    User,
    Webhook,
)
from .security import encrypt_id_number, generate_api_key, generate_webhook_secret, hash_secret
from .services import audit
from .services.quote_engine import engine as quote_engine

#: Fixed so every run of the demo produces the same history and the same
#: numbers appear in the video and in the README.
SEED = 20260628
DEMO_PIN = "123456"
DEMO_ADMIN_PASSWORD = "cowrie-demo"


# ---------------------------------------------------------------------------
# people
# ---------------------------------------------------------------------------

SENDERS = [
    # (name, phone, email, country, kyc level, NGN balance)
    ("Emmanuel Adeyemi", "+2348012345678", "emmanuel@cowrie.demo", "NG", KycLevel.TIER3, "2450000.00"),
    ("Chiamaka Okonkwo", "+2348023456789", "chiamaka@cowrie.demo", "NG", KycLevel.TIER2, "890000.00"),
    ("Tunde Bakare", "+2348034567890", "tunde@cowrie.demo", "NG", KycLevel.TIER2, "1250000.00"),
    ("Ngozi Eze", "+2348045678901", "ngozi@cowrie.demo", "NG", KycLevel.TIER1, "310000.00"),
    ("Yusuf Bello", "+2348056789012", "yusuf@cowrie.demo", "NG", KycLevel.TIER2, "670000.00"),
    ("Folake Adeniyi", "+2348067890123", "folake@cowrie.demo", "NG", KycLevel.TIER3, "3100000.00"),
    ("Ibrahim Sani", "+2348078901234", "ibrahim@cowrie.demo", "NG", KycLevel.TIER1, "145000.00"),
    ("Adaeze Nwosu", "+2348089012345", "adaeze@cowrie.demo", "NG", KycLevel.TIER2, "980000.00"),
]

RECIPIENTS = [
    ("Mary Wanjiru", "+254712345678"),
    ("Samuel Kiprop", "+254723456789"),
    ("Grace Achieng", "+254734567890"),
    ("Peter Mwangi", "+254745678901"),
    ("Faith Njeri", "+254756789012"),
    ("Daniel Otieno", "+254767890123"),
    ("Esther Chebet", "+254778901234"),
]

ADMINS = [
    ("Amara Obi", "amara@cowrie.demo", AdminRole.ADMIN),
    ("Kwame Mensah", "kwame@cowrie.demo", AdminRole.OFFICER),
    ("Zainab Musa", "zainab@cowrie.demo", AdminRole.REVIEWER),
    ("David Kimani", "david@cowrie.demo", AdminRole.ENGINEER),
    ("Blessing Eze", "blessing@cowrie.demo", AdminRole.SUPPORT),
]

#: Fictional. No real sanctions list is shipped - see services/sanctions.py.
SANCTIONS = [
    ("OFAC", "Ibrahim Al-Rashid Kone", "ML", "Fictional entry for demonstration"),
    ("OFAC", "Viktor Semenov Petrov", "RU", "Fictional entry for demonstration"),
    ("UN", "Hassan Abdi Warsame", "SO", "Fictional entry for demonstration"),
    ("UN", "Mohammed Tahir Bakr", "SD", "Fictional entry for demonstration"),
    ("EU", "Dmitri Sokolov Ivanov", "BY", "Fictional entry for demonstration"),
    ("EU", "Andrei Kuznetsov Mikhail", "RU", "Fictional entry for demonstration"),
]


def _already_seeded() -> bool:
    with session_scope() as db:
        return db.execute(select(func.count()).select_from(User)).scalar_one() > 0


def seed_if_empty() -> None:
    if _already_seeded():
        return
    seed()


def seed() -> None:  # noqa: PLR0915 - a seed is inherently a long linear script
    random.seed(SEED)
    now = datetime.now(UTC)

    with session_scope() as db:
        # ---- sanctions list ------------------------------------------------
        for list_name, full_name, country, reason in SANCTIONS:
            db.add(
                SanctionsEntry(
                    listName=list_name, fullName=full_name, country=country, reason=reason
                )
            )

        # ---- admins --------------------------------------------------------
        for full_name, email, role in ADMINS:
            admin = AdminUser(email=email, fullName=full_name, role=role)
            admin._passwordHash = hash_secret(DEMO_ADMIN_PASSWORD)
            db.add(admin)

        # ---- senders -------------------------------------------------------
        users: list[User] = []
        for name, phone, email, country, level, balance in SENDERS:
            user = User(
                fullName=name,
                phone=phone,
                email=email,
                country=country,
                kycLevel=level,
                ngnBalance=Decimal(balance),
                bankName=random.choice(
                    ["Guaranty Trust Bank", "Access Bank", "Zenith Bank", "First Bank of Nigeria"]
                ),
                bankAccountMasked=f"******{random.randint(1000, 9999)}",
                createdAt=now - timedelta(days=random.randint(20, 180)),
                sanctionsClearedAt=now - timedelta(hours=random.randint(1, 20)),
            )
            user._pinHash = hash_secret(DEMO_PIN)
            db.add(user)
            users.append(user)

            db.flush()
            db.add(
                SanctionsScreening(
                    userId=user.id,
                    trigger="SIGNUP",
                    passed=True,
                    listsChecked=["OFAC", "UN", "EU"],
                    createdAt=user.createdAt,
                )
            )

        db.flush()

        # ---- KYC submissions: a mix, so the review queue is not empty ------
        _seed_kyc(db, users, now)

        # ---- transaction history -------------------------------------------
        _seed_transactions(db, users, now)

        # ---- API partner, key and webhook ----------------------------------
        _seed_partner(db)

        # ---- cUSDC reserve history -----------------------------------------
        _seed_reserve(db, now)

        # ---- disputes -------------------------------------------------------
        _seed_disputes(db, users, now)

        db.commit()

    print(
        f"[seed] {len(SENDERS)} senders, {len(ADMINS)} admins, "
        f"{len(SANCTIONS)} sanctions entries, transaction history seeded"
    )
    print(f"[seed] CowriePay login: {SENDERS[0][1]} / PIN {DEMO_PIN}")
    print(f"[seed] Admin login: {ADMINS[0][1]} / {DEMO_ADMIN_PASSWORD}")


def _seed_kyc(db, users: list[User], now: datetime) -> None:
    """Three approved, two pending for the queue, one rejected."""
    plan = [
        (users[0], KycIdType.BVN, KycStatus.APPROVED, 97.4, KycLevel.TIER3),
        (users[1], KycIdType.NIN, KycStatus.APPROVED, 94.1, KycLevel.TIER2),
        (users[2], KycIdType.NIN, KycStatus.APPROVED, 95.8, KycLevel.TIER2),
        (users[3], KycIdType.NIN, KycStatus.PENDING, 88.2, KycLevel.TIER2),
        (users[6], KycIdType.KENYAN_ID, KycStatus.PENDING, 79.6, KycLevel.TIER2),
        (users[7], KycIdType.GHANA_CARD, KycStatus.REJECTED, 61.3, KycLevel.TIER2),
    ]

    for user, id_type, status, confidence, requested in plan:
        submission = KycSubmission(
            userId=user.id,
            provider="Smile ID",
            status=status,
            idType=id_type,
            confidenceScore=confidence,
            livenessPassed=status != KycStatus.REJECTED,
            requestedLevel=requested,
            createdAt=now - timedelta(hours=random.randint(2, 72)),
        )
        submission._idNumberEncrypted = encrypt_id_number(str(random.randint(10**10, 10**11 - 1)))

        if status == KycStatus.APPROVED:
            submission.decidedAt = submission.createdAt + timedelta(minutes=random.randint(2, 40))
            submission.decidedBy = "Smile ID (auto)"
        elif status == KycStatus.REJECTED:
            submission.decidedAt = submission.createdAt + timedelta(minutes=random.randint(5, 60))
            submission.decidedBy = "zainab@cowrie.demo"
            submission.rejectionReason = "Document image too blurred to match against the selfie"

        db.add(submission)

    db.flush()


def _seed_transactions(db, users: list[User], now: datetime) -> None:
    """Two weeks of history, weighted towards success.

    The weighting is deliberate: a settlement rate around 93% with the
    remainder refunded rather than lost is what NFR 3 describes, and a demo
    where everything succeeded would not show the refund machinery working.
    """
    outcomes = (
        [TransactionState.SETTLED] * 42
        + [TransactionState.REFUNDED] * 4
        + [TransactionState.FAILED] * 2
        + [TransactionState.CANCELLED] * 1
    )

    failure_reasons = {
        TransactionState.REFUNDED: [
            "Daraja B2C failed: recipient wallet limit exceeded (simulated)",
            "Base reorganisation rolled the bridge transaction back (FR 3.3)",
            "On-ramp did not settle within the 10 minute SLA (NFR 3)",
            "Auto-refunded: exceeded the 600s settlement guarantee (NFR 3)",
        ],
        TransactionState.FAILED: [
            "Sanctions hold: name matches a listed entity (FR 1.3)",
            "Mono debit declined: insufficient funds at issuing bank (simulated)",
        ],
        TransactionState.CANCELLED: ["Quote expired before confirmation (60s lock)"],
    }

    for index, state in enumerate(outcomes):
        user = random.choice(users)
        recipient_name, recipient_msisdn = random.choice(RECIPIENTS)

        # Amounts skewed small, as consumer remittances are, with a few large.
        amount = Decimal(
            random.choice(
                [25_000, 40_000, 50_000, 75_000, 100_000, 120_000, 150_000, 200_000, 350_000, 500_000]
            )
        )
        quote = quote_engine.quote(source_amount=amount)

        created = now - timedelta(
            days=random.randint(0, 13),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )

        tx = Transaction(
            reference=f"CWR-{random.randint(0x100000, 0xFFFFFF):06X}",
            senderId=user.id,
            state=state,
            fxRate=quote.fxRate,
            sourceAmount=quote.source.amount,
            sourceCurrency="NGN",
            destinationAmount=quote.destination.amount,
            destinationCurrency="KES",
            feeFxSpread=quote.fees.fxSpread,
            feeNetworkGas=quote.fees.networkGas,
            feeLiquiditySpread=quote.fees.liquiditySpread,
            feeCowrie=quote.fees.cowrieFee,
            recipientName=recipient_name,
            recipientMsisdn=recipient_msisdn,
            channel="API" if index % 7 == 0 else "COWRIEPAY",
            createdAt=created,
            stateEnteredAt=created,
            quoteExpiresAt=created + timedelta(seconds=settings.quote_lock_seconds),
        )

        # Latency around the ~26s the live state machine actually produces.
        if state == TransactionState.SETTLED:
            elapsed = random.gauss(26.5, 3.2)
            elapsed = max(21.0, min(elapsed, 58.0))
            tx.settledAt = created + timedelta(seconds=elapsed)
            tx.stateEnteredAt = tx.settledAt
            tx.mpesaReceipt = "".join(
                random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(10)
            )
        else:
            tx.failureReason = random.choice(failure_reasons[state])
            tx.stateEnteredAt = created + timedelta(seconds=random.randint(30, 600))

        # A few flagged for the analyst queue.
        usd = amount / Decimal(str(settings.mid_market_ngn_per_usd))
        if usd >= 200:
            tx.riskLevel = RiskLevel.MEDIUM
            tx.riskFlags = [f"Large transfer: ${usd:,.0f}"]
        if usd >= 300:
            tx.riskLevel = RiskLevel.HIGH
            tx.riskFlags = [f"Large transfer: ${usd:,.0f}", "First transfer to this recipient"]

        db.add(tx)
        db.flush()

        # On-chain record for anything that reached the bridge.
        if state in {TransactionState.SETTLED, TransactionState.REFUNDED}:
            rolled_back = "reorganisation" in tx.failureReason
            db.add(
                OnchainRecord(
                    transactionId=tx.id,
                    txHash="0x" + "".join(random.choice("0123456789abcdef") for _ in range(64)),
                    blockNumber=21_400_000 + index * 13,
                    confirmations=0 if rolled_back else settings.required_confirmations,
                    contractAddress=settings.bridge_address,
                    chainMode="simulated",
                    gasUsedUsd=Decimal(str(settings.network_gas_usd)),
                    rolledBack=rolled_back,
                    cngnAmount=quote.source.amount,
                    cusdcAmount=quote.usdEquivalent,
                    createdAt=created,
                )
            )

        audit.record(
            db,
            entity_type="Transaction",
            entity_id=tx.id,
            action=f"transaction.{str(state).lower()}",
            actor=ActorType.SYSTEM,
            actor_id="seed",
            after=audit.snapshot(tx),
            detail={"seeded": True},
        )

    db.flush()


def _seed_partner(db) -> None:
    """One institutional partner with a usable key and a webhook endpoint.

    The key is fixed rather than random so the README, the developer portal and
    the video all show the same value and it can be copied into a curl command
    that works.
    """
    partner_id = "11111111-2222-3333-4444-555555555555"

    plaintext = "ck_sandbox_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6"
    prefix = "ck_sandbox_a1b2c3"

    key = ApiKey(
        partnerId=partner_id,
        scopes="payments:read payments:write",
        partnerName="Adumi Payments Ltd",
        label="Sandbox key",
        prefix=prefix,
        environment="sandbox",
    )
    key._keyHash = hash_secret(plaintext)
    db.add(key)

    # A second key, revoked, so the portal shows both states.
    revoked_plain, revoked_prefix = generate_api_key("sandbox")
    revoked = ApiKey(
        partnerId=partner_id,
        scopes="payments:read",
        partnerName="Adumi Payments Ltd",
        label="Rotated out",
        prefix=revoked_prefix,
        environment="sandbox",
        revokedAt=datetime.now(UTC) - timedelta(days=6),
    )
    revoked._keyHash = hash_secret(revoked_plain)
    db.add(revoked)

    secret, secret_prefix = generate_webhook_secret()
    endpoint = Webhook(
        partnerId=partner_id,
        url="https://api.adumipay.demo/webhooks/cowrie",
        status=WebhookStatus.ACTIVE,
        events=["payment.settled", "payment.failed", "payout.completed"],
        signingSecretPrefix=secret_prefix,
        environment="sandbox",
    )
    endpoint._secretHash = secret
    db.add(endpoint)
    db.flush()

    print(f"[seed] Cowrie API sandbox key: {plaintext}")


def _seed_reserve(db, now: datetime) -> None:
    """Twelve months of attestations, and the mint/burn ledger behind them."""
    supply = Decimal("8200000.000000")

    for months_ago in range(11, -1, -1):
        date = now - timedelta(days=months_ago * 30)
        supply += Decimal(random.randint(180_000, 520_000))
        # Reserve always meets or exceeds supply - an attestation showing
        # otherwise would be a solvency event, not a data point.
        usd = supply + Decimal(random.randint(1_000, 90_000))

        db.add(
            CusdcReserve(
                attestationDate=date,
                usdBalance=usd,
                cusdcSupply=supply,
                attestor="Adeyemi & Partners LLP (simulated attestor)",
                bankingPartner="Access Bank (Trust Account, simulated)",
                reportUrl=f"https://transparency.cowrie.demo/attestations/{date:%Y-%m}.pdf",
                anchorTxHash="0x" + "".join(random.choice("0123456789abcdef") for _ in range(64)),
                createdAt=date,
            )
        )

    movements = [
        ("MINT", "450000.00", "WIRE-IN-8823A1", 4),
        ("MINT", "1200000.00", "WIRE-IN-9041B7", 5),
        ("BURN", "220000.00", "WIRE-OUT-3312C9", 3),
        ("MINT", "800000.00", "WIRE-IN-7756D2", 3),
        ("BURN", "150000.00", "WIRE-OUT-1188E4", 4),
    ]
    running = supply
    for days_ago, (kind, amount, reference, approvals) in enumerate(movements):
        value = Decimal(amount)
        running = running + value if kind == "MINT" else running - value
        db.add(
            ReserveMovement(
                kind=kind,
                amount=value,
                usdDepositReference=reference,
                txHash="0x" + "".join(random.choice("0123456789abcdef") for _ in range(64)),
                performedBy="david@cowrie.demo",
                approvals=approvals,
                supplyAfter=running,
                createdAt=now - timedelta(days=(len(movements) - days_ago) * 4),
            )
        )

    db.flush()


def _seed_disputes(db, users: list[User], now: datetime) -> None:
    settled = (
        db.execute(
            select(Transaction).where(Transaction.state == TransactionState.REFUNDED).limit(2)
        )
        .scalars()
        .all()
    )

    entries = [
        (
            users[3],
            "Recipient says the money never arrived",
            "The app says settled and gave me a receipt number but my sister has not seen it in "
            "her M-Pesa. It has been two hours. Reference is in the transfer.",
            DisputeStatus.OPEN,
            settled[0].id if settled else None,
        ),
        (
            users[5],
            "Charged twice for the same transfer",
            "I tapped confirm once but I can see two debits on my bank statement for the same "
            "amount within a minute of each other.",
            DisputeStatus.ESCALATED,
            None,
        ),
        (
            users[1],
            "Wrong exchange rate applied",
            "The quote screen showed one rate and the receipt shows a different one. The "
            "difference is small but I want to understand it.",
            DisputeStatus.RESOLVED,
            None,
        ),
    ]

    for user, subject, body, status, transaction_id in entries:
        dispute = Dispute(
            userId=user.id,
            transactionId=transaction_id,
            subject=subject,
            body=body,
            status=status,
            createdAt=now - timedelta(hours=random.randint(3, 90)),
        )
        if status == DisputeStatus.RESOLVED:
            dispute.resolution = (
                "The quote was locked at request time and honoured; the receipt shows the "
                "effective rate after the itemised fees. Explained to the customer with the "
                "fee breakdown from the confirmation screen."
            )
            dispute.resolvedBy = "kwame@cowrie.demo"
            dispute.resolvedAt = dispute.createdAt + timedelta(hours=6)
        db.add(dispute)

    db.flush()


if __name__ == "__main__":
    from .db import init_db

    init_db()
    seed()
