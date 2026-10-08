import app.main as main


def test_manager_closes_on_real_tp(monkeypatch):
    trades = [{
        "id": 1, "status": "OPEN", "type": "BUY",
        "entry": 100.0, "sl": 98.0, "tp": 104.0
    }]
    saved = []

    monkeypatch.setattr(main, "load_trades", lambda: trades)
    monkeypatch.setattr(main, "save_trades", lambda value: saved.append(value))
    monkeypatch.setattr(main, "fetch_m5_live", lambda n=900: [
        {"datetime": "2026-10-09 04:40:00", "open": 100.5, "high": 104.2, "low": 100.0, "close": 103.8}
    ])
    monkeypatch.setattr(main, "MASTER_LIVE_ENABLE", False)
    monkeypatch.setattr(main, "PAPER_SCAN_PAUSED", False)

    result = main.manage_open_paper_trades()

    assert result["closed"] == 1
    assert trades[0]["result"] == "WIN"
    assert trades[0]["close_reason"] == "TP_HIT"
    assert trades[0]["exit_price"] == 104.0
    assert trades[0]["r"] == 2.0
    assert saved


def test_manager_does_not_change_state_on_no_data(monkeypatch):
    trades = [{
        "id": 1, "status": "OPEN", "type": "BUY",
        "entry": 100.0, "sl": 98.0, "tp": 104.0
    }]
    monkeypatch.setattr(main, "load_trades", lambda: trades)
    monkeypatch.setattr(main, "fetch_m5_live", lambda n=900: None)

    result = main.manage_open_paper_trades()

    assert result["status"] == "no_data"
    assert result["closed"] == 0
    assert trades[0]["status"] == "OPEN"


def test_manager_uses_conservative_sl_when_both_hit(monkeypatch):
    trades = [{
        "id": 1, "status": "OPEN", "type": "BUY",
        "entry": 100.0, "sl": 98.0, "tp": 104.0
    }]
    monkeypatch.setattr(main, "load_trades", lambda: trades)
    monkeypatch.setattr(main, "save_trades", lambda value: None)
    monkeypatch.setattr(main, "fetch_m5_live", lambda n=900: [
        {"datetime": "2026-10-09 04:40:00", "open": 100.5, "high": 105.0, "low": 97.0, "close": 103.0}
    ])
    monkeypatch.setattr(main, "MASTER_LIVE_ENABLE", False)
    monkeypatch.setattr(main, "PAPER_SCAN_PAUSED", False)

    result = main.manage_open_paper_trades()

    assert result["trades"][0]["reason"] == "SL_HIT"
    assert result["trades"][0]["result"] == "LOSS"
    assert result["trades"][0]["r"] == -1.0
