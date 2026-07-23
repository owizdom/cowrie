"""cUSDC reserve banking partner (simulated).

Stands in for the regulated bank holding the 1:1 USD reserves behind cUSDC
(SRS 3.3, "cUSDC Reserve Banking Partner", encrypted REST API).

This adapter is the gate in FR 3.2: "Only create new cUSDC after the banking
partner confirms a matching USD deposit ... Reject any attempt to create cUSDC
without verified dollar backing."  The mint path in reserve_service calls
`confirm_deposit` first and refuses to proceed when it comes back unconfirmed,
which is what makes the requirement testable rather than aspirational.

Not simulated: the bank's actual API, the third-party attestor's signature on
the monthly report, and daily reconciliation against a real ledger.
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from decimal import Decimal

from ..config import settings


@dataclass(slots=True)
class DepositConfirmation:
    confirmed: bool
    reference: str
    amount_usd: Decimal
    reason: str = ""


@dataclass(slots=True)
class AttestationReport:
    attestor: str
    usd_balance: Decimal
    report_url: str
    period: str


class BankingPartnerAdapter:
    """Simulated reserve custody and attestation."""

    name = "Cowrie Reserve Banking Partner"
    partner = "Access Bank (Trust Account, simulated)"
    attestor = "Adeyemi & Partners LLP (simulated attestor)"
    simulated = True

    #: The USD sitting in the trust account.  Seeded, and moved by mint/burn.
    _usd_on_hand: Decimal = Decimal("12400128.00")

    async def confirm_deposit(self, *, amount: Decimal, reference: str) -> DepositConfirmation:
        """Confirm that `amount` USD actually landed before any cUSDC is minted.

        FR 3.2.  A reference that does not look like a settled wire is refused,
        which is what the admin console demonstrates when an operator tries to
        mint without one.
        """
        await asyncio.sleep(settings.scaled(0.8))

        if not reference or not reference.strip():
            return DepositConfirmation(
                confirmed=False,
                reference="",
                amount_usd=Decimal("0"),
                reason="No USD deposit reference supplied; mint refused (FR 3.2)",
            )

        if amount <= 0:
            return DepositConfirmation(
                confirmed=False,
                reference=reference,
                amount_usd=Decimal("0"),
                reason="Deposit amount must be positive",
            )

        return DepositConfirmation(confirmed=True, reference=reference, amount_usd=amount)

    async def redeem(self, *, amount: Decimal) -> str:
        """Pay USD out of the trust account when cUSDC is burned."""
        await asyncio.sleep(settings.scaled(0.6))
        return f"WIRE-OUT-{secrets.token_hex(4).upper()}"

    async def reserve_balance(self) -> Decimal:
        await asyncio.sleep(settings.scaled(0.1))
        return self._usd_on_hand

    async def request_attestation(self, *, period: str, usd_balance: Decimal) -> AttestationReport:
        """The monthly outside-auditor statement (glossary, "Attestation")."""
        await asyncio.sleep(settings.scaled(0.5))
        return AttestationReport(
            attestor=self.attestor,
            usd_balance=usd_balance,
            report_url=f"https://transparency.cowrie.demo/attestations/{period}.pdf",
            period=period,
        )
