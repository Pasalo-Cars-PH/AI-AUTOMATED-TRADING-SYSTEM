from app.main import summarize


def test_breakeven_trades_do_not_dilute_win_rate_or_average_loss():
    result = summarize([
        {"r": 2.0, "sl_d": 10.0},
        {"r": -1.0, "sl_d": 10.0},
        {"r": 0.0, "sl_d": 10.0},
    ])

    assert result["total"] == 3
    assert result["wins"] == 1
    assert result["losses"] == 1
    assert result["breakevens"] == 1
    assert result["decisive"] == 2
    assert result["wr"] == 50.0
    assert result["pf"] == 2.0
    assert result["be"] == 33.3
    assert result["net"] == 1.0


def test_all_breakeven_sample_has_no_decisive_win_rate():
    result = summarize([
        {"r": 0.0, "sl_d": 5.0},
        {"r": 0.0, "sl_d": 5.0},
    ])

    assert result["wins"] == 0
    assert result["losses"] == 0
    assert result["breakevens"] == 2
    assert result["decisive"] == 0
    assert result["wr"] == 0
    assert result["pf"] == 0
    assert result["be"] is None
