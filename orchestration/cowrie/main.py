"""Cowrie orchestration tier - application entrypoint.

Wires the routers, the middleware and the background workers, and serves the
OpenAPI 3.0 document that SRS §3.4 promises.

Background workers
------------------
Three loops run for the life of the process:

    quote expiry    Quoted -> Cancelled after the 60 second lock (FR 2.1)
    stuck sweep     in-flight -> Refunding after 10 minutes (NFR 3)
    webhook retry   redeliver failed webhooks on their backoff (FR 4.3)

The stuck sweep is the one that matters most. Each transfer already has its own
driver task that handles its own failures, but a process restart kills those
tasks while the transactions stay in flight in the database. The sweep runs
independently of any driver, so a transfer orphaned by a restart is still
refunded - which is what NFR 3 actually promises.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .adapters.chain import get_chain
from .config import settings
from .db import init_db, session_scope
from .middleware import RateLimitMiddleware, TimingMiddleware, performance
from .routers import admin, auth, demo, kyc, partner, regulator, support, transfers, transparency, ws
from .services import transfer_service, webhooks
from .services.sanctions import service as sanctions_service

DESCRIPTION = """
The orchestration tier behind all six Cowrie surfaces.

**Cowrie** settles cross-border payments between African currencies in seconds,
using **cUSDC** - a USD-pegged stablecoin - as the neutral bridge between local
on-ramps and off-ramps. The launch corridor is **Nigeria to Kenya (NGN to KES)**.

### This is a prototype
No real money moves. Mono, Safaricom Daraja, Smile ID and the reserve banking
partner are simulated, and the contracts run on a local chain rather than Base
mainnet. See `GET /transparency` for the full disclosure. This is the position
SRS §2.5 constraint 2 sets out.

### Surfaces
| Prefix | Surface | Audience |
|---|---|---|
| `/auth`, `/quotes`, `/transfers`, `/kyc`, `/support` | CowriePay | Individuals |
| `/v1` | Cowrie API | Banks, fintechs, SMEs |
| `/admin` | Admin console | Cowrie compliance and ops |
| `/regulator` | Regulator portal | SEC Nigeria, CMA Kenya, CBN |
| `/transparency` | Public transparency page | Anyone |
| `/ws` | WebSocket status push | CowriePay, admin |
"""


async def _loop(name: str, interval: float, work) -> None:
    """Run `work` forever, surviving its failures.

    A background loop that dies on one bad iteration takes a requirement with
    it, so failures are logged and the loop continues.
    """
    while True:
        try:
            await asyncio.sleep(interval)
            await work()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - see docstring
            print(f"[worker:{name}] iteration failed: {exc}")


async def _expire_quotes() -> None:
    with session_scope() as db:
        count = await transfer_service.expire_quotes(db)
        if count:
            print(f"[worker:quotes] cancelled {count} expired quote(s)")


async def _sweep_stuck() -> None:
    with session_scope() as db:
        count = await transfer_service.sweep_stuck(db)
        if count:
            print(f"[worker:sweep] auto-refunded {count} stuck transfer(s) (NFR 3)")


async def _retry_webhooks() -> None:
    sent = await webhooks.retry_pending()
    if sent:
        print(f"[worker:webhooks] retried {sent} delivery attempt(s)")


async def _daily_sanctions() -> None:
    """FR 1.3 - "refresh daily".

    Runs hourly rather than daily so the demo can show it happening, and is
    idempotent, so the extra runs cost nothing but a re-screen.
    """
    with session_scope() as db:
        result = sanctions_service.daily_refresh(db)
        db.commit()
        if result["newlyFlagged"]:
            print(f"[worker:sanctions] froze {len(result['newlyFlagged'])} newly matched user(s)")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()

    if settings.seed_on_startup:
        from .seed import seed_if_empty

        seed_if_empty()

    chain = get_chain()
    health = await chain.health()
    print(f"[cowrie] {settings.app_name} {settings.version}")
    print(f"[cowrie] database: {'sqlite' if settings.is_sqlite else 'postgresql'}")
    print(f"[cowrie] chain: {health['mode']} - {health['network']}")

    from .services.cache import cache

    print(f"[cowrie] cache: {cache.backend}")
    print(f"[cowrie] corridor: {settings.corridor_source} -> {settings.corridor_destination}")

    tasks = [
        asyncio.create_task(_loop("quotes", 10, _expire_quotes)),
        asyncio.create_task(_loop("sweep", 15, _sweep_stuck)),
        asyncio.create_task(_loop("webhooks", 30, _retry_webhooks)),
        asyncio.create_task(_loop("sanctions", 3_600, _daily_sanctions)),
    ]

    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(
    title="Cowrie API",
    version=settings.version,
    description=DESCRIPTION,
    lifespan=lifespan,
    openapi_tags=[
        {"name": "auth", "description": "Registration (FR 1.1), sign-in, sessions"},
        {"name": "cowriepay", "description": "Consumer transfers (FR 2.1 - FR 2.4)"},
        {"name": "kyc", "description": "Identity verification (FR 1.2) and account linking"},
        {"name": "support", "description": "Support tickets and the in-app help centre"},
        {"name": "cowrie-api", "description": "Institutional API (FR 4.1 - FR 4.3)"},
        {"name": "admin", "description": "Admin and compliance console (FR 5.1 - FR 5.3)"},
        {"name": "regulator", "description": "Read-only regulator portal and signed exports"},
        {"name": "transparency", "description": "Public cUSDC supply and reserve disclosure"},
        {"name": "websocket", "description": "Live transaction status push (SRS §3.4)"},
        {"name": "demo", "description": "Scenario controls that exercise the state machine"},
    ],
)

# Order matters: timing wraps rate limiting, so a 429 is still measured.
app.add_middleware(TimingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id", "X-RateLimit-Remaining", "X-RateLimit-Limit", "Server-Timing"],
)

# SRS 2.4 - OpenTelemetry. Must run before the routers are exercised.
from . import telemetry  # noqa: E402

print(f"[cowrie] telemetry: {telemetry.setup(app)}")

app.include_router(auth.router)
app.include_router(transfers.router)
app.include_router(kyc.router)
app.include_router(support.router)
app.include_router(partner.router)
app.include_router(admin.router)
app.include_router(regulator.router)
app.include_router(transparency.router)
app.include_router(ws.router)

# Demo controls are mounted only in the demo environment. This build is always
# 'demo', but the gate is here so that changing one environment variable removes
# the scenario switch rather than leaving it reachable in a real deployment.
if settings.environment == "demo":
    app.include_router(demo.router)


@app.get("/", tags=["meta"])
def root() -> dict:
    return {
        "service": settings.app_name,
        "version": settings.version,
        "product": "Cowrie - a cross-border payment network for Africa",
        "corridor": f"{settings.corridor_source} -> {settings.corridor_destination}",
        "environment": settings.environment,
        "documentation": {"openapi": "/openapi.json", "swagger": "/docs", "redoc": "/redoc"},
        "surfaces": {
            "cowriepay": "/auth, /quotes, /transfers, /kyc, /support",
            "cowrieApi": "/v1",
            "admin": "/admin",
            "regulator": "/regulator",
            "transparency": "/transparency",
            "websocket": "/ws/transfers, /ws/admin, /ws/public",
        },
        "disclosure": "Prototype with seeded demonstration data. See GET /transparency.",
    }


@app.get("/health", tags=["meta"])
async def health() -> dict:
    """Liveness and dependency check."""
    chain = get_chain()
    try:
        chain_health = await chain.health()
        chain_ok = True
    except Exception as exc:  # pragma: no cover - environment dependent
        chain_health = {"error": str(exc)}
        chain_ok = False

    db_ok = True
    try:
        from sqlalchemy import text

        with session_scope() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    healthy = chain_ok and db_ok
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={
            "status": "ok" if healthy else "degraded",
            "version": settings.version,
            "database": {"ok": db_ok, "engine": "sqlite" if settings.is_sqlite else "postgresql"},
            "chain": {"ok": chain_ok, **chain_health},
        },
    )


@app.get("/health/performance", tags=["meta"])
def health_performance() -> dict:
    """NFR 1 budgets, measured over recent requests."""
    return performance.summary()


@app.get("/requirements", tags=["meta"])
def requirements() -> dict:
    """The requirement map, served by the running system.

    Points at docs/TRACEABILITY.md, which is the full matrix. This endpoint
    exists so the mapping is reachable from the deployed instance rather than
    only from the repository.
    """
    return {
        "srs": "Cowrie SRS v1.0 - NGN to KES launch corridor",
        "functionalRequirements": {
            "FR 1": "User onboarding & KYC - /auth, /kyc",
            "FR 2": "Send money (CowriePay) - /quotes, /transfers",
            "FR 3": "Settlement layer & cUSDC - adapters/chain.py, cusdc/",
            "FR 4": "Cowrie API (institutional) - /v1",
            "FR 5": "Admin & compliance console - /admin, /regulator",
        },
        "nonFunctionalRequirements": {
            "NFR 1": "Performance - GET /health/performance, GET /admin/performance",
            "NFR 2": "Security - 3-of-5 treasury gate; no HSM in this build",
            "NFR 3": "Reliability - every transfer settles or refunds; see GET /demo/state-machine",
            "NFR 4": "Compliance - OFAC/UN/EU screening on every transfer",
            "NFR 5": "Auditability - GET /admin/audit/verify",
            "NFR 6": "Usability - four itemised fees, never bundled",
            "NFR 7": "Accessibility - WCAG 2.1 AA in the surfaces layer",
        },
        "umlDiagrams": {
            "useCase": "22 use cases, 9 actors",
            "class": "12 classes - orchestration/cowrie/models.py",
            "sequence": "24 messages - orchestration/cowrie/services/transfer_service.py",
            "deployment": "docs/uml/cowrie_deployment.puml",
            "stateMachine": "11 states - GET /demo/state-machine",
        },
        "fullMatrix": "docs/TRACEABILITY.md",
    }
