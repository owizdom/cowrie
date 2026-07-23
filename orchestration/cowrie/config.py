"""Runtime configuration.

Everything here has a working default so that `uvicorn cowrie.main:app` runs
with no .env file at all.  Nothing in this file points at a production system:
the default database is a local SQLite file, the default chain is the in-process
simulator, and every partner adapter is a simulation.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path(".env")),
        env_prefix="COWRIE_",
        extra="ignore",
    )

    # ---- service ---------------------------------------------------------
    app_name: str = "Cowrie Orchestration Tier"
    version: str = "1.0.0"
    environment: str = "demo"
    """Always 'demo' in this build.  There is no production environment."""

    # ---- datastores ------------------------------------------------------
    database_url: str = f"sqlite:///{REPO_ROOT / 'cowrie-demo.db'}"
    """SQLite by default so the project runs with zero infrastructure.
    docker-compose.yml sets this to the PostgreSQL 15 URL named in SRS 2.4."""

    redis_url: str = ""
    """Empty means 'use the in-process fallback'.  Redis is a cache, a rate
    limiter and a job queue here (SRS 3.3); none of those need to be durable for
    a demo, so its absence degrades rather than breaks."""

    # ---- security --------------------------------------------------------
    jwt_secret: str = "cowrie-demo-secret-not-for-production"
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 720

    # ---- corridor --------------------------------------------------------
    corridor_source: str = "NGN"
    corridor_destination: str = "KES"

    quote_lock_seconds: int = 60
    """FR 2.1 - "The quote is locked for 60 seconds"."""

    required_confirmations: int = 12
    """FR 3.3 - "at least 12 block confirmations on Base"."""

    base_block_seconds: float = 2.0
    """Base L2 block time (SRS hypothesis: "~2-second blocks").
    12 x 2s = ~24s, which is the figure FR 3.3 quotes."""

    stuck_cancel_seconds: int = 300
    """FR 2.4 - cancel button appears after 5 minutes pending."""

    stuck_refund_seconds: int = 600
    """FR 2.4 / NFR 3 - automatic refund after 10 minutes."""

    # ---- pricing (FR 2.1 / NFR 6) ----------------------------------------
    mid_market_ngn_per_usd: float = 1_530.00
    mid_market_kes_per_usd: float = 129.50
    fx_spread_bps: int = 35
    """0.35% of principal."""
    liquidity_spread_bps: int = 15
    """0.15% of principal."""
    cowrie_fee_bps: int = 40
    """0.40% of principal.  35 + 15 + 40 = 90bps = 0.90%, under the sub-1%
    all-in target in the SRS hypothesis, before network gas."""
    network_gas_usd: float = 0.004
    """Base L2 gas for the bridge call; "less than a cent" per the glossary."""

    # ---- limits (FR 1.2: limits scale with verification level) -----------
    tier_limits_usd: dict[str, float] = {
        "NONE": 0.0,
        "TIER1": 200.0,
        "TIER2": 2_000.0,
        "TIER3": 20_000.0,
    }

    # ---- chain -----------------------------------------------------------
    chain_mode: str = "simulated"
    """'simulated' | 'anvil'.

    'simulated' runs an in-process model of Base: deterministic transaction
    hashes, a block counter advancing at base_block_seconds, and confirmation
    counting.  Nothing leaves the machine.

    'anvil' deploys cusdc/ (the real Solidity contracts) to a local Anvil node
    and issues real transactions against it.  Still entirely local; Base mainnet
    is never contacted.  See README "Running against a local chain"."""

    anvil_rpc_url: str = "http://127.0.0.1:8545"
    chain_id: int = 8453
    """Base mainnet chain id, used as a label only in simulated mode."""

    # Addresses shown in the UI.  These are the addresses recorded in SRS 2.4;
    # in this build they are labels on simulated records, not live contracts.
    cusdc_address: str = "0x46C85152bFe9f96829aA94755D9f915F9B10EF5F"
    cngn_address: str = "0xe2387F04d3858e7Cb64Ef5Ed6617f9B2fcEEAfa2"
    bridge_address: str = "0x9A6f3C1B0e5D2A874fE13b09C7D4a5E86F2B0c31"

    # ---- demo ------------------------------------------------------------
    demo_speed: float = 1.0
    """Divides every simulated wall-clock delay.  1.0 = real timings, so a
    happy-path transfer takes ~30s and demonstrates NFR 1 honestly.  The test
    suite raises this so the suite does not take minutes."""

    seed_on_startup: bool = True

    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
    ]
    cors_origin_regex: str = r"https://.*\.vercel\.app|https://.*\.onrender\.com"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def sqlalchemy_url(self) -> str:
        """Normalise the URL a managed host hands out.

        Render (and Heroku, and most managed Postgres) provide
        `postgres://...`, which SQLAlchemy 2 no longer recognises, and which
        would otherwise pick psycopg2 rather than the psycopg3 driver this
        project depends on. Rewriting it here means the deployment needs no
        special-cased environment variable.
        """
        url = self.database_url
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url

    def scaled(self, seconds: float) -> float:
        """Apply the demo speed multiplier to a wall-clock delay."""
        return seconds / max(self.demo_speed, 0.001)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
