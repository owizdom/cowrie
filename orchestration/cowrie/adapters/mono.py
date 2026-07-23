"""Mono Connect - NGN on-ramp (simulated).

Stands in for Mono Connect API v2 (SRS 3.3), which Cowrie uses to debit the
sender's Nigerian bank account through open banking, settling over NIBSS.

Real integration shape, preserved here:
    POST /v2/payments/initiate  -> {"reference": ..., "status": "pending"}
    webhook  mono.payments.successful / mono.payments.failed

The real call is asynchronous: the API acknowledges immediately and the money
is confirmed by webhook, which is why the sequence diagram shows
"NGN received (async webhook)" as a separate message.  That two-step shape is
kept, because it is the reason ONRAMP_PENDING exists as a state at all.

Not simulated: OAuth token exchange, account linking consent, and the reversal
endpoint.  Those need real credentials.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from decimal import Decimal

from ..config import settings


@dataclass(slots=True)
class MonoDebitResult:
    accepted: bool
    reference: str
    failure_reason: str = ""


@dataclass(slots=True)
class MonoRefundResult:
    refunded: bool
    reference: str
    failure_reason: str = ""


class MonoAdapter:
    """Simulated NGN debit and refund."""

    name = "Mono Connect API v2"
    simulated = True

    async def debit(
        self,
        *,
        user_id: str,
        amount: Decimal,
        narration: str,
        force_error: bool = False,
    ) -> MonoDebitResult:
        """Debit NGN from the sender's linked bank account.

        Sequence diagram step 10 -> 11.  `force_error` is the demo hook behind
        DemoScenario.MONO_ERROR, which drives Authorized -> Failed.
        """
        await asyncio.sleep(settings.scaled(1.2))

        if force_error:
            return MonoDebitResult(
                accepted=False,
                reference="",
                failure_reason="Mono debit declined: insufficient funds at issuing bank (simulated)",
            )

        return MonoDebitResult(accepted=True, reference=f"MONO-{secrets.token_hex(5).upper()}")

    async def refund(self, *, original_reference: str, amount: Decimal) -> MonoRefundResult:
        """Return NGN to the sender.

        Sequence diagram step 21, and the Refunding -> Refunded transition.
        This is the leg that makes NFR 3 true: nothing is left in the system.
        """
        await asyncio.sleep(settings.scaled(1.0))
        return MonoRefundResult(
            refunded=True,
            reference=f"MONO-RFD-{secrets.token_hex(4).upper()}",
        )

    async def account_snapshot(self, *, user_id: str) -> dict:
        """What Mono's account endpoint would return for the linked account."""
        await asyncio.sleep(settings.scaled(0.2))
        return {
            "institution": "Guaranty Trust Bank",
            "accountNumber": "******4417",
            "currency": "NGN",
            "linkedVia": "Mono Connect (simulated)",
        }
