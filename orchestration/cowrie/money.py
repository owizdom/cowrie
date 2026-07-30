"""Parsing amounts of money out of request input.

Every endpoint that moves value takes its amount as a decimal string, and each
one used to parse it locally. That produced the same defect in several places at
once, so the rule lives here now and is declared once.

The defect worth remembering
----------------------------
`Decimal("NaN")` does not raise. It parses happily, and the exception arrives
later, on the first *comparison*:

    >>> Decimal("NaN") <= 0
    decimal.InvalidOperation

So a guard written as

    try:
        value = Decimal(raw)
    except InvalidOperation:
        raise ValueError("amount must be a number")
    if value <= 0:                      # <- the exception actually happens here
        raise ValueError("amount must be positive")

catches nothing on a NaN input: the try block succeeds and the comparison
outside it raises straight through to a 500. Two routers had exactly that shape
and returned 500 for `{"amount": "NaN"}`; a third happened to put the comparison
inside the try and was fine. The fix is placement, not logic.

`is_finite()` is the right test rather than a string blacklist: it is False for
NaN, sNaN and both infinities, it covers every spelling the constructor accepts
(`nan`, `-NaN`, `snan`, `Infinity`, `1e999`, ...), and unlike a comparison it
does not raise.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from pydantic import AfterValidator

#: The corridor's upper bound, matching the validator this replaces.
MAX_AMOUNT = Decimal("50000000")


def parse_amount(raw: str, *, maximum: Decimal | None = MAX_AMOUNT) -> Decimal:
    """Return `raw` as a positive, finite Decimal, or raise ValueError.

    ValueError rather than HTTPException so this is usable from a Pydantic
    validator, a query parameter and a service alike; each caller renders it as
    the 4xx that suits its surface.
    """
    if raw is None:
        raise ValueError("amount is required")

    try:
        value = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("amount must be a number") from exc

    # Before any comparison - see the module docstring.
    if not value.is_finite():
        raise ValueError("amount must be a finite number")

    if value <= 0:
        raise ValueError("amount must be positive")

    if maximum is not None and value > maximum:
        raise ValueError("amount exceeds the corridor maximum")

    return value


def _validate(raw: str) -> str:
    """Pydantic hook: validate, but keep the field a string.

    The models carry amounts as strings so the exact decimal the caller sent is
    preserved for echoing back; parsing happens where the value is used.
    """
    parse_amount(raw)
    return raw


#: An amount field on a request model. Declares the rule by type rather than
#: restating a validator on every model that happens to take money.
MoneyAmount = Annotated[str, AfterValidator(_validate)]


__all__ = ["MAX_AMOUNT", "MoneyAmount", "parse_amount"]
