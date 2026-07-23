"""Database engine and session handling.

Supports both datastores named in SRS 2.4:

    PostgreSQL 15   the SRS target, used by docker-compose and by the deployed
                    demo instance.
    SQLite          the zero-infrastructure default, so `uv run uvicorn ...`
                    works on a clean machine with nothing installed.

The models are written against portable SQLAlchemy types, so the same schema
runs on both.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .models import Base


def _build_engine() -> Engine:
    if settings.is_sqlite:
        eng = create_engine(
            settings.sqlalchemy_url,
            connect_args={"check_same_thread": False},
            future=True,
        )

        @event.listens_for(eng, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - driver hook
            cur = dbapi_conn.cursor()
            # Foreign keys are off by default in SQLite; the composition
            # relationships in models.py depend on them.
            cur.execute("PRAGMA foreign_keys=ON")
            # WAL keeps the background state-machine worker from blocking reads
            # while it writes transitions.
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()

        return eng

    return create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        future=True,
    )


engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_db() -> None:
    """Create the schema.

    A demo build has no migration history worth keeping, so the schema is
    created directly from the models rather than through Alembic.
    """
    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped session."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def session_scope() -> Session:
    """A standalone session for background workers and scripts.

    Callers are responsible for commit/close; use as a context manager.
    """
    return SessionLocal()
