"""Reject query strings the database cannot store.

PostgreSQL text columns cannot hold a NUL byte, so a query parameter carrying
one reaches psycopg and raises a DataError that surfaces as a 500. That was
observable: `GET /admin/audit?entityType=%00` answered 500.

Two reasons this is middleware rather than a validator on the one parameter that
was found:

  * There is nothing special about `entityType`. Every string query parameter in
    the service is a candidate, so fixing them one at a time leaves the next one
    waiting to be discovered.

  * It is a client error, not a server one. A caller who sends a byte the storage
    layer cannot represent should be told so with a 4xx, rather than handed a 500
    that reads like the service broke.

Deliberately narrow: it refuses NUL and nothing else. This is not a filter on
suspicious-looking input - guessing at malice is how a guard starts rejecting
legitimate names - it removes exactly one byte that has no valid representation
downstream.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class QueryGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # The raw query string and path are checked rather than the parsed
        # values, so a NUL is caught however it was encoded and whichever
        # parameter carries it. The path matters too: an id in the URL becomes a
        # query parameter against the database just as surely as `?id=` does.
        suspect = f"{request.url.path}?{request.url.query}"
        if "\x00" in suspect or "%00" in suspect.lower():
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "type": "invalid_request",
                        "message": (
                            "The request URL contains a NUL byte, which cannot be stored. "
                            "Remove it and retry."
                        ),
                    }
                },
            )

        return await call_next(request)
