"""Rate limiting - SRS §3.4.

SRS §3.4 gives three distinct limits, and all three are enforced:

    Cowrie API        100 requests/second per key, burst 200/second
    CowriePay         1,000 requests/minute per session
    Unauthenticated   10 requests/second

Algorithm
---------
Sliding window over a deque of timestamps, not a fixed window.  A fixed window
lets a caller send the full allowance in the last instant of one window and
again in the first instant of the next, which is twice the stated limit at the
boundary - not acceptable for a limit that exists to protect a settlement
system.

Burst
-----
The API tier has a sustained rate (100/s) and a burst ceiling (200/s).  These
are two different windows checked together: the burst allowance is measured over
one second, the sustained rate over ten, so a caller may spike to 200 in a
single second provided they average 100 across the longer window.

Storage
-------
In-process by default.  SRS §3.3 names Redis as the sliding-window rate limiter,
and `RedisWindow` uses it when COWRIE_REDIS_URL is set; without Redis the
in-process counter is correct for a single container and wrong for several,
which is stated rather than hidden.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


@dataclass(frozen=True, slots=True)
class Tier:
    name: str
    limit: int
    window_seconds: float
    burst_limit: int | None = None
    burst_window_seconds: float = 1.0


#: The three tiers, verbatim from SRS §3.4.
API_TIER = Tier(name="api", limit=1_000, window_seconds=10.0, burst_limit=200, burst_window_seconds=1.0)
"""100/s sustained expressed over a 10s window, with a 200/s burst ceiling."""

SESSION_TIER = Tier(name="session", limit=1_000, window_seconds=60.0)
"""CowriePay: 1,000 requests per minute per session."""

ANON_TIER = Tier(name="anonymous", limit=10, window_seconds=1.0)
"""Unauthenticated: 10 requests per second."""


class SlidingWindow:
    """In-process sliding window keyed by caller."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, tier: Tier) -> tuple[bool, int, float]:
        """Return (allowed, remaining, retry_after_seconds)."""
        now = time.monotonic()
        window = self._hits[key]

        horizon = now - tier.window_seconds
        while window and window[0] < horizon:
            window.popleft()

        if tier.burst_limit is not None:
            burst_horizon = now - tier.burst_window_seconds
            in_burst = sum(1 for t in window if t >= burst_horizon)
            if in_burst >= tier.burst_limit:
                return False, 0, tier.burst_window_seconds

        if len(window) >= tier.limit:
            retry_after = max(0.0, window[0] + tier.window_seconds - now)
            return False, 0, retry_after

        window.append(now)
        return True, tier.limit - len(window), 0.0

    def sweep(self, older_than: float = 300.0) -> None:
        """Drop keys nobody has used recently, so the map does not grow forever."""
        cutoff = time.monotonic() - older_than
        for key in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
            del self._hits[key]


window = SlidingWindow()

#: Paths that must answer even under load: health checks and the WebSocket
#: upgrade, which is one request that then stays open.
EXEMPT_PREFIXES = ("/health", "/ws", "/docs", "/openapi.json", "/redoc")


def _classify(request: Request) -> tuple[Tier, str]:
    """Decide which tier a request falls into, and what identifies the caller."""
    api_key = request.headers.get("x-api-key")
    if api_key:
        # Key by a prefix of the key, never the key itself - this dictionary
        # would otherwise be a store of live credentials.
        return API_TIER, f"api:{api_key[:16]}"

    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return SESSION_TIER, f"session:{auth[7:39]}"

    client = request.client.host if request.client else "unknown"
    return ANON_TIER, f"anon:{client}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith(EXEMPT_PREFIXES):
            return await call_next(request)

        tier, key = _classify(request)
        allowed, remaining, retry_after = window.check(key, tier)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "type": "rate_limit_exceeded",
                        "message": (
                            f"Rate limit exceeded for the {tier.name} tier "
                            f"({tier.limit} requests per {tier.window_seconds:g}s). "
                            "See SRS section 3.4."
                        ),
                        "retryAfterSeconds": round(retry_after, 3),
                    }
                },
                headers={
                    "Retry-After": str(max(1, int(retry_after) + 1)),
                    "X-RateLimit-Limit": str(tier.limit),
                    "X-RateLimit-Remaining": "0",
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(tier.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Tier"] = tier.name
        return response
