"""Durable paper-ledger adapter for Supabase PostgreSQL.

The database backend is opt-in via PAPER_LEDGER_BACKEND=postgres and
PAPER_LEDGER_DATABASE_URL. The URL must remain a server-only secret.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from typing import Iterator, Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

_active_session: ContextVar[Optional[Session]] = ContextVar("paper_ledger_session", default=None)
_engine: Optional[Engine] = None
_session_factory = None


def backend() -> str:
    value = os.getenv("PAPER_LEDGER_BACKEND", "file").strip().lower()
    if value not in {"file", "postgres"}:
        raise RuntimeError("paper_ledger_backend_invalid")
    return value


def is_postgres_backend() -> bool:
    return backend() == "postgres"


def _get_session_factory():
    global _engine, _session_factory
    if _session_factory is not None:
        return _session_factory
    raw_url = os.getenv("PAPER_LEDGER_DATABASE_URL", "").strip()
    if not raw_url:
        raise RuntimeError("paper_ledger_database_url_not_configured")
    if raw_url.startswith("postgres://"):
        raw_url = "postgresql+psycopg://" + raw_url[len("postgres://"):]
    elif raw_url.startswith("postgresql://"):
        raw_url = "postgresql+psycopg://" + raw_url[len("postgresql://"):]
    if not raw_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("paper_ledger_database_url_must_be_postgresql")

    # Secure by default for hosted databases (including Supabase). Allow CI/local
    # PostgreSQL to opt out explicitly without weakening production defaults.
    sslmode = os.getenv("PAPER_LEDGER_SSLMODE", "require").strip().lower()
    if sslmode not in {"require", "verify-ca", "verify-full", "prefer", "allow", "disable"}:
        raise RuntimeError("paper_ledger_sslmode_invalid")

    _engine = create_engine(
        raw_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        pool_timeout=10,
        connect_args={"connect_timeout": 5, "sslmode": sslmode},
    )
    _session_factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _session_factory


@contextmanager
def transaction() -> Iterator[None]:
    """Lock the singleton ledger row for the full read/check/write operation."""
    if not is_postgres_backend():
        yield
        return
    if _active_session.get() is not None:
        # Nested ledger operations reuse the outer transaction and row lock.
        yield
        return
    factory = _get_session_factory()
    session = factory()
    token = None
    try:
        with session.begin():
            row = session.execute(text(
                "SELECT id FROM titan_private.paper_ledger_state WHERE id = 1 FOR UPDATE"
            )).first()
            if row is None:
                raise RuntimeError("paper_ledger_state_row_missing")
            token = _active_session.set(session)
            yield
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"paper_ledger_transaction_failed:{type(exc).__name__}") from exc
    finally:
        if token is not None:
            _active_session.reset(token)
        session.close()


def load_trades():
    if not is_postgres_backend():
        raise RuntimeError("postgres_ledger_backend_not_enabled")
    session = _active_session.get()
    if session is None:
        with transaction():
            return load_trades()
    try:
        value = session.execute(text(
            "SELECT trades FROM titan_private.paper_ledger_state WHERE id = 1"
        )).scalar_one()
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, list):
            raise RuntimeError("paper_ledger_invalid_format:expected_array")
        return value
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"paper_ledger_read_failed:{type(exc).__name__}") from exc


def save_trades(trades) -> None:
    if not is_postgres_backend():
        raise RuntimeError("postgres_ledger_backend_not_enabled")
    if not isinstance(trades, list):
        raise RuntimeError("paper_ledger_invalid_format:expected_array")
    try:
        payload = json.dumps(trades, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"paper_ledger_invalid_payload:{type(exc).__name__}") from exc
    session = _active_session.get()
    if session is None:
        with transaction():
            save_trades(trades)
            return
    try:
        result = session.execute(
            text("UPDATE titan_private.paper_ledger_state "
                 "SET trades = CAST(:trades AS jsonb), updated_at = now() WHERE id = 1"),
            {"trades": payload},
        )
        if result.rowcount != 1:
            raise RuntimeError("paper_ledger_state_row_missing")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"paper_ledger_write_failed:{type(exc).__name__}") from exc
