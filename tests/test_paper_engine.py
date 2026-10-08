import pytest

from app.paper_engine import evaluate_position_on_candle, realized_r


def trade(side="BUY"):
    return {"status": "OPEN", "type": side, "entry": 100.0, "sl": 98.0, "tp": 104.0}


def test_buy_tp_hit():
    assert evaluate_position_on_candle(trade("BUY"), {"high": 104.1, "low": 99.0}) == {
        "result": "WIN", "exit_price": 104.0, "reason": "TP_HIT"
    }


def test_buy_sl_hit():
    assert evaluate_position_on_candle(trade("BUY"), {"high": 101.0, "low": 97.9}) == {
        "result": "LOSS", "exit_price": 98.0, "reason": "SL_HIT"
    }


def test_sell_tp_hit():
    assert evaluate_position_on_candle(trade("SELL"), {"high": 101.0, "low": 95.9}) == {
        "result": "WIN", "exit_price": 96.0, "reason": "TP_HIT"
    }


def test_same_candle_sl_and_tp_is_conservative_loss():
    assert evaluate_position_on_candle(trade("BUY"), {"high": 105.0, "low": 97.0})["result"] == "LOSS"


def test_realized_r_uses_actual_exit():
    assert realized_r(trade("BUY"), 102.0) == pytest.approx(1.0)
    assert realized_r(trade("SELL"), 102.0) == pytest.approx(-1.0)


def test_closed_trade_is_ignored():
    t = trade("BUY")
    t["status"] = "CLOSED"
    assert evaluate_position_on_candle(t, {"high": 105.0, "low": 97.0}) is None
