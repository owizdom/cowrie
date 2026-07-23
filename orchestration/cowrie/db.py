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
    """Create the schema, then reconcile columns added since it was created."""
    Base.metadata.create_all(bind=engine)
    _sync_columns()


def _sync_columns() -> None:
    """Add columns the models declare but the live tables lack.

    `create_all` creates missing *tables* and silently ignores existing ones, so
    a column added to a model after the first deployment never reaches the
    database and every insert fails with UndefinedColumn. That is exactly what
    happened when the 90-day expiry was added to ApiKey.

    This is deliberately narrow: it only ever ADDs nullable columns. It will not
    drop, rename or retype anything, because those need a decision about
    existing rows that no automatic step should make on its own. A project that
    outgrows this wants Alembic; this keeps a single-service deployment honest
    without pretending to be a migration tool.
    """
    from sqlalchemy import inspect, text
    from sqlalchemy.schema import CreateColumn

    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue

            present = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                if not column.nullable and column.default is None and column.server_default is None:
                    print(
                        f"[schema] {table.name}.{column.name} is NOT NULL without a default; "
                        "add it by hand"
                    )
                    continue

                ddl = CreateColumn(column).compile(engine).string
                # A new column has to be nullable for existing rows to remain
                # valid; the model default applies to rows written from now on.
                ddl = ddl.replace(" NOT NULL", "")
                connection.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN {ddl}'))
                print(f"[schema] added {table.name}.{column.name}")


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
