"""Safaricom Daraja v2 - M-Pesa off-ramp (simulated).

Stands in for the Daraja B2C endpoint (SRS 3.3), which credits Kenyan shillings
into a recipient's M-Pesa wallet.  This is the last leg of the corridor and the
one that makes the transfer real to the recipient.

Real integration shape, preserved here:
    POST /mpesa/b2c/v3/paymentrequest
        -> {"ConversationID", "OriginatorConversationID", "ResponseCode"}
    result callback -> {"TransactionReceipt": "SJ48H3K2LM", ...}

FR 2.3 requires that the M-Pesa transaction ID be matched to the on-chain
record, so `receipt` is returned to the caller and stored on the Transaction
next to the bridge txHash.

Not simulated: OAuth 2.0 client-credentials token fetch, the security
credential encryption Safaricom requires, and the reversal endpoint.
"""

from __future__ import annotations

import asyncio
import random
import string
from dataclasses import dataclass
from decimal import Decimal

from ..config import settings


@dataclass(slots=True)
class DarajaPayoutResult:
    credited: bool
    receipt: str
    conversation_id: str = ""
    failure_reason: str = ""


def _mpesa_receipt() -> str:
    """M-Pesa receipts are 10 characters, uppercase alphanumeric."""
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choice(alphabet) for _ in range(10))


class DarajaAdapter:
    """Simulated B2C payout to an M-Pesa wallet."""

    name = "Safaricom Daraja API v2"
    simulated = True

    async def payout(
        self,
        *,
        msisdn: str,
        amount: Decimal,
        remarks: str,
        force_failure: bool = False,
    ) -> DarajaPayoutResult:
        """Credit KES to the recipient's wallet.

        Sequence diagram steps 16 -> 17.  `force_failure` is the demo hook
        behind DemoScenario.PAYOUT_FAILED, which drives
        OffRampPending -> Refunding.
        """
        await asyncio.sleep(settings.scaled(1.5))

        if force_failure:
            return DarajaPayoutResult(
                credited=False,
                receipt="",
                failure_reason="Daraja B2C failed: recipient wallet limit exceeded (simulated)",
            )

        return DarajaPayoutResult(
            credited=True,
            receipt=_mpesa_receipt(),
            conversation_id=f"AG_{random.randint(10**9, 10**10 - 1)}_{_mpesa_receipt()[:6]}",
        )

    async def balance(self) -> dict:
        """Daraja account balance - what funds the corridor's KES float."""
        await asyncio.sleep(settings.scaled(0.2))
        return {"currency": "KES", "available": "48250000.00", "source": "simulated"}
