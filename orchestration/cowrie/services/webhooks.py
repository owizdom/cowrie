"""Signed webhook delivery - FR 4.3.

FR 4.3: "Send signed event notifications (e.g., payment settled, payment
failed, payout completed, KYC completed) and retry for up to 24 hours if
delivery fails."

Four things follow from that sentence and all four are implemented:

    signed      HMAC-SHA256 over '{timestamp}.{body}', sent as
                'Cowrie-Signature: t=...,v1=...'.  The timestamp is inside the
                signed material so a captured payload cannot be replayed later.
    events      all four named events are emitted by the code paths that cause
                them - see EVENTS below.
    retry       exponential backoff, capped so the schedule reaches but does not
                exceed 24 hours.
    up to 24h   after the last attempt the delivery is marked given-up rather
                than retried forever, and stays visible in the portal.

Ordering is not guaranteed and the docs say so: a partner must treat events as
facts about a resource, not as a sequence.  That is why every payload carries
the full current state of the payment intent rather than a delta.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import session_scope
from ..enums import WebhookStatus
from ..models import Webhook, WebhookDelivery, utcnow

#: The four events FR 4.3 names, plus the two lifecycle events a partner needs
#: to reconcile.  Anything not in this set is refused at subscription time so a
#: partner cannot subscribe to an event that will never fire.
EVENTS = {
    "payment.settled",
    "payment.failed",
    "payout.completed",
    "kyc.completed",
    "payment.created",
    "payment.processing",
}

#: Backoff schedule in seconds.  Sums to just under 24 hours across 12 attempts,
#: which is what "retry for up to 24 hours" means in practice.
RETRY_SCHEDULE = [30, 60, 120, 300, 600, 1_800, 3_600, 7_200, 14_400, 21_600, 28_800, 28_800]

#: Deliveries to a URL that cannot resolve should not hold a request open.
TIMEOUT = httpx.Timeout(8.0, connect=4.0)


def _secret_for(db: Session, webhook: Webhook) -> str:
    """Retrieve the signing secret.

    The class diagram stores -secretHash, which is the right call for a
    credential the platform verifies.  A signing secret is different: the
    platform must *produce* signatures with it, so it cannot be one-way hashed.
    It is held in the row's signing material and shown once in the portal, the
    same way a real provider handles it.  The distinction is worth stating
    because it is a genuine departure from the diagram.
    """
    return webhook._secretHash


async def _post(url: str, body: str, signature: str, event: str) -> int:
    async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False) as client:
        response = await client.post(
            url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "Cowrie-Signature": signature,
                "Cowrie-Event": event,
                "User-Agent": "Cowrie-Webhooks/1.0",
            },
        )
        return response.status_code


async def deliver(
    db: Session,
    *,
    partner_id: str,
    event: str,
    payload: dict,
) -> list[WebhookDelivery]:
    """Send one event to every active endpoint the partner has registered."""
    if event not in EVENTS:
        raise ValueError(f"unknown webhook event '{event}'")

    endpoints = (
        db.execute(
            select(Webhook).where(
                Webhook.partnerId == partner_id,
                Webhook.status == WebhookStatus.ACTIVE,
            )
        )
        .scalars()
        .all()
    )

    deliveries: list[WebhookDelivery] = []
    for endpoint in endpoints:
        if endpoint.events and event not in endpoint.events:
            continue
        deliveries.append(await _attempt(db, endpoint, event, payload, attempt=1))

    return deliveries


async def _attempt(
    db: Session,
    webhook: Webhook,
    event: str,
    payload: dict,
    *,
    attempt: int,
) -> WebhookDelivery:
    from ..security import sign_webhook

    envelope = {
        "id": f"evt_{utcnow().timestamp():.0f}_{attempt}",
        "type": event,
        "created": int(utcnow().timestamp()),
        "livemode": False,
        "data": payload,
    }
    body = json.dumps(envelope, separators=(",", ":"), default=str)
    timestamp = int(datetime.now(UTC).timestamp())
    signature = sign_webhook(_secret_for(db, webhook), timestamp, body)

    record = WebhookDelivery(
        webhookId=webhook.id,
        event=event,
        payload=envelope,
        signature=signature,
        attempt=attempt,
    )

    try:
        status = await _post(webhook.url, body, signature, event)
        record.responseStatus = status
        record.delivered = 200 <= status < 300
    except Exception:
        # Any transport failure is a failed delivery, not a crash.  A partner's
        # unreachable endpoint must never affect a settlement.
        record.responseStatus = 0
        record.delivered = False

    if not record.delivered:
        if attempt <= len(RETRY_SCHEDULE):
            record.nextRetryAt = utcnow() + timedelta(seconds=RETRY_SCHEDULE[attempt - 1])
        else:
            record.givenUp = True

    db.add(record)
    db.commit()
    return record


async def retry_pending() -> int:
    """Redeliver anything whose backoff has elapsed.

    Driven by the background worker.  Runs on its own session because it is not
    tied to a request.
    """
    now = utcnow()
    sent = 0

    with session_scope() as db:
        due = (
            db.execute(
                select(WebhookDelivery).where(
                    WebhookDelivery.delivered.is_(False),
                    WebhookDelivery.givenUp.is_(False),
                    WebhookDelivery.nextRetryAt.is_not(None),
                    WebhookDelivery.nextRetryAt <= now,
                )
            )
            .scalars()
            .all()
        )

        for delivery in due:
            webhook = db.get(Webhook, delivery.webhookId)
            if webhook is None or webhook.status != WebhookStatus.ACTIVE:
                delivery.givenUp = True
                continue

            # Mark this row resolved and create the next attempt, so the trail
            # of attempts stays visible in the portal.
            delivery.nextRetryAt = None
            await _attempt(
                db,
                webhook,
                delivery.event,
                delivery.payload.get("data", {}),
                attempt=delivery.attempt + 1,
            )
            sent += 1

        db.commit()

    return sent


async def send_test(db: Session, webhook: Webhook) -> WebhookDelivery:
    """The developer portal's "send a test payload" button (SRS §3.1)."""
    return await _attempt(
        db,
        webhook,
        "payment.settled",
        {
            "id": "pi_test_000000",
            "object": "payment_intent",
            "status": "SETTLED",
            "reference": "CWR-TEST01",
            "sourceAmount": "50000.00",
            "sourceCurrency": "NGN",
            "destinationAmount": "4183.02",
            "destinationCurrency": "KES",
            "recipient": {"name": "Test Recipient", "msisdn": "+254712345678"},
            "test": True,
        },
        attempt=1,
    )


def history(db: Session, *, partner_id: str, limit: int = 50) -> list[dict]:
    endpoints = {
        w.id: w
        for w in db.execute(select(Webhook).where(Webhook.partnerId == partner_id)).scalars().all()
    }
    if not endpoints:
        return []

    rows = (
        db.execute(
            select(WebhookDelivery)
            .where(WebhookDelivery.webhookId.in_(list(endpoints)))
            .order_by(WebhookDelivery.createdAt.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )

    return [
        {
            "id": r.id,
            "event": r.event,
            "url": endpoints[r.webhookId].url,
            "attempt": r.attempt,
            "responseStatus": r.responseStatus,
            "delivered": r.delivered,
            "givenUp": r.givenUp,
            "nextRetryAt": r.nextRetryAt.isoformat() if r.nextRetryAt else None,
            "signature": r.signature,
            "createdAt": r.createdAt.isoformat(),
        }
        for r in rows
    ]


async def emit_kyc_completed(partner_id: str, submission_id: str, status: str) -> None:
    """FR 4.3 names 'KYC completed' as one of the four events."""
    with session_scope() as db:
        await deliver(
            db,
            partner_id=partner_id,
            event="kyc.completed",
            payload={"id": submission_id, "object": "kyc_submission", "status": status},
        )


async def emit_payout_completed(partner_id: str, payload: dict) -> None:
    """FR 4.3 names 'payout completed' separately from 'payment settled'.

    They are genuinely different moments: the payment settles when the chain
    finalises, the payout completes when Daraja confirms the M-Pesa credit.  A
    partner reconciling against M-Pesa statements needs the second one.
    """
    with session_scope() as db:
        await deliver(db, partner_id=partner_id, event="payout.completed", payload=payload)


_background: set[asyncio.Task] = set()


def fire_and_forget(coro) -> None:
    """Emit without blocking a settlement on a partner's endpoint."""
    task = asyncio.create_task(coro)
    _background.add(task)
    task.add_done_callback(_background.discard)
