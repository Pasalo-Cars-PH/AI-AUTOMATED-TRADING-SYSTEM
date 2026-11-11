from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import pytest
import executor.mt5_executor as ex

def deal(ticket, pnl, entry=1, stamp=None):
    stamp = stamp or int(datetime.now(timezone.utc).timestamp())
    return SimpleNamespace(ticket=ticket, entry=entry, time=stamp, profit=pnl,
                           commission=0.0, swap=0.0, fee=0.0)

def fake_mt5(deals, equity):
    return SimpleNamespace(
        DEAL_ENTRY_OUT=1, DEAL_ENTRY_OUT_BY=3, DEAL_ENTRY_INOUT=2,
        history_deals_get=lambda start, end: deals,
        account_info=lambda: SimpleNamespace(equity=equity),
        last_error=lambda: (0, "ok"),
    )

def test_two_percent_daily_loss_cap():
    now = datetime.now(timezone.utc); stamp = int(now.timestamp())
    with patch.object(ex, "mt5", fake_mt5([deal(1, -20, stamp=stamp)], 980)):
        r = ex.history_risk(now)
    assert r["start_equity_estimate"] == 1000
    assert r["daily_loss_pct"] == 2.0
    assert r["daily_loss_locked"] is True

def test_four_consecutive_closing_losses_lock():
    now = datetime.now(timezone.utc); stamp = int(now.timestamp())
    ds = [deal(i, -1, stamp=stamp - (5-i)) for i in range(1, 5)]
    with patch.object(ex, "mt5", fake_mt5(ds, 996)):
        r = ex.history_risk(now)
    assert r["consecutive_losses"] == 4
    assert r["loss_streak_locked"] is True

def test_win_breaks_loss_streak():
    now = datetime.now(timezone.utc); stamp = int(now.timestamp())
    ds = [deal(1, -1, stamp=stamp-20), deal(2, -1, stamp=stamp-10), deal(3, 2, stamp=stamp)]
    with patch.object(ex, "mt5", fake_mt5(ds, 1000)):
        r = ex.history_risk(now)
    assert r["consecutive_losses"] == 0
    assert r["loss_streak_locked"] is False

def test_history_failure_fails_closed():
    fake = fake_mt5([], 1000)
    fake.history_deals_get = lambda start, end: None
    with patch.object(ex, "mt5", fake):
        with pytest.raises(ex.ExecutorError, match="HISTORY_UNAVAILABLE"):
            ex.history_risk(datetime.now(timezone.utc))

def test_entry_deal_not_counted():
    now = datetime.now(timezone.utc); stamp = int(now.timestamp())
    ds = [deal(1, -99, entry=0, stamp=stamp-10), deal(2, -1, entry=1, stamp=stamp)]
    with patch.object(ex, "mt5", fake_mt5(ds, 999)):
        r = ex.history_risk(now)
    assert r["closing_deals"] == 1
    assert r["daily_net_pnl"] == -1
    assert r["consecutive_losses"] == 1
