import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import paper_ledger


@pytest.fixture
def ledger_db(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ledger.db'}", future=True)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE titan_ledger_state (id INTEGER PRIMARY KEY, trades JSON NOT NULL)"))
        conn.execute(text("INSERT INTO titan_ledger_state (id, trades) VALUES (1, '[]')"))
    factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    monkeypatch.setenv("PAPER_LEDGER_BACKEND", "postgres")
    monkeypatch.setenv("PAPER_LEDGER_DATABASE_URL", "postgresql+psycopg://not-used")
    monkeypatch.setattr(paper_ledger, "_engine", engine)
    monkeypatch.setattr(paper_ledger, "_session_factory", factory)
    original_text = paper_ledger.text
    monkeypatch.setattr(paper_ledger, "text", lambda sql: original_text(
        sql.replace("SELECT id FROM titan_private.paper_ledger_state WHERE id = 1 FOR UPDATE",
                    "SELECT id FROM titan_ledger_state WHERE id = 1")
           .replace("SELECT trades FROM titan_private.paper_ledger_state WHERE id = 1",
                    "SELECT trades FROM titan_ledger_state WHERE id = 1")
           .replace("UPDATE titan_private.paper_ledger_state ",
                    "UPDATE titan_ledger_state ")
           .replace("CAST(:trades AS jsonb)", ":trades")
           .replace(", updated_at = now()", "")
    ))
    yield engine
    engine.dispose()


def test_postgres_backend_round_trips_trades(ledger_db):
    trades = [{"id": 1, "status": "OPEN", "symbol": "XAUUSD"}]
    with paper_ledger.transaction():
        paper_ledger.save_trades(trades)
        assert paper_ledger.load_trades() == trades
    with paper_ledger.transaction():
        assert paper_ledger.load_trades() == trades


def test_postgres_backend_fails_closed_without_database_url(monkeypatch):
    monkeypatch.setenv("PAPER_LEDGER_BACKEND", "postgres")
    monkeypatch.delenv("PAPER_LEDGER_DATABASE_URL", raising=False)
    monkeypatch.setattr(paper_ledger, "_session_factory", None)
    monkeypatch.setattr(paper_ledger, "_engine", None)
    with pytest.raises(RuntimeError, match="database_url_not_configured"):
        with paper_ledger.transaction():
            pass


def test_save_rejects_non_json_values(ledger_db):
    with paper_ledger.transaction():
        with pytest.raises(RuntimeError, match="invalid_payload"):
            paper_ledger.save_trades([{"bad": float("nan")}])


def test_unknown_backend_fails_closed(monkeypatch):
    monkeypatch.setenv("PAPER_LEDGER_BACKEND", "redis")
    with pytest.raises(RuntimeError, match="backend_invalid"):
        paper_ledger.is_postgres_backend()
