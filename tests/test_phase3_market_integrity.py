import time
from app.market.models import Candle
from app.market.service import MarketDataService


def candle(ts, *, o=2000, h=2002, low=1999, close=2001, symbol="XAUUSD"):
    return Candle(timestamp=ts, open=o, high=h, low=low, close=close, volume=1,
                  symbol=symbol, provider_symbol="XAU/USD", timeframe="M5",
                  source="twelvedata", provider="twelvedata")


def test_validation_sorts_deduplicates_and_marks_closed():
    now = 1_800_000_000
    data = [candle(now - 600), candle(now - 300), candle(now - 600, close=2000.5)]
    result = MarketDataService._validate_candles(data, "M5", now=now)
    assert [x.timestamp for x in result] == [now - 600, now - 300]
    assert all(x.is_closed for x in result)


def test_validation_rejects_open_and_stale_bars():
    now = 1_800_000_000
    open_bar = candle(now - 120)
    stale_bar = candle(now - 1800)
    assert MarketDataService._validate_candles([open_bar], "M5", now=now) == []
    assert MarketDataService._validate_candles([stale_bar], "M5", now=now) == []


def test_validation_rejects_corrupt_and_nonfinite_ohlc():
    now = 1_800_000_000
    corrupt = candle(now - 600, o=2000, h=1990, low=1995, close=2001)
    nonfinite = candle(now - 300, close=float("nan"))
    assert MarketDataService._validate_candles([corrupt, nonfinite], "M5", now=now) == []


def test_symbol_routing_is_explicit_and_no_proxy_symbols():
    svc = MarketDataService()
    provider, symbol = svc._get_provider_for_symbol("XAUUSD")
    assert provider is svc.twelvedata and symbol == "XAUUSD"
    provider, symbol = svc._get_provider_for_symbol("BTCUSD")
    assert provider is svc.binance and symbol == "BTCUSD"
    for unsupported in ("PAXGUSDT", "EURUSDT", "YF_XAUUSD"):
        try:
            svc._get_provider_for_symbol(unsupported)
        except ValueError:
            pass
        else:
            raise AssertionError(f"proxy/unsupported symbol accepted: {unsupported}")


def test_timeframe_is_not_silently_defaulted():
    try:
        MarketDataService._interval_seconds("M2")
    except ValueError:
        pass
    else:
        raise AssertionError("unsupported timeframe accepted")
