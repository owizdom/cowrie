"""Support tickets and the in-app help centre.

Covers two things the SRS asks for that are easy to overlook:

    SRS §2.2   "create a support ticket" - one of the nine CowriePay functions,
               and its own use case on the use case diagram.
    SRS §2.6   "CowriePay: Help center in app" - the user documentation
               commitment.

A ticket becomes a Dispute row, which is the same queue an admin resolves under
FR 5.2 ("Show pending KYC submissions and disputes in review queues").  Tying
the user-facing ticket and the compliance-facing dispute to one record is
deliberate: two separate queues would let a user's complaint and an analyst's
case drift apart.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_session
from ..enums import ActorType, DisputeStatus
from ..models import Dispute, Transaction, User
from ..services import audit
from .deps import current_user

router = APIRouter(prefix="/support", tags=["support"])


class TicketRequest(BaseModel):
    subject: str = Field(min_length=4, max_length=200)
    body: str = Field(min_length=10, max_length=4000)
    transactionReference: str | None = None


@router.post("/tickets", status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: TicketRequest,
    user: User = Depends(current_user),
    db: Session = Depends(get_session),
) -> dict:
    """Raise a support ticket ("Create support ticket" use case)."""
    transaction_id = None
    if payload.transactionReference:
        tx = db.execute(
            select(Transaction).where(
                Transaction.reference == payload.transactionReference,
                Transaction.senderId == user.id,
            )
        ).scalar_one_or_none()
        if tx is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                "No transfer with that reference on your account.",
            )
        transaction_id = tx.id

    dispute = Dispute(
        userId=user.id,
        transactionId=transaction_id,
        subject=payload.subject,
        body=payload.body,
        status=DisputeStatus.OPEN,
    )
    db.add(dispute)
    db.flush()

    audit.record(
        db,
        entity_type="Dispute",
        entity_id=dispute.id,
        action="dispute.opened",
        actor=ActorType.USER,
        actor_id=user.id,
        after=audit.snapshot(dispute),
        detail={"subject": payload.subject, "transactionReference": payload.transactionReference},
    )
    db.commit()

    return {
        "id": dispute.id,
        "status": str(dispute.status),
        "subject": dispute.subject,
        "createdAt": dispute.createdAt.isoformat(),
        "message": "Ticket raised. Our compliance team reviews disputes within one business day.",
    }


@router.get("/tickets")
def my_tickets(user: User = Depends(current_user), db: Session = Depends(get_session)) -> dict:
    rows = (
        db.execute(
            select(Dispute).where(Dispute.userId == user.id).order_by(Dispute.createdAt.desc())
        )
        .scalars()
        .all()
    )
    return {
        "tickets": [
            {
                "id": d.id,
                "subject": d.subject,
                "body": d.body,
                "status": str(d.status),
                "resolution": d.resolution,
                "createdAt": d.createdAt.isoformat(),
                "resolvedAt": d.resolvedAt.isoformat() if d.resolvedAt else None,
            }
            for d in rows
        ]
    }


# ---------------------------------------------------------------------------
# in-app help centre (SRS §2.6)
# ---------------------------------------------------------------------------

HELP_ARTICLES = [
    {
        "slug": "how-long-does-a-transfer-take",
        "title": "How long does a transfer take?",
        "category": "Sending money",
        "body": (
            "Most transfers settle in under 30 seconds. The longest step is waiting for 12 "
            "confirmations on the Base network, which takes about 24 seconds. If a transfer has "
            "not completed after 10 minutes it is refunded automatically and the naira goes back "
            "to the account it came from. You never have to ask for that refund."
        ),
    },
    {
        "slug": "what-are-the-fees",
        "title": "What am I being charged?",
        "category": "Fees",
        "body": (
            "Four separate charges, and you see all four before you confirm: the exchange-rate "
            "spread, the Base network fee, the liquidity spread, and Cowrie's own fee. Together "
            "they come to under 1% of what you send. We never show you one combined number, "
            "because a single figure hides which part is ours and which part is the network's. "
            "For comparison, the World Bank puts the average cost of sending $200 within "
            "Sub-Saharan Africa at 7.4%."
        ),
    },
    {
        "slug": "transfer-is-stuck",
        "title": "My transfer is stuck",
        "category": "Sending money",
        "body": (
            "If a transfer has been pending for more than 5 minutes, a 'Cancel and refund' button "
            "appears on it. Press it and the naira is returned. If you do nothing, the transfer is "
            "refunded automatically once it passes 10 minutes. Either way the money comes back - "
            "a transfer in Cowrie either completes or it refunds, and nothing is left in between."
        ),
    },
    {
        "slug": "why-verify-my-identity",
        "title": "Why do I need to verify my identity?",
        "category": "Account",
        "body": (
            "Two reasons. Cowrie moves money across a regulated border, so we are required to know "
            "who our senders are. And your transfer limit depends on it: a verified phone and email "
            "gets you $200, a government ID raises it to $2,000, and a BVN matched against your bank "
            "record raises it to $20,000. You can use these ID types: NIN, BVN, Kenyan National ID, "
            "NIDA, or Ghana Card."
        ),
    },
    {
        "slug": "recipient-did-not-get-the-money",
        "title": "The recipient has not received the money",
        "category": "Receiving",
        "body": (
            "Check the transfer's status first. If it says Settled, it carries an M-Pesa receipt "
            "number - give that number to the recipient and they can find the payment in their "
            "M-Pesa statement. If it says Refunded, the payout failed and your naira has already "
            "been returned. If it is still moving after 10 minutes, it will refund itself. If the "
            "status says Settled but the recipient still cannot find it, raise a support ticket "
            "with the reference and we will trace it."
        ),
    },
    {
        "slug": "is-my-money-safe",
        "title": "Where is my money while it is moving?",
        "category": "Security",
        "body": (
            "It moves as cUSDC, a dollar-backed stablecoin that Cowrie issues. Every cUSDC in "
            "circulation is backed one-to-one by a real dollar held at a regulated banking partner, "
            "and an outside auditor checks that monthly. You can see the live supply, the reserve "
            "balance and the coverage ratio on our public transparency page at any time - you do "
            "not have to take our word for it."
        ),
    },
]


@router.get("/help")
def help_centre() -> dict:
    """In-app help centre (SRS §2.6)."""
    categories: dict[str, list] = {}
    for article in HELP_ARTICLES:
        categories.setdefault(article["category"], []).append(article)
    return {
        "categories": [
            {"name": name, "articles": articles} for name, articles in categories.items()
        ],
        "articles": HELP_ARTICLES,
    }


@router.get("/help/{slug}")
def help_article(slug: str) -> dict:
    for article in HELP_ARTICLES:
        if article["slug"] == slug:
            return article
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Article not found")
