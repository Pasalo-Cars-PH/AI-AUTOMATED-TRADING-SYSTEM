"""Real PostgreSQL integration tests for the paper-ledger adapter.

These run against an ephemeral PostgreSQL service in CI, not the production
Supabase project, and do not require production secrets.
"""
import os

import pytest
from sqlalchemy import create_engine, text

from app import paper_ledger


@pytest.fixture
def postgres_ledger(monkeypatch):
    url = os.getenv("PAPER_LEDGER_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PAPER_LEDGER_TEST_DATABASE_URL not configured")

    setup_engine = create_engine(url, future=True)
    with setup_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS titan_private CASCADE"))
        conn.execute(text("CREATE SCHEMA titan_private"))
        conn.execute(text("""
            CREATE TABLE titan_private.paper_ledger_state (
                id SMALLINT PRIMARY KEY CHECK (id = 1),
                trades JSONB NOT NULL DEFAULT '[]'::jsonb,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                CHECK (jsonb_typeof(trades) = 'array')
            )
        """))
        conn.execute(text(
            "INSERT INTO titan_private.paper_ledger_state (id, trades) VALUES (1, '[]'::jsonb)"
        ))

    monkeypatch.setenv("PAPER_LEDGER_BACKEND", "postgres")
    monkeypatch.setenv("PAPER_LEDGER_DATABASE_URL", url)
    # This fixture is only for disposable local CI PostgreSQL, which has no TLS.
    monkeypatch.setenv("PAPER_LEDGER_SSLMODE", "disable")
    monkeypatch.setattr(paper_ledger, "_session_factory", None)
    old_engine = paper_ledger._engine
    monkeypatch.setattr(paper_ledger, "_engine", None)
    yield setup_engine

    if paper_ledger._engine is not None:
        paper_ledger._engine.dispose()
    monkeypatch.setattr(paper_ledger, "_engine", old_engine)
    monkeypatch.setattr(paper_ledger, "_session_factory", None)
    with setup_engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS titan_private CASCADE"))
    setup_engine.dispose()


def test_real_postgres_round_trip_and_commit(postgres_ledger):
    trades = [{"id": 17, "status": "OPEN", "symbol": "XAUUSD"}]
    with paper_ledger.transaction():
        paper_ledger.save_trades(trades)
        assert paper_ledger.load_trades() == trades

    with paper_ledger.transaction():
        assert paper_ledger.load_trades() == trades


def test_real_postgres_transaction_rolls_back(postgres_ledger):
    with pytest.raises(ValueError, match="intentional rollback test"):
        with paper_ledger.transaction():
            paper_ledger.save_trades([{"id": 18, "status": "OPEN"}])
            raise ValueError("intentional rollback test")

    with paper_ledger.transaction():
        assert paper_ledger.load_trades() == []


def test_real_postgres_missing_singleton_fails_closed(postgres_ledger):
    with postgres_ledger.begin() as conn:
        conn.execute(text("DELETE FROM titan_private.paper_ledger_state WHERE id = 1"))

    with pytest.raises(RuntimeError, match="paper_ledger_state_row_missing"):
        with paper_ledger.transaction():
            pass
