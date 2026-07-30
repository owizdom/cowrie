"""The base every request body inherits from.

Why this exists
---------------
PostgreSQL text columns cannot hold a NUL byte. A NUL that reaches psycopg raises
a DataError, which surfaces to the caller as a 500 - a server error for what is
entirely a client mistake.

`middleware/queryguard.py` screens the query string and the path. It deliberately
does not read the request body: consuming the request stream inside a
`BaseHTTPMiddleware` is a well-known way to break downstream body parsing, and a
middleware that had to buffer and replay the stream would be a lot of machinery
for one byte.

Validating at the model layer is both safer and more useful. Pydantic already
walks every field, and its refusal names the offending field, which a
middleware-level 400 cannot do - so the caller is told *what* to fix rather than
just that something was wrong.

Scope
-----
Deliberately narrow: NUL and nothing else. This is not a filter on
suspicious-looking input - guessing at malice is how a guard starts rejecting
real people's names - it removes exactly one byte that has no representation in
the storage layer.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, model_validator

NUL = "\x00"


def _find_nul(value: Any) -> bool:
    """True if a NUL hides anywhere in this value.

    Recurses through containers and nested models so a field added later is
    covered without anyone having to remember this file exists.
    """
    if isinstance(value, str):
        return NUL in value
    if isinstance(value, BaseModel):
        return any(_find_nul(v) for v in value.__dict__.values())
    if isinstance(value, dict):
        return any(_find_nul(k) or _find_nul(v) for k, v in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_find_nul(v) for v in value)
    return False


class RequestModel(BaseModel):
    """Base for request bodies. Refuses a NUL byte in any string field."""

    @model_validator(mode="after")
    def _reject_nul_bytes(self):
        offenders = [name for name, value in self.__dict__.items() if _find_nul(value)]
        if offenders:
            raise ValueError(
                f"{', '.join(sorted(offenders))}: contains a NUL byte, which cannot be stored"
            )
        return self


__all__ = ["RequestModel"]
