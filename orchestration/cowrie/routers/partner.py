"""Cowrie API - the institutional surface (FR 4).

Mounted at /v1 and versioned from the start, because the SRS promises banks and
fintechs a stable integration and an unversioned payments API cannot be changed
without breaking them.

FR 4.1  API key authentication with an idempotency key on every write
FR 4.2  Payment intent creation
FR 4.3  Signed webhooks (services/webhooks.py)
        + "Analyze transaction stats" from the use case diagram

Idempotency (FR 4.1)
--------------------
"Each write request must include a unique ID to prevent duplicates."  The header
is `Idempotency-Key` and it is mandatory, not optional.  A repeat of the same
key returns the original result rather than creating a second payment - the
uniqueness is enforced by a database constraint on PaymentIntent.idempotencyKey,
so two concurrent identical requests cannot both succeed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_session
from ..enums import ActorType, DemoScenario, IntentStatus, TransactionState, WebhookStatus
from ..models import ApiKey, PaymentIntent, Transaction, User, Webhook
from ..security import generate_key_pair, generate_webhook_secret, hash_secret
from ..services import audit, transfer_service, webhooks
from ..services.quote_engine import engine as quote_engine
from .deps import require_scope

router = APIRouter(prefix="/v1", tags=["cowrie-api"])

#: SRS 3.3 - keys and webhook signing secrets are rotated every 90 days.
KEY_LIFETIME_DAYS = 90


# ---------------------------------------------------------------------------
# schemas
# ---------------------------------------------------------------------------


class PaymentIntentRequest(BaseModel):
    """FR 4.2 - source currency, destination currency, amount, recipient, and a
    reference of the partner's choice."""

    sourceCurrency: str = Field(default="NGN", min_length=3, max_length=3)
    destinationCurrency: str = Field(default="KES", min_length=3, max_length=3)
    amount: str = Field(description="Amount in the source currency, as a decimal string")
    recipientName: str = Field(min_length=2, max_length=160)
    recipientMsisdn: str = Field(min_length=9, max_length=24)
    reference: str = Field(default="", max_length=120, description="Your own reference")
    scenario: DemoScenario = DemoScenario.HAPPY

    @field_validator("sourceCurrency", "destinationCurrency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("amount")
    @classmethod
    def _positive(cls, v: str) -> str:
        try:
            if Decimal(v) <= 0:
                raise ValueError
        except (InvalidOperation, ValueError) as exc:
            raise ValueError("amount must be a positive decimal string") from exc
        return v


class WebhookRequest(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    events: list[str] = Field(default_factory=lambda: ["payment.settled", "payment.failed"])

    @field_validator("url")
    @classmethod
    def _https(cls, v: str) -> str:
        if not v.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            raise ValueError("Webhook URLs must be HTTPS (localhost is allowed for testing)")
        return v

    @field_validator("events")
    @classmethod
    def _known(cls, v: list[str]) -> list[str]:
        unknown = set(v) - webhooks.EVENTS
        if unknown:
            raise ValueError(f"unknown events: {sorted(unknown)}; valid: {sorted(webhooks.EVENTS)}")
        return v


def _intent_view(intent: PaymentIntent, tx: Transaction | None) -> dict:
    return {
        "id": intent.id,
        "object": "payment_intent",
        "status": str(intent.status),
        "createdAt": intent.createdAt.isoformat(),
        "sourceCurrency": intent.sourceCurrency,
        "destinationCurrency": intent.destinationCurrency,
        "amount": str(intent.amount),
        "recipient": {"name": intent.recipientName, "msisdn": intent.recipientMsisdn},
        "reference": intent.partnerReference,
        "idempotencyKey": intent.idempotencyKey,
        "transaction": {
            "id": tx.id,
            "reference": tx.reference,
            "state": str(tx.state),
            "destinationAmount": str(tx.destinationAmount),
            "fees": tx.fees.as_dict(),
            "fxRate": str(tx.fxRate),
            "mpesaReceipt": tx.mpesaReceipt,
            "onchainTxHash": tx.onchainRecord.txHash if tx.onchainRecord else "",
            "settledAt": tx.settledAt.isoformat() if tx.settledAt else None,
        }
        if tx
        else None,
    }


# ---------------------------------------------------------------------------
# FR 4.2 - payment intents
# ---------------------------------------------------------------------------


@router.post("/payment_intents", status_code=status.HTTP_201_CREATED)
async def create_payment_intent(
    body: PaymentIntentRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    key: ApiKey = Depends(require_scope("payments:write")),
    db: Session = Depends(get_session),
) -> dict:
    """Create a cross-border payment (FR 4.2).

    The intent produces a Transaction - the same Transaction a CowriePay user
    would create from the app, which is the "one payment intent produces at most
    one transaction" association on the class diagram.  Both surfaces settle
    over identical rails; only the entry point differs.
    """
    if not idempotency_key:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "An Idempotency-Key header is required on every write request (FR 4.1).",
        )

    # Replay of a key we have already seen returns the original result.
    existing = db.execute(
        select(PaymentIntent).where(PaymentIntent.idempotencyKey == idempotency_key)
    ).scalar_one_or_none()
    if existing:
        if existing.apiKeyId != key.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "That idempotency key belongs to another API key."
            )
        tx = db.get(Transaction, existing.transactionId) if existing.transactionId else None
        return _intent_view(existing, tx)

    if body.sourceCurrency != "NGN" or body.destinationCurrency != "KES":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Only the {settings.corridor_source}->{settings.corridor_destination} corridor is "
            "live in v1.0. Other corridors ship with v2.0 (SRS 1.1).",
        )

    amount = Decimal(body.amount)
    try:
        quote = quote_engine.quote(source_amount=amount)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    intent = PaymentIntent(
        idempotencyKey=idempotency_key,
        apiKeyId=key.id,
        status=IntentStatus.CREATED,
        sourceCurrency=body.sourceCurrency,
        destinationCurrency=body.destinationCurrency,
        amount=amount,
        recipientName=body.recipientName,
        recipientMsisdn=body.recipientMsisdn,
        partnerReference=body.reference,
    )
    db.add(intent)
    db.flush()

    # An institutional payment settles from the partner's own float rather than
    # a consumer's linked bank account, so it is attributed to the partner's
    # settlement account rather than to an individual sender.
    settlement_user = _settlement_account(db, key)

    tx = transfer_service.create_transfer(
        db,
        user=settlement_user,
        quote=quote,
        recipient_name=body.recipientName,
        recipient_msisdn=body.recipientMsisdn,
        channel="API",
        scenario=body.scenario,
    )
    intent.transactionId = tx.id
    intent.status = IntentStatus.PROCESSING

    audit.record(
        db,
        entity_type="PaymentIntent",
        entity_id=intent.id,
        action="transaction.created",
        actor=ActorType.SYSTEM,
        actor_id=f"apikey:{key.prefix}",
        after=audit.snapshot(intent),
        detail={"partner": key.partnerName, "reference": body.reference},
    )
    db.commit()

    # An API-originated transfer has no PIN step: the API key is the
    # authorisation, which is what FR 4.1 makes it.
    await transfer_service.transition(
        db, tx, TransactionState.AUTHORIZED, actor=ActorType.SYSTEM, actor_id=f"apikey:{key.prefix}"
    )
    transfer_service.launch(tx.id)

    # Tell the partner the payment exists now, rather than only when it lands.
    # Fire-and-forget: a partner's slow endpoint must never delay a settlement.
    webhooks.fire_and_forget(
        _emit_created(key.partnerId, intent.id, body.reference, str(intent.amount))
    )

    return _intent_view(intent, tx)


async def _emit_created(partner_id: str, intent_id: str, reference: str, amount: str) -> None:
    from ..db import session_scope

    with session_scope() as db:
        await webhooks.deliver(
            db,
            partner_id=partner_id,
            event="payment.created",
            payload={
                "id": intent_id,
                "object": "payment_intent",
                "status": "PROCESSING",
                "amount": amount,
                "reference": reference,
            },
        )


def _settlement_account(db: Session, key: ApiKey) -> User:
    """The partner's settlement account, created on first use.

    Transactions require a sender (the class diagram's User o-- Transaction),
    and an institutional payment has no individual behind it.  Rather than make
    senderId nullable and special-case it everywhere, each partner gets one
    settlement account that owns their transactions.
    """
    email = f"settlement+{key.partnerId[:8]}@partners.cowrie.demo"
    account = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if account:
        return account

    from ..enums import KycLevel

    account = User(
        fullName=f"{key.partnerName} (settlement account)",
        phone=f"+000{key.partnerId[:9]}",
        email=email,
        country="NG",
        kycLevel=KycLevel.TIER3,
        ngnBalance=Decimal("500000000.00"),
        bankName="Partner settlement float",
        bankAccountMasked="******0001",
    )
    account._pinHash = hash_secret("000000")
    db.add(account)
    db.flush()
    return account


@router.get("/payment_intents/{intent_id}")
def get_payment_intent(
    intent_id: str,
    key: ApiKey = Depends(require_scope("payments:read")),
    db: Session = Depends(get_session),
) -> dict:
    intent = db.get(PaymentIntent, intent_id)
    if intent is None or intent.apiKeyId != key.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such payment intent")
    tx = db.get(Transaction, intent.transactionId) if intent.transactionId else None
    return _intent_view(intent, tx)


@router.get("/payment_intents")
def list_payment_intents(
    key: ApiKey = Depends(require_scope("payments:read")),
    db: Session = Depends(get_session),
    limit: int = Query(default=25, le=100),
    status_filter: IntentStatus | None = Query(default=None, alias="status"),
) -> dict:
    stmt = (
        select(PaymentIntent)
        .where(PaymentIntent.apiKeyId == key.id)
        .order_by(PaymentIntent.createdAt.desc())
        .limit(limit)
    )
    if status_filter:
        stmt = stmt.where(PaymentIntent.status == status_filter)

    rows = db.execute(stmt).scalars().all()
    return {
        "object": "list",
        "data": [
            _intent_view(i, db.get(Transaction, i.transactionId) if i.transactionId else None)
            for i in rows
        ],
        "hasMore": len(rows) == limit,
    }


# ---------------------------------------------------------------------------
# quotes (read-only pricing, no commitment)
# ---------------------------------------------------------------------------


@router.get("/quotes")
def api_quote(
    amount: str = Query(description="Amount in NGN"),
    key: ApiKey = Depends(require_scope("payments:read")),
) -> dict:
    try:
        return quote_engine.quote(source_amount=Decimal(amount)).as_dict()
    except (ValueError, InvalidOperation) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/quotes/reverse")
def api_reverse_quote(
    destinationAmount: str = Query(description="Amount the recipient should receive, in KES"),
    key: ApiKey = Depends(require_scope("payments:read")),
) -> dict:
    """Price backwards from the payout amount - the common institutional case."""
    try:
        return quote_engine.quote_for_destination(
            destination_amount=Decimal(destinationAmount)
        ).as_dict()
    except (ValueError, InvalidOperation) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


# ---------------------------------------------------------------------------
# "Analyze transaction stats" use case
# ---------------------------------------------------------------------------


@router.get("/stats")
def transaction_stats(
    key: ApiKey = Depends(require_scope("payments:read")),
    db: Session = Depends(get_session),
    days: int = Query(default=30, le=365),
) -> dict:
    """Volume, settlement rate, latency and cost for this partner."""
    since = datetime.now(UTC) - timedelta(days=days)

    intents = (
        db.execute(
            select(PaymentIntent).where(
                PaymentIntent.apiKeyId == key.id, PaymentIntent.createdAt >= since
            )
        )
        .scalars()
        .all()
    )
    tx_ids = [i.transactionId for i in intents if i.transactionId]
    transactions = (
        db.execute(select(Transaction).where(Transaction.id.in_(tx_ids))).scalars().all()
        if tx_ids
        else []
    )

    settled = [t for t in transactions if t.state == TransactionState.SETTLED]
    refunded = [t for t in transactions if t.state == TransactionState.REFUNDED]
    failed = [t for t in transactions if t.state == TransactionState.FAILED]

    volume_ngn = sum((t.sourceAmount for t in settled), Decimal("0"))
    fees_ngn = sum((t.fees.total() for t in settled), Decimal("0"))
    latencies = sorted(
        (t.settledAt - t.createdAt).total_seconds() for t in settled if t.settledAt and t.createdAt
    )

    def percentile(p: float) -> float:
        if not latencies:
            return 0.0
        return round(latencies[min(len(latencies) - 1, int(len(latencies) * p))], 2)

    terminal = len(settled) + len(refunded) + len(failed)

    return {
        "periodDays": days,
        "partner": key.partnerName,
        "contactName": key.contactName,
        "environment": key.environment,
        "counts": {
            "created": len(intents),
            "settled": len(settled),
            "refunded": len(refunded),
            "failed": len(failed),
        },
        "volume": {
            "sourceNgn": str(volume_ngn),
            "destinationKes": str(sum((t.destinationAmount for t in settled), Decimal("0"))),
            "usdEquivalent": str(
                (volume_ngn / Decimal(str(settings.mid_market_ngn_per_usd))).quantize(Decimal("0.01"))
            ),
        },
        "cost": {
            "totalFeesNgn": str(fees_ngn),
            "averageCostPercent": str(
                ((fees_ngn / volume_ngn) * 100).quantize(Decimal("0.01"))
                if volume_ngn
                else Decimal("0")
            ),
        },
        "settlement": {
            "successRate": round(len(settled) / terminal * 100, 2) if terminal else 0.0,
            "medianSeconds": percentile(0.5),
            "p95Seconds": percentile(0.95),
            "slaTargetSeconds": 30,
        },
    }


# ---------------------------------------------------------------------------
# FR 4.3 - webhook endpoints
# ---------------------------------------------------------------------------


@router.post("/webhooks", status_code=status.HTTP_201_CREATED)
def create_webhook(
    body: WebhookRequest,
    key: ApiKey = Depends(require_scope("payments:write")),
    db: Session = Depends(get_session),
) -> dict:
    """Register a signed webhook endpoint.

    The signing secret is returned exactly once, here.  It is needed to verify
    signatures, so it cannot be one-way hashed the way an API key is - see the
    note in services/webhooks.py.
    """
    secret, prefix = generate_webhook_secret()
    endpoint = Webhook(
        partnerId=key.partnerId,
        url=body.url,
        status=WebhookStatus.ACTIVE,
        events=body.events,
        signingSecretPrefix=prefix,
        environment=key.environment,
    )
    endpoint._secretHash = secret
    db.add(endpoint)
    db.commit()

    return {
        "id": endpoint.id,
        "url": endpoint.url,
        "events": endpoint.events,
        "status": str(endpoint.status),
        "signingSecret": secret,
        "warning": "This signing secret is shown once. Store it now.",
        "signatureScheme": "HMAC-SHA256 over '{timestamp}.{body}', header 'Cowrie-Signature: t=..,v1=..'",
    }


@router.get("/webhooks")
def list_webhooks(
    key: ApiKey = Depends(require_scope("payments:read")),
    db: Session = Depends(get_session),
) -> dict:
    rows = (
        db.execute(select(Webhook).where(Webhook.partnerId == key.partnerId)).scalars().all()
    )
    return {
        "data": [
            {
                "id": w.id,
                "url": w.url,
                "events": w.events,
                "status": str(w.status),
                "signingSecretPrefix": w.signingSecretPrefix,
                "createdAt": w.createdAt.isoformat(),
            }
            for w in rows
        ]
    }


@router.post("/webhooks/{webhook_id}/test")
async def test_webhook(
    webhook_id: str,
    key: ApiKey = Depends(require_scope("payments:write")),
    db: Session = Depends(get_session),
) -> dict:
    """Send a test payload (the developer portal's payload test, SRS §3.1)."""
    endpoint = db.get(Webhook, webhook_id)
    if endpoint is None or endpoint.partnerId != key.partnerId:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such webhook endpoint")

    delivery = await webhooks.send_test(db, endpoint)
    return {
        "delivered": delivery.delivered,
        "responseStatus": delivery.responseStatus,
        "signature": delivery.signature,
        "payload": delivery.payload,
        "nextRetryAt": delivery.nextRetryAt.isoformat() if delivery.nextRetryAt else None,
    }


@router.get("/webhooks/deliveries")
def webhook_deliveries(
    key: ApiKey = Depends(require_scope("payments:read")),
    db: Session = Depends(get_session),
    limit: int = Query(default=50, le=200),
) -> dict:
    return {"data": webhooks.history(db, partner_id=key.partnerId, limit=limit)}


# ---------------------------------------------------------------------------
# FR 4.1 - business onboarding
# ---------------------------------------------------------------------------


class PartnerSignup(BaseModel):
    """A business registering for API access."""

    organisation: str = Field(min_length=2, max_length=160)
    fullName: str = Field(min_length=2, max_length=160, description="Who is integrating")
    email: str = Field(min_length=5, max_length=255)
    country: str = Field(default="NG", min_length=2, max_length=2)


@router.post("/partners", status_code=status.HTTP_201_CREATED, tags=["cowrie-api"])
def register_partner(body: PartnerSignup, db: Session = Depends(get_session)) -> dict:
    """Create a partner and issue its first key pair (FR 4.1).

    Public, because a business cannot obtain a key without one and there is no
    prior credential to authenticate with. Sandbox only: a live corridor needs
    the business verified first, which is a manual step, not a form.
    """
    import uuid as _uuid

    existing = db.execute(
        select(ApiKey).where(ApiKey.partnerName == body.organisation.strip())
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "An organisation with that name is already registered.",
        )

    partner_id = str(_uuid.uuid4())
    pair = generate_key_pair("sandbox")
    # SRS 3.3: "API keys and webhook signing secrets are rotated every 90 days".
    expires = datetime.now(UTC) + timedelta(days=KEY_LIFETIME_DAYS)

    secret = ApiKey(
        partnerId=partner_id,
        scopes="payments:read payments:write",
        partnerName=body.organisation.strip(),
        contactName=body.fullName.strip(),
        contactEmail=body.email.strip(),
        label="Secret key",
        prefix=pair["secret_prefix"],
        environment="sandbox",
        expiresAt=expires,
    )
    secret._keyHash = hash_secret(pair["secret"])
    db.add(secret)

    publishable = ApiKey(
        partnerId=partner_id,
        scopes="payments:read",
        partnerName=body.organisation.strip(),
        contactName=body.fullName.strip(),
        contactEmail=body.email.strip(),
        label="Publishable key",
        prefix=pair["publishable_prefix"],
        environment="sandbox",
        expiresAt=expires,
    )
    publishable._keyHash = hash_secret(pair["publishable"])
    db.add(publishable)
    db.flush()

    audit.record(
        db,
        entity_type="ApiKey",
        entity_id=secret.id,
        action="partner.registered",
        actor=ActorType.SYSTEM,
        actor_id=body.email,
        after={"organisation": body.organisation, "partnerId": partner_id},
    )
    db.commit()

    return {
        "partnerId": partner_id,
        "organisation": body.organisation.strip(),
        "contactName": body.fullName.strip(),
        "environment": "sandbox",
        "secretKey": pair["secret"],
        "publishableKey": pair["publishable"],
        "expiresAt": expires.isoformat(),
        "warning": "The secret key is shown once. Store it now.",
    }


@router.post("/keys", status_code=status.HTTP_201_CREATED)
def create_key(
    key: ApiKey = Depends(require_scope("payments:write")),
    db: Session = Depends(get_session),
) -> dict:
    """Issue an additional key pair for the calling partner (FR 4.1).

    Authenticated by an existing key, so a partner can rotate without support
    involvement: create the new pair, migrate, then revoke the old one. The old
    key keeps working until it is revoked, which is what makes a rotation
    possible without downtime.
    """
    pair = generate_key_pair(key.environment or "sandbox")
    expires = datetime.now(UTC) + timedelta(days=KEY_LIFETIME_DAYS)

    secret = ApiKey(
        partnerId=key.partnerId,
        scopes="payments:read payments:write",
        partnerName=key.partnerName,
        contactName=key.contactName,
        contactEmail=key.contactEmail,
        label="Secret key",
        prefix=pair["secret_prefix"],
        environment=key.environment or "sandbox",
        expiresAt=expires,
    )
    secret._keyHash = hash_secret(pair["secret"])
    db.add(secret)

    publishable = ApiKey(
        partnerId=key.partnerId,
        scopes="payments:read",
        partnerName=key.partnerName,
        contactName=key.contactName,
        contactEmail=key.contactEmail,
        label="Publishable key",
        prefix=pair["publishable_prefix"],
        environment=key.environment or "sandbox",
        expiresAt=expires,
    )
    publishable._keyHash = hash_secret(pair["publishable"])
    db.add(publishable)
    db.flush()

    audit.record(
        db,
        entity_type="ApiKey",
        entity_id=secret.id,
        action="apikey.created",
        actor=ActorType.SYSTEM,
        actor_id=f"apikey:{key.prefix}",
        after={"partnerId": key.partnerId, "prefix": pair["secret_prefix"]},
    )
    db.commit()

    return {
        "secretKey": pair["secret"],
        "publishableKey": pair["publishable"],
        "expiresAt": expires.isoformat(),
        "warning": "The secret key is shown once. Store it now.",
    }


@router.get("/keys")
def list_keys(
    key: ApiKey = Depends(require_scope("payments:read")),
    db: Session = Depends(get_session),
) -> dict:
    """Every key this partner holds, by prefix. Secrets are never returned."""
    rows = (
        db.execute(
            select(ApiKey).where(ApiKey.partnerId == key.partnerId).order_by(ApiKey.createdAt)
        )
        .scalars()
        .all()
    )
    return {
        "data": [
            {
                "id": row.id,
                "label": row.label,
                "prefix": row.prefix,
                "scopes": row.scopes,
                "environment": row.environment,
                "revoked": row.revokedAt is not None,
                "expiresAt": row.expiresAt.isoformat() if row.expiresAt else None,
                "daysUntilExpiry": row.daysUntilExpiry(),
                "expired": row.expiresAt is not None and not row.isActive() and row.revokedAt is None,
                "current": row.id == key.id,
                "lastUsedAt": row.lastUsedAt.isoformat() if row.lastUsedAt else None,
                "requestCount": row.requestCount,
                "createdAt": row.createdAt.isoformat(),
            }
            for row in rows
        ]
    }


@router.post("/keys/{key_id}/revoke")
def revoke_key(
    key_id: str,
    key: ApiKey = Depends(require_scope("payments:write")),
    db: Session = Depends(get_session),
) -> dict:
    """Revoke a key. Refuses the key making the request, so a partner cannot
    lock itself out in one call."""
    target = db.get(ApiKey, key_id)
    if target is None or target.partnerId != key.partnerId:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such key")
    if target.id == key.id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That is the key you are using. Create a replacement first.",
        )

    target.revoke()
    audit.record(
        db,
        entity_type="ApiKey",
        entity_id=target.id,
        action="apikey.revoked",
        actor=ActorType.SYSTEM,
        actor_id=f"apikey:{key.prefix}",
        after={"prefix": target.prefix},
    )
    db.commit()
    return {"id": target.id, "revoked": True}
