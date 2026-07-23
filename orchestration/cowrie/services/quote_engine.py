"""Quote Engine - FR 2.1 and NFR 6.

FR 2.1: "Shows the live exchange rate, all fees, and the exact amount the
recipient will receive on one confirmation screen. The quote is locked for 60
seconds."

NFR 6: "Every quote shows each fee on its own line (network costs,
exchange-rate spread, and Cowrie's fee). The interface never bundles fees into
a single total."

Those two requirements decide the shape of this module.  The engine returns a
FeeBreakdown value object with four separate components and never a single
"fee" number, and the quote carries an explicit expiry that the transfer
service enforces rather than a soft hint.

How a quote is computed
-----------------------
The corridor has no direct NGN/KES market, which is the whole premise of the
product (problem statement, "No direct African currency pairs").  So the rate is
built through USD, exactly as the settlement path is:

    NGN --(mid-market NGN/USD)--> USD --(mid-market KES/USD)--> KES

and the costs of doing that are itemised:

    fxSpread          0.35%  the spread Cowrie takes on the two conversions
    liquiditySpread   0.15%  the cost of holding float on both ends
    cowrieFee         0.40%  the platform's own fee
    networkGas        ~$0.004 the Base L2 cost of the bridge call, converted
                             to NGN so the sender sees one currency

Total: 0.90% plus gas, which is what the SRS hypothesis claims ("less than 1%
in fees") and what the transparency page publishes.  Compare the 7.4% average
for Sub-Saharan Africa cited in the problem statement.

The mid-market rates are static configuration in this build.  A production
engine reads them from an FX feed, and the SRS lists that as a middleware
function; here they are pinned so the demo produces the same numbers every run.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from ..config import settings
from ..models import FeeBreakdown, Money

TWO_PLACES = Decimal("0.01")
SIX_PLACES = Decimal("0.000001")


def _money(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


@dataclass(slots=True)
class Quote:
    """A locked, itemised price for one corridor movement."""

    id: str
    source: Money
    destination: Money
    fees: FeeBreakdown
    fxRate: Decimal
    """Effective NGN -> KES rate the recipient actually gets, after spread."""
    midMarketRate: Decimal
    """The unspread NGN -> KES rate, published so the spread is inspectable."""
    usdEquivalent: Decimal
    expiresAt: datetime
    corridor: str = "NGN->KES"

    def isExpired(self) -> bool:
        return datetime.now(UTC) >= self.expiresAt

    def secondsRemaining(self) -> int:
        return max(0, int((self.expiresAt - datetime.now(UTC)).total_seconds()))

    def costRatio(self) -> Decimal:
        """All-in cost as a fraction of principal - the sub-1% claim, computed."""
        if not self.source.amount:
            return Decimal("0")
        return (self.fees.total() / self.source.amount).quantize(SIX_PLACES)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "corridor": self.corridor,
            "source": self.source.as_dict(),
            "destination": self.destination.as_dict(),
            "fees": self.fees.as_dict(),
            "fxRate": str(self.fxRate),
            "midMarketRate": str(self.midMarketRate),
            "usdEquivalent": str(self.usdEquivalent),
            "expiresAt": self.expiresAt.isoformat(),
            "secondsRemaining": self.secondsRemaining(),
            "costRatio": str(self.costRatio()),
            "costPercent": str((self.costRatio() * 100).quantize(TWO_PLACES)),
            "lockSeconds": settings.quote_lock_seconds,
        }


class QuoteEngine:
    """Prices one corridor movement, itemised and time-locked."""

    def mid_market_rate(self) -> Decimal:
        """NGN per KES, via USD.

        NGN/USD divided by KES/USD.  At the seeded rates: 1530 / 129.5 = 11.81
        NGN per KES.
        """
        ngn_usd = Decimal(str(settings.mid_market_ngn_per_usd))
        kes_usd = Decimal(str(settings.mid_market_kes_per_usd))
        return (ngn_usd / kes_usd).quantize(SIX_PLACES)

    def quote(self, *, source_amount: Decimal) -> Quote:
        """Price a send of `source_amount` NGN.

        Fees are charged on the principal and deducted before conversion, so
        the recipient figure shown on the confirmation screen is exactly what
        lands in the M-Pesa wallet - which is what FR 2.1 means by "the exact
        amount the recipient will receive".
        """
        if source_amount <= 0:
            raise ValueError("amount must be positive")

        ngn_usd = Decimal(str(settings.mid_market_ngn_per_usd))
        mid = self.mid_market_rate()

        fx_spread = _money(source_amount * Decimal(settings.fx_spread_bps) / Decimal(10_000))
        liquidity = _money(source_amount * Decimal(settings.liquidity_spread_bps) / Decimal(10_000))
        cowrie_fee = _money(source_amount * Decimal(settings.cowrie_fee_bps) / Decimal(10_000))
        gas_ngn = _money(Decimal(str(settings.network_gas_usd)) * ngn_usd)

        fees = FeeBreakdown(
            fxSpread=fx_spread,
            networkGas=gas_ngn,
            liquiditySpread=liquidity,
            cowrieFee=cowrie_fee,
            currency="NGN",
        )

        net_ngn = source_amount - fees.total()
        if net_ngn <= 0:
            raise ValueError("amount is too small to cover the network cost of the transfer")

        destination_amount = _money(net_ngn / mid)

        # The effective rate the sender actually received, which is the honest
        # number to put next to the mid-market rate.
        effective = (source_amount / destination_amount).quantize(SIX_PLACES)

        return Quote(
            id=f"qt_{secrets.token_hex(10)}",
            source=Money(_money(source_amount), "NGN"),
            destination=Money(destination_amount, "KES"),
            fees=fees,
            fxRate=effective,
            midMarketRate=mid,
            usdEquivalent=(source_amount / ngn_usd).quantize(TWO_PLACES),
            expiresAt=datetime.now(UTC) + timedelta(seconds=settings.quote_lock_seconds),
        )

    def quote_for_destination(self, *, destination_amount: Decimal) -> Quote:
        """Price backwards from "recipient should get exactly this much KES".

        Used by the Cowrie API, where a business often knows the payout amount
        rather than the send amount.  Solved directly rather than iteratively:
        with all fees proportional to the principal, source = (dest * mid + gas)
        / (1 - proportional_bps).
        """
        if destination_amount <= 0:
            raise ValueError("amount must be positive")

        ngn_usd = Decimal(str(settings.mid_market_ngn_per_usd))
        mid = self.mid_market_rate()
        gas_ngn = Decimal(str(settings.network_gas_usd)) * ngn_usd
        proportional = Decimal(
            settings.fx_spread_bps + settings.liquidity_spread_bps + settings.cowrie_fee_bps
        ) / Decimal(10_000)

        source = (destination_amount * mid + gas_ngn) / (Decimal(1) - proportional)
        return self.quote(source_amount=_money(source))


engine = QuoteEngine()
