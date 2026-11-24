"""
Shared fixtures for integration tests.

Integration tests run the full FastAPI app with stubbed external
dependencies — no real Postgres, no real LLM agent, no real Resend.
We mock the boundaries so the request → handler → response path is
exercised end-to-end while staying network-free in CI.

Skip note
---------
The full FastAPI app pulls in `src.agent.agent`, which transitively
imports langchain + sentence-transformers + pgvector. CI installs only
the lightweight test deps — bringing in the whole prod stack just to
boot the app is a 2-minute pip install we don't want to pay on every PR.
We skip the entire integration module when those deps aren't available;
the unit suite still covers all the pure logic. A dedicated integration
job (with the prod stack installed and a real Postgres container) can
be added later when the value of the extra coverage justifies the cost.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

# Bail out cleanly if the heavyweight stack isn't installed (typical CI).
pytest.importorskip(
    "langchain",
    reason="integration tests require the full prod stack; see conftest docstring",
)
pytest.importorskip("pgvector", reason="pgvector required for ORM imports")


@pytest.fixture(autouse=True)
def _disable_rate_limiter(monkeypatch):
    """The shared SlowAPI limiter caches counters across tests in the
    same process. The limits are read when the routers are imported, so an
    env var set here is too late; switch the limiter off for the test
    instead (restored by monkeypatch)."""
    monkeypatch.setenv("AUTH_LIMIT", "10000/minute")
    from src.middleware.rate_limiter import limiter

    monkeypatch.setattr(limiter, "enabled", False)


SYNTHETIC_PG_URL = os.getenv("MEDICALLM_SYNTHETIC_PG_URL", "")
requires_synthetic_pg = pytest.mark.skipif(
    not SYNTHETIC_PG_URL, reason="MEDICALLM_SYNTHETIC_PG_URL not set"
)


@pytest.fixture
def synthetic_pg():
    """A freshly re-seeded SYNTHETIC PostgreSQL database for one test.

    ``reset_and_seed`` refuses unless ``assert_safe_to_reset`` passes (``_synth``
    name, loopback host, explicit ``MEDICALLM_SYNTHETIC_PG_CONFIRM`` and no
    non-synthetic users/drugs). Every ``get_session()`` in the app is routed
    to this database for the duration of the test and restored afterwards.
    """
    if not SYNTHETIC_PG_URL:
        pytest.skip("MEDICALLM_SYNTHETIC_PG_URL not set")
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from src.db import sql_client

    from .synthetic_data import reset_and_seed

    reset_and_seed(SYNTHETIC_PG_URL)
    engine = create_engine(SYNTHETIC_PG_URL)
    saved = (sql_client._engine, sql_client._SessionLocal)
    sql_client._engine = engine
    sql_client._SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield engine
    finally:
        sql_client._engine, sql_client._SessionLocal = saved
        engine.dispose()


@pytest.fixture
def synthetic_app(synthetic_pg, monkeypatch):
    """TestClient over the real FastAPI app backed by ``synthetic_pg``.

    Only the LLM agent and e-mail delivery are stubbed; auth, routing,
    access control and SQL run for real against the synthetic database.
    """

    async def _noop_init():
        return MagicMock()

    monkeypatch.setattr("src.agent.agent.init_medical_agent", _noop_init)

    async def _noop_send(*args, **kwargs):
        return None

    monkeypatch.setattr("src.auth.email_sender.send_verification_code", _noop_send)

    from fastapi.testclient import TestClient
    from src.main import app

    monkeypatch.setattr(app.state, "medical_agent", MagicMock(), raising=False)
    return TestClient(app)


@pytest.fixture
def app_with_stubs(monkeypatch):
    """
    Returns a TestClient over the real FastAPI app, but with the
    expensive external deps stubbed out:

      * The SQLAlchemy session is a MagicMock — handlers can call .query,
        .add, .commit and they all no-op. Tests that need actual data must
        stub the relevant query result with .return_value.
      * The agent is replaced by a stub that returns a canned response.
      * Email delivery is a no-op.

    Use this fixture for testing routing, validation, and basic shape —
    not for testing data flow that genuinely needs a database.
    """
    fake_session = MagicMock()
    fake_session.execute.return_value.first.return_value = (1,)
    fake_session.query.return_value.filter.return_value.first.return_value = None

    # Patch the session FACTORY, not the `get_session` name: most modules do
    # `from ..db.sql_client import get_session` at import time, so patching
    # the name leaks the fake into whichever modules happen to be imported
    # for the first time inside this fixture (and only those) — and keeps it
    # there for every later test in the process. The real get_session()
    # returns `_SessionLocal()`, so swapping the factory reaches every
    # caller and is restored by monkeypatch.
    from src.db import sql_client

    monkeypatch.setattr(sql_client, "_SessionLocal", lambda: fake_session)

    async def _noop_init():
        return MagicMock()

    monkeypatch.setattr("src.agent.agent.init_medical_agent", _noop_init)

    async def _noop_send(*args, **kwargs):
        return None

    monkeypatch.setattr(
        "src.auth.email_sender.send_verification_code",
        _noop_send,
    )

    from fastapi.testclient import TestClient
    from src.main import app

    # TestClient is not used as a context manager, so the lifespan (which
    # builds the real agent) never runs. Install the stub agent explicitly so
    # /health reflects "agent constructed" as this fixture documents.
    monkeypatch.setattr(app.state, "medical_agent", MagicMock(), raising=False)

    return TestClient(app)
