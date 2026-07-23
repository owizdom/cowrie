"""Request timing and span logging - NFR 1, and the observability line in SRS §2.4.

NFR 1 states two API budgets:

    reads   < 500 ms
    writes  < 2 s

A requirement with a number in it should be measured, not asserted.  This
middleware times every request, tags it against the applicable budget, and keeps
a rolling window of recent samples that `/health/performance` exposes and the
admin console renders.  A request that breaches its budget is logged as a
breach, so the claim can be checked rather than believed.

On OpenTelemetry
----------------
SRS §2.4 names OpenTelemetry for observability.  What is emitted here is a
structured span per request with the fields an OTel exporter would carry
(trace id, route, method, status, duration).  The exporter itself is not wired,
because a local demo has no collector to send to; adding one is a dependency and
a few lines in `main.py`, not a redesign.  The traceability matrix records this
as a partial rather than a tick.
"""

from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

#: NFR 1 budgets, in milliseconds.
READ_BUDGET_MS = 500
WRITE_BUDGET_MS = 2_000

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(slots=True)
class Sample:
    route: str
    method: str
    status: int
    duration_ms: float
    budget_ms: int
    within_budget: bool
    trace_id: str


class PerformanceLog:
    """A bounded rolling window of recent requests.

    Bounded because an unbounded list in a long-running process is a leak; 2,000
    samples is enough to compute a stable p95 and small enough to ignore.
    """

    def __init__(self, capacity: int = 2_000) -> None:
        self._samples: deque[Sample] = deque(maxlen=capacity)

    def add(self, sample: Sample) -> None:
        self._samples.append(sample)

    def summary(self) -> dict:
        samples = list(self._samples)
        if not samples:
            return {
                "requests": 0,
                "readBudgetMs": READ_BUDGET_MS,
                "writeBudgetMs": WRITE_BUDGET_MS,
                "note": "No requests recorded yet.",
            }

        reads = [s for s in samples if s.budget_ms == READ_BUDGET_MS]
        writes = [s for s in samples if s.budget_ms == WRITE_BUDGET_MS]
        breaches = [s for s in samples if not s.within_budget]

        return {
            "requests": len(samples),
            "readBudgetMs": READ_BUDGET_MS,
            "writeBudgetMs": WRITE_BUDGET_MS,
            "reads": _stats(reads),
            "writes": _stats(writes),
            "budgetBreaches": len(breaches),
            "withinBudgetPercent": round((1 - len(breaches) / len(samples)) * 100, 2),
            "slowest": [
                {
                    "route": s.route,
                    "method": s.method,
                    "durationMs": round(s.duration_ms, 1),
                    "budgetMs": s.budget_ms,
                }
                for s in sorted(samples, key=lambda s: s.duration_ms, reverse=True)[:5]
            ],
        }


def _stats(samples: list[Sample]) -> dict:
    if not samples:
        return {"count": 0}
    durations = sorted(s.duration_ms for s in samples)
    return {
        "count": len(durations),
        "medianMs": round(durations[len(durations) // 2], 1),
        "p95Ms": round(durations[min(len(durations) - 1, int(len(durations) * 0.95))], 1),
        "maxMs": round(durations[-1], 1),
    }


performance = PerformanceLog()


class TimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()

        response = await call_next(request)

        duration_ms = (time.perf_counter() - started) * 1_000
        budget = WRITE_BUDGET_MS if request.method in WRITE_METHODS else READ_BUDGET_MS

        # Route template rather than the concrete path, so /transfers/{id}
        # aggregates instead of producing one bucket per transfer.
        route = request.scope.get("route")
        route_name = getattr(route, "path", request.url.path)

        sample = Sample(
            route=route_name,
            method=request.method,
            status=response.status_code,
            duration_ms=duration_ms,
            budget_ms=budget,
            within_budget=duration_ms <= budget,
            trace_id=trace_id,
        )
        performance.add(sample)

        if not sample.within_budget:
            print(
                f"[nfr1] budget breach {request.method} {route_name} "
                f"{duration_ms:.0f}ms > {budget}ms trace={trace_id}"
            )

        response.headers["X-Trace-Id"] = trace_id
        response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"
        return response
