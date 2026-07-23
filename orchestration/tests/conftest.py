"""Test fixtures.

Every test runs against a fresh in-memory-ish SQLite database and the simulated
chain, with the demo speed multiplier raised so a suite that exercises a
30-second settlement does not take 30 seconds per test.

The multiplier only scales the simulated wall-clock delays in the adapters. It
does not change any threshold under test: the quote lock is still 60 seconds of
model time, the confirmation requirement is still 12, and the refund guarantee
is still 10 minutes. Compressing the clock rather than loosening the rules is
what keeps these tests meaningful.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Configure before any cowrie module is imported - settings are read at import.
_TMP = Path(tempfile.mkdtemp(prefix="cowrie-test-"))
os.environ["COWRIE_DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["COWRIE_DEMO_SPEED"] = "40"
os.environ["COWRIE_BASE_BLOCK_SECONDS"] = "0.05"
os.environ["COWRIE_SEED_ON_STARTUP"] = "false"
os.environ["COWRIE_CHAIN_MODE"] = "simulated"
os.environ["COWRIE_JWT_SECRET"] = "test-secret"

from cowrie.config import settings  # noqa: E402
from cowrie.db import SessionLocal, engine, init_db  # noqa: E402
from cowrie.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    """A fresh schema per test, so ordering never matters."""
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def user(db):
    """A verified sender with a fundable balance."""
    from decimal import Decimal

    from cowrie.enums import KycLevel
    from cowrie.models import User
    from cowrie.security import hash_secret

    account = User(
        fullName="Test Sender",
        phone="+2348000000001",
        email="sender@example.com",
        country="NG",
        kycLevel=KycLevel.TIER3,
        ngnBalance=Decimal("5000000.00"),
    )
    account._pinHash = hash_secret("123456")
    db.add(account)
    db.commit()
    return account


@pytest.fixture
def admin(db):
    from cowrie.enums import AdminRole
    from cowrie.models import AdminUser
    from cowrie.security import hash_secret

    account = AdminUser(email="admin@example.com", fullName="Test Admin", role=AdminRole.ADMIN)
    account._passwordHash = hash_secret("password")
    db.add(account)
    db.commit()
    return account


@pytest.fixture
def client():
    """A TestClient with the app's lifespan (and its background workers) active."""
    from fastapi.testclient import TestClient

    from cowrie.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def chain():
    from cowrie.adapters.chain import get_chain, reset_chain

    reset_chain()
    yield get_chain()
    reset_chain()


@pytest.fixture
def app_settings():
    return settings
