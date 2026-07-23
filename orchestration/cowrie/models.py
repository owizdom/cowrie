"""Persistence model.

Every class in docs/uml/cowrie_class.puml appears here under the same name with
the same fields, the same visibility and the same relationships:

    AuditableEntity   abstract base carrying id + createdAt
    User              *-- KycSubmission        (composition, "files")
    User              o-- Transaction          (aggregation, "initiates")
    ApiKey            o-- PaymentIntent        (aggregation, "issues")
    PaymentIntent     --> Transaction 0..1     (association, "produces")
    Transaction       *-- OnchainRecord 0..1   (composition, "anchored by")
    Transaction       *-- Money x2             (composition, source/destination)
    Transaction       *-- FeeBreakdown         (composition, "itemizes")
    AuditLogEntry     ..> AuditableEntity      (dependency, "records")

Private members on the diagram (-idNumberEncrypted, -keyHash, -secretHash,
-beforeHash, -afterHash, -prevLogHash) are prefixed with a single underscore
and are never returned by any response schema.

Money and FeeBreakdown are «value object» on the diagram: they have no identity,
so rather than becoming tables they are inlined as columns on Transaction and
rehydrated by the value-object accessors at the bottom of the Transaction class.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .enums import (
    ActorType,
    AdminRole,
    DisputeStatus,
    IntentStatus,
    KycIdType,
    KycLevel,
    KycStatus,
    RiskLevel,
    TransactionState,
    WebhookStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_uuid() -> str:
    return str(uuid.uuid4())


#: Money amounts are stored as NUMERIC(24, 6).  Never floats - this is a
#: payments system and 6 decimal places covers cUSDC's precision.
MONEY = Numeric(24, 6)


class UtcDateTime(TypeDecorator):
    """A timestamp that is always timezone-aware UTC on the way out.

    PostgreSQL round-trips `TIMESTAMP WITH TIME ZONE` faithfully; SQLite has no
    timezone type and hands back a naive datetime.  Without this, the same
    comparison - `datetime.now(UTC) >= tx.quoteExpiresAt` - works on Postgres
    and raises TypeError on SQLite, which is exactly the kind of bug that only
    appears in the environment you did not test in.

    Normalising at the type layer fixes it once, rather than at each of the
    dozen call sites that compare a stored timestamp with the current time.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class EnumString(TypeDecorator):
    """Store a StrEnum as text, and return it as the enum rather than as text.

    The alternative, a native database ENUM, would make adding a state a schema
    migration - and TransactionState is the one thing in this system most likely
    to gain a value.  Text keeps that cheap.

    Without the coercion on the way out, `user.kycLevel` is a plain `str`, so
    `.value` raises and `isinstance(x, KycLevel)` is False, while `==` still
    works because StrEnum subclasses str.  That combination produces bugs that
    pass every equality check and fail on the one attribute access.
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_cls, length: int | None = None) -> None:
        self._enum = enum_cls
        super().__init__(length or max(len(member.value) for member in enum_cls) + 4)

    def process_bind_param(self, value, dialect) -> str | None:
        if value is None:
            return None
        return value.value if isinstance(value, self._enum) else str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return self._enum(value)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# «value object» classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Money:
    """«value object» Money  {+amount: Decimal, +currency: Char(3)}

    Frozen because a value object has no identity and must not be mutated in
    place; two Money instances with equal fields are the same value.
    """

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if len(self.currency) != 3:
            raise ValueError("currency must be an ISO 4217 alpha-3 code (SRS 1.2)")

    def as_dict(self) -> dict:
        return {"amount": str(self.amount), "currency": self.currency}


@dataclass(frozen=True, slots=True)
class FeeBreakdown:
    """«value object» FeeBreakdown - the four itemised charges of NFR 6.

    NFR 6 requires that "the interface never bundles fees into a single total",
    so each component is carried separately all the way to the UI and total()
    is derived rather than stored.
    """

    fxSpread: Decimal
    networkGas: Decimal
    liquiditySpread: Decimal
    cowrieFee: Decimal
    currency: str = "NGN"

    def total(self) -> Decimal:
        """+total() : Decimal"""
        return self.fxSpread + self.networkGas + self.liquiditySpread + self.cowrieFee

    def as_dict(self) -> dict:
        return {
            "fxSpread": str(self.fxSpread),
            "networkGas": str(self.networkGas),
            "liquiditySpread": str(self.liquiditySpread),
            "cowrieFee": str(self.cowrieFee),
            "total": str(self.total()),
            "currency": self.currency,
        }


# ---------------------------------------------------------------------------
# abstract class AuditableEntity
# ---------------------------------------------------------------------------


class AuditableEntity(Base):
    """abstract class AuditableEntity {+id: UUID, +createdAt: Timestamp}

    Mapped as a SQLAlchemy abstract base, which is the faithful translation:
    the diagram's hollow triangles are generalization, and no table exists for
    the parent itself.  AuditLogEntry.entityType names the concrete subclass.
    """

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    createdAt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)

    @property
    def entity_type(self) -> str:
        return type(self).__name__


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------


class User(AuditableEntity):
    """AuditableEntity <|-- User"""

    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    country: Mapped[str] = mapped_column(String(2))
    kycLevel: Mapped[KycLevel] = mapped_column(EnumString(KycLevel), default=KycLevel.NONE)

    # -- supporting fields, not on the diagram --------------------------------
    fullName: Mapped[str] = mapped_column(String(160), default="")
    _pinHash: Mapped[str] = mapped_column("pin_hash", String(255), default="")
    ngnBalance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    """Demo ledger. In production this is the balance at the sender's bank,
    read through Mono; here it is seeded so the app has something to spend."""
    bankName: Mapped[str] = mapped_column(String(80), default="")
    bankAccountMasked: Mapped[str] = mapped_column(String(32), default="")
    sanctionsClearedAt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    isFrozen: Mapped[bool] = mapped_column(Boolean, default=False)

    kycSubmissions: Mapped[list[KycSubmission]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",  # composition: parts die with the whole
    )
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="sender",
        # aggregation: no cascade delete, a Transaction outlives its User
    )

    # -- operations from the diagram -----------------------------------------
    def raiseLimit(self, level: KycLevel) -> None:
        """+raiseLimit() : void  - FR 1.2, limits scale with verification."""
        order = [KycLevel.NONE, KycLevel.TIER1, KycLevel.TIER2, KycLevel.TIER3]
        if order.index(level) > order.index(self.kycLevel):
            self.kycLevel = level

    def limitUsd(self) -> float:
        from .config import settings

        return settings.tier_limits_usd[str(self.kycLevel)]


# ---------------------------------------------------------------------------
# KycSubmission
# ---------------------------------------------------------------------------


class KycSubmission(AuditableEntity):
    """AuditableEntity <|-- KycSubmission,  User "1" *-- "0..*" KycSubmission"""

    __tablename__ = "kyc_submissions"

    userId: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40), default="Smile ID")
    status: Mapped[KycStatus] = mapped_column(EnumString(KycStatus), default=KycStatus.PENDING, index=True)
    idType: Mapped[KycIdType] = mapped_column(EnumString(KycIdType))
    _idNumberEncrypted: Mapped[bytes] = mapped_column("id_number_encrypted", LargeBinary, default=b"")
    """-idNumberEncrypted : Bytea.  Private on the diagram and never serialised;
    the API only ever exposes the last four characters."""
    decidedAt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    # -- supporting fields ----------------------------------------------------
    confidenceScore: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    """Smile ID liveness/match confidence, shown in the admin review queue."""
    livenessPassed: Mapped[bool] = mapped_column(Boolean, default=False)
    requestedLevel: Mapped[KycLevel] = mapped_column(EnumString(KycLevel), default=KycLevel.TIER1)
    decidedBy: Mapped[str] = mapped_column(String(120), default="")
    rejectionReason: Mapped[str] = mapped_column(Text, default="")

    user: Mapped[User] = relationship(back_populates="kycSubmissions")

    def approve(self, by: str) -> None:
        """+approve() : void"""
        self.status = KycStatus.APPROVED
        self.decidedAt = utcnow()
        self.decidedBy = by

    def reject(self, by: str, reason: str) -> None:
        """+reject() : void"""
        self.status = KycStatus.REJECTED
        self.decidedAt = utcnow()
        self.decidedBy = by
        self.rejectionReason = reason

    def freeze(self, by: str, reason: str) -> None:
        """+freeze() : void"""
        self.status = KycStatus.FROZEN
        self.decidedAt = utcnow()
        self.decidedBy = by
        self.rejectionReason = reason


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------


class Transaction(AuditableEntity):
    """AuditableEntity <|-- Transaction

    Carries three composed value objects (source Money, destination Money,
    FeeBreakdown) as inlined columns, plus a composed OnchainRecord as a real
    row because it has its own identity on the chain.
    """

    __tablename__ = "transactions"

    fxRate: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    state: Mapped[TransactionState] = mapped_column(
        EnumString(TransactionState), default=TransactionState.CREATED, index=True
    )
    settledAt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    # -- *-- Money "source" ---------------------------------------------------
    sourceAmount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    sourceCurrency: Mapped[str] = mapped_column(String(3), default="NGN")

    # -- *-- Money "destination" ----------------------------------------------
    destinationAmount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    destinationCurrency: Mapped[str] = mapped_column(String(3), default="KES")

    # -- *-- FeeBreakdown -----------------------------------------------------
    feeFxSpread: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    feeNetworkGas: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    feeLiquiditySpread: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    feeCowrie: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))

    # -- o-- User "initiates" -------------------------------------------------
    senderId: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), index=True)

    # -- supporting fields ----------------------------------------------------
    reference: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    """Human-facing reference, e.g. CWR-8F3K2M."""
    recipientName: Mapped[str] = mapped_column(String(160), default="")
    recipientMsisdn: Mapped[str] = mapped_column(String(24), default="")
    """Kenyan mobile-money number - the M-Pesa wallet credited by Daraja."""
    quoteExpiresAt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    channel: Mapped[str] = mapped_column(String(16), default="COWRIEPAY")
    """COWRIEPAY | API - which surface created it."""
    monoReference: Mapped[str] = mapped_column(String(64), default="")
    mpesaReceipt: Mapped[str] = mapped_column(String(64), default="")
    failureReason: Mapped[str] = mapped_column(Text, default="")
    riskLevel: Mapped[RiskLevel] = mapped_column(EnumString(RiskLevel), default=RiskLevel.LOW)
    riskFlags: Mapped[list] = mapped_column(JSON, default=list)
    stateEnteredAt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    demoScenario: Mapped[str] = mapped_column(String(24), default="HAPPY")

    sender: Mapped[User | None] = relationship(back_populates="transactions")
    onchainRecord: Mapped[OnchainRecord | None] = relationship(
        back_populates="transaction",
        cascade="all, delete-orphan",  # composition
        uselist=False,
    )
    paymentIntent: Mapped[PaymentIntent | None] = relationship(back_populates="transaction")

    # -- value object accessors ----------------------------------------------
    @property
    def source(self) -> Money:
        return Money(self.sourceAmount, self.sourceCurrency)

    @property
    def destination(self) -> Money:
        return Money(self.destinationAmount, self.destinationCurrency)

    @property
    def fees(self) -> FeeBreakdown:
        return FeeBreakdown(
            fxSpread=self.feeFxSpread,
            networkGas=self.feeNetworkGas,
            liquiditySpread=self.feeLiquiditySpread,
            cowrieFee=self.feeCowrie,
            currency=self.sourceCurrency,
        )

    # -- operations from the diagram -----------------------------------------
    def isStuck(self) -> bool:
        """+isStuck() : bool - FR 2.4.

        True once an in-flight transfer has been pending long enough that the
        sender is entitled to the "Cancel and refund" button.
        """
        from .config import settings
        from .enums import IN_FLIGHT_STATES

        if self.state not in IN_FLIGHT_STATES:
            return False
        age = (utcnow() - self.stateEnteredAt).total_seconds()
        return age >= settings.scaled(settings.stuck_cancel_seconds)

    def secondsInState(self) -> float:
        return (utcnow() - self.stateEnteredAt).total_seconds()

    def totalCostRatio(self) -> Decimal:
        """All-in cost as a fraction of principal - the sub-1% claim of NFR/SRS."""
        if not self.sourceAmount:
            return Decimal("0")
        return self.fees.total() / self.sourceAmount


# ---------------------------------------------------------------------------
# OnchainRecord
# ---------------------------------------------------------------------------


class OnchainRecord(AuditableEntity):
    """Transaction "1" *-- "0..1" OnchainRecord : anchored by

    Not a subclass of AuditableEntity on the diagram, but it inherits id and
    createdAt here for a uniform primary key; it is never itself audited, only
    the Transaction that owns it is.
    """

    __tablename__ = "onchain_records"

    transactionId: Mapped[str] = mapped_column(String(36), ForeignKey("transactions.id"), index=True)
    txHash: Mapped[str] = mapped_column(String(66), index=True)
    blockNumber: Mapped[int] = mapped_column(Integer, default=0)
    confirmations: Mapped[int] = mapped_column(Integer, default=0)
    contractAddress: Mapped[str] = mapped_column(String(42), default="")

    # -- supporting fields ----------------------------------------------------
    chain: Mapped[str] = mapped_column(String(24), default="base")
    chainMode: Mapped[str] = mapped_column(String(16), default="simulated")
    """'simulated' or 'anvil'.  Recorded on the row so the UI can be honest
    about which one produced this hash."""
    gasUsedUsd: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=Decimal("0"))
    rolledBack: Mapped[bool] = mapped_column(Boolean, default=False)
    cngnAmount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    cusdcAmount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))

    transaction: Mapped[Transaction] = relationship(back_populates="onchainRecord")

    def isFinal(self) -> bool:
        """+isFinal() : bool - FR 3.3, at least 12 confirmations on Base."""
        from .config import settings

        return (not self.rolledBack) and self.confirmations >= settings.required_confirmations


# ---------------------------------------------------------------------------
# ApiKey
# ---------------------------------------------------------------------------


class ApiKey(AuditableEntity):
    """AuditableEntity <|-- ApiKey.  FR 4.1."""

    __tablename__ = "api_keys"

    partnerId: Mapped[str] = mapped_column(String(36), index=True)
    _keyHash: Mapped[str] = mapped_column("key_hash", String(255))
    """-keyHash : Bytea.  The plaintext key is shown exactly once, at creation,
    and never stored."""
    scopes: Mapped[str] = mapped_column(String(255), default="payments:read payments:write")
    revokedAt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)

    # -- supporting fields ----------------------------------------------------
    partnerName: Mapped[str] = mapped_column(String(160), default="")
    contactName: Mapped[str] = mapped_column(String(160), default="")
    """Who at the partner owns this integration.  Shown in the portal header and
    used to know who to contact when a key starts failing."""
    contactEmail: Mapped[str] = mapped_column(String(255), default="")
    label: Mapped[str] = mapped_column(String(80), default="")
    prefix: Mapped[str] = mapped_column(String(24), index=True, default="")
    """Non-secret identifying prefix, e.g. ck_sandbox_a1b2c3 - lets the portal
    list keys without ever holding the secret."""
    environment: Mapped[str] = mapped_column(String(16), default="sandbox")
    lastUsedAt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    requestCount: Mapped[int] = mapped_column(Integer, default=0)

    paymentIntents: Mapped[list[PaymentIntent]] = relationship(
        back_populates="apiKey",  # aggregation: no cascade
    )

    def isActive(self) -> bool:
        return self.revokedAt is None

    def revoke(self) -> None:
        """+revoke() : void"""
        self.revokedAt = utcnow()

    def hasScope(self, scope: str) -> bool:
        return scope in self.scopes.split()


# ---------------------------------------------------------------------------
# PaymentIntent
# ---------------------------------------------------------------------------


class PaymentIntent(AuditableEntity):
    """AuditableEntity <|-- PaymentIntent.  FR 4.2.

    ApiKey "1" o-- "0..*" PaymentIntent : issues
    PaymentIntent "1" --> "0..1" Transaction : produces
    """

    __tablename__ = "payment_intents"

    idempotencyKey: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    """FR 4.1 - "Each write request must include a unique ID to prevent
    duplicates"."""
    status: Mapped[IntentStatus] = mapped_column(
        EnumString(IntentStatus), default=IntentStatus.CREATED, index=True
    )

    apiKeyId: Mapped[str] = mapped_column(String(36), ForeignKey("api_keys.id"), index=True)
    transactionId: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("transactions.id"), default=None
    )

    # -- supporting fields: the FR 4.2 request body ---------------------------
    sourceCurrency: Mapped[str] = mapped_column(String(3), default="NGN")
    destinationCurrency: Mapped[str] = mapped_column(String(3), default="KES")
    amount: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    recipientName: Mapped[str] = mapped_column(String(160), default="")
    recipientMsisdn: Mapped[str] = mapped_column(String(24), default="")
    partnerReference: Mapped[str] = mapped_column(String(120), default="")
    """"a reference of their choice" - FR 4.2."""

    apiKey: Mapped[ApiKey] = relationship(back_populates="paymentIntents")
    transaction: Mapped[Transaction | None] = relationship(back_populates="paymentIntent")


# ---------------------------------------------------------------------------
# CusdcReserve
# ---------------------------------------------------------------------------


class CusdcReserve(AuditableEntity):
    """AuditableEntity <|-- CusdcReserve.  FR 3.2 / FR 5.3.

    One row per attestation: the banking partner's USD balance against the
    circulating cUSDC supply on the date an outside attestor signed for it.
    """

    __tablename__ = "cusdc_reserves"

    attestationDate: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    usdBalance: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    cusdcSupply: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    attestor: Mapped[str] = mapped_column(String(160), default="")

    # -- supporting fields ----------------------------------------------------
    bankingPartner: Mapped[str] = mapped_column(String(160), default="")
    reportUrl: Mapped[str] = mapped_column(String(255), default="")
    anchorTxHash: Mapped[str] = mapped_column(String(66), default="")
    """NFR 5 - the attestation's hash anchored on-chain."""
    isPublished: Mapped[bool] = mapped_column(Boolean, default=True)

    def coverageRatio(self) -> Decimal:
        """+coverageRatio() : Decimal"""
        if not self.cusdcSupply:
            return Decimal("0")
        return (self.usdBalance / self.cusdcSupply).quantize(Decimal("0.000001"))

    def isFullyBacked(self) -> bool:
        """+isFullyBacked() : bool - FR 3.2 rejects unbacked issuance."""
        return self.usdBalance >= self.cusdcSupply


class ReserveMovement(Base):
    """Mint and burn ledger behind FR 3.2.

    Not on the class diagram.  CusdcReserve models the periodic attestation
    snapshot; this models the individual mint/burn events the admin console
    performs, which the diagram implies through the "Mint cUSDC" and
    "Burn cUSDC" use cases but does not give a class.
    """

    __tablename__ = "reserve_movements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    createdAt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    kind: Mapped[str] = mapped_column(String(8))  # MINT | BURN
    amount: Mapped[Decimal] = mapped_column(MONEY)
    usdDepositReference: Mapped[str] = mapped_column(String(120), default="")
    """FR 3.2 - a mint is refused unless the banking partner confirms a matching
    USD deposit, and this is that confirmation's reference."""
    txHash: Mapped[str] = mapped_column(String(66), default="")
    performedBy: Mapped[str] = mapped_column(String(120), default="")
    approvals: Mapped[int] = mapped_column(Integer, default=0)
    """NFR 2 - treasury movement needs >= 3 of 5 signatures."""
    supplyAfter: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


class Webhook(AuditableEntity):
    """AuditableEntity <|-- Webhook.  FR 4.3."""

    __tablename__ = "webhooks"

    partnerId: Mapped[str] = mapped_column(String(36), index=True)
    url: Mapped[str] = mapped_column(String(500))
    _secretHash: Mapped[str] = mapped_column("secret_hash", String(255), default="")
    status: Mapped[WebhookStatus] = mapped_column(EnumString(WebhookStatus), default=WebhookStatus.ACTIVE)

    # -- supporting fields ----------------------------------------------------
    events: Mapped[list] = mapped_column(JSON, default=list)
    signingSecretPrefix: Mapped[str] = mapped_column(String(24), default="")
    environment: Mapped[str] = mapped_column(String(16), default="sandbox")


class WebhookDelivery(Base):
    """One attempt to deliver one event to one endpoint.

    FR 4.3 requires retry "for up to 24 hours if delivery fails", so attempts
    are rows rather than a counter.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    createdAt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    webhookId: Mapped[str] = mapped_column(String(36), ForeignKey("webhooks.id"), index=True)
    event: Mapped[str] = mapped_column(String(60), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    signature: Mapped[str] = mapped_column(String(255), default="")
    """FR 4.3 "signed event notifications" - HMAC-SHA256 over
    '{timestamp}.{body}', the scheme the developer portal documents."""
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    responseStatus: Mapped[int] = mapped_column(Integer, default=0)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    nextRetryAt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)
    givenUp: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# AuditLogEntry
# ---------------------------------------------------------------------------


class AuditLogEntry(Base):
    """«log» AuditLogEntry ..> AuditableEntity : records

    Deliberately not an AuditableEntity itself - a log that audited itself
    would recurse.  Append-only: there is no update or delete path anywhere in
    the codebase, and each row carries the hash of the row before it, so any
    tampering breaks the chain and verifyChain() reports the break.  This is
    NFR 5.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    seq: Mapped[int] = mapped_column(Integer, autoincrement=True, unique=True, index=True)
    entityType: Mapped[str] = mapped_column(String(40), index=True)
    entityId: Mapped[str] = mapped_column(String(36), index=True)
    actor: Mapped[ActorType] = mapped_column(EnumString(ActorType), index=True)
    actorId: Mapped[str] = mapped_column(String(120), default="")
    action: Mapped[str] = mapped_column(String(80), index=True)
    _beforeHash: Mapped[str] = mapped_column("before_hash", String(64), default="")
    _afterHash: Mapped[str] = mapped_column("after_hash", String(64), default="")
    _prevLogHash: Mapped[str] = mapped_column("prev_log_hash", String(64), default="")
    ts: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)

    # -- supporting fields ----------------------------------------------------
    entryHash: Mapped[str] = mapped_column(String(64), default="", index=True)
    """This row's own hash, i.e. the next row's prevLogHash."""
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    anchorTxHash: Mapped[str] = mapped_column(String(66), default="")
    """NFR 5 - "anchored on-chain".  Set when a batch is anchored."""


# ---------------------------------------------------------------------------
# Supporting entities (not on the class diagram)
# ---------------------------------------------------------------------------


class AdminUser(Base):
    """Operator of the admin console.  RBAC roles come from SRS 2.3."""

    __tablename__ = "admin_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    createdAt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    fullName: Mapped[str] = mapped_column(String(160))
    role: Mapped[AdminRole] = mapped_column(EnumString(AdminRole), default=AdminRole.SUPPORT)
    _passwordHash: Mapped[str] = mapped_column("password_hash", String(255), default="")


class RegulatorUser(Base):
    """A named person at a regulator (SRS 2.3, "Regulators").

    Their access is read-only and that is enforced structurally: no write route
    accepts the `regulator` token audience, so there is no privilege here to
    escalate. Accounts carry which body the person represents, because an
    export generated for the SEC should be attributable to a person at the SEC.
    """

    __tablename__ = "regulator_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    createdAt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    fullName: Mapped[str] = mapped_column(String(160))
    regulator: Mapped[str] = mapped_column(String(24), index=True)
    """SEC_NIGERIA | CMA_KENYA | CBN"""
    _passwordHash: Mapped[str] = mapped_column("password_hash", String(255), default="")
    lastSeenAt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)


class SanctionsEntry(Base):
    """Local OFAC / UN / EU consolidated list used by FR 1.3.

    Seeded with a small set of fictional names so the screening step can be
    demonstrated failing as well as passing.  No real sanctions list is shipped.
    """

    __tablename__ = "sanctions_list"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    listName: Mapped[str] = mapped_column(String(16), index=True)  # OFAC | UN | EU
    fullName: Mapped[str] = mapped_column(String(200), index=True)
    country: Mapped[str] = mapped_column(String(2), default="")
    reason: Mapped[str] = mapped_column(String(200), default="")


class SanctionsScreening(Base):
    """Result of one screening run.  FR 1.3 requires screening at signup and a
    daily refresh, so results are rows with a timestamp rather than a flag."""

    __tablename__ = "sanctions_screenings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    createdAt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    userId: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    transactionId: Mapped[str | None] = mapped_column(String(36), default=None)
    trigger: Mapped[str] = mapped_column(String(24), default="SIGNUP")  # SIGNUP | DAILY | TRANSFER
    passed: Mapped[bool] = mapped_column(Boolean, default=True)
    listsChecked: Mapped[list] = mapped_column(JSON, default=list)
    matchedName: Mapped[str] = mapped_column(String(200), default="")
    matchScore: Mapped[float] = mapped_column(Numeric(5, 2), default=0)


class Dispute(Base):
    """FR 5.2 - disputes appear in a review queue alongside KYC."""

    __tablename__ = "disputes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    createdAt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    userId: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    transactionId: Mapped[str | None] = mapped_column(String(36), ForeignKey("transactions.id"))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[DisputeStatus] = mapped_column(
        EnumString(DisputeStatus), default=DisputeStatus.OPEN, index=True
    )
    resolution: Mapped[str] = mapped_column(Text, default="")
    resolvedBy: Mapped[str] = mapped_column(String(120), default="")
    resolvedAt: Mapped[datetime | None] = mapped_column(UtcDateTime, default=None)


class RegulatorExport(Base):
    """FR 5.3 - a signed transaction report generated for SEC / CMA."""

    __tablename__ = "regulator_exports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    createdAt: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, index=True)
    regulator: Mapped[str] = mapped_column(String(24))  # SEC_NIGERIA | CMA_KENYA | CBN
    periodStart: Mapped[datetime] = mapped_column(UtcDateTime)
    periodEnd: Mapped[datetime] = mapped_column(UtcDateTime)
    rowCount: Mapped[int] = mapped_column(Integer, default=0)
    totalVolumeUsd: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    contentHash: Mapped[str] = mapped_column(String(64), default="")
    signature: Mapped[str] = mapped_column(String(255), default="")
    generatedBy: Mapped[str] = mapped_column(String(120), default="")
