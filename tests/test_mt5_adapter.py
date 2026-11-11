from types import SimpleNamespace as N
import pytest
import broker.mt5_adapter as ad
from broker.mt5_adapter import MT5Adapter, MT5AdapterError


class Mock:
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_IOC = 1

    def __init__(self, positions=None, **spec):
        self._positions = positions or []
        self._spec = dict(
            name="XAUUSD", visible=True, trade_contract_size=100,
            volume_min=0.01, volume_step=0.01, volume_max=100,
            digits=2, trade_stops_level=20, trade_tick_size=0.01,
            trade_tick_value=1.0, point=0.01,
            currency_profit="USD", currency_margin="USD")
        self._spec.update(spec)
        self.sent = []

    def symbol_info(self, s):
        return N(**self._spec)

    def symbol_select(self, *a):
        return True

    def symbol_info_tick(self, s):
        return N(ask=2000.0, bid=1999.98)

    def positions_get(self, **kw):
        return self._positions

    def last_error(self):
        return (0, "ok")

    def order_send(self, r):
        self.sent.append(r)
        return N(retcode=10009)


@pytest.fixture
def make(monkeypatch):
    def _make(**kw):
        for k in ("MT5_CONTRACT_SIZE", "MT5_MIN_VOLUME", "MT5_VOLUME_STEP"):
            monkeypatch.delenv(k, raising=False)
        m = Mock(**kw)
        monkeypatch.setattr(ad, "mt5", m)
        return MT5Adapter(), m
    return _make


def order(a, **kw):
    args = dict(signal_id="t1", side="BUY", volume=0.01, sl=1999.0, tp=2002.0)
    args.update(kw)
    return a.place_order(**args)


def test_tick_values_read_from_runtime(make):
    a, _ = make()
    meta = a.symbol_info()
    assert meta["tick_size"] == 0.01
    assert meta["tick_value"] == 1.0
    assert meta["contract_size"] == 100.0


def test_spec_mismatch_fails_closed(make):
    a, m = make(trade_contract_size=10)
    with pytest.raises(MT5AdapterError, match="contract_size mismatch"):
        a.symbol_info()


def test_invalid_tick_value_rejected(make):
    a, _ = make(trade_tick_value=0)
    with pytest.raises(MT5AdapterError, match="Invalid runtime"):
        a.symbol_info()


def test_sl_tp_mandatory(make):
    a, m = make()
    with pytest.raises(MT5AdapterError, match="mandatory"):
        order(a, sl=None)
    assert m.sent == []


def test_bad_side_rejected(make):
    a, m = make()
    with pytest.raises(MT5AdapterError, match="BUY or SELL"):
        order(a, side="HOLD")
    assert m.sent == []


def test_volume_below_min_rejected(make):
    a, m = make()
    with pytest.raises(MT5AdapterError, match="Volume outside"):
        order(a, volume=0.001)
    assert m.sent == []


def test_volume_not_aligned_to_step(make):
    a, m = make()
    with pytest.raises(MT5AdapterError, match="not aligned"):
        order(a, volume=0.015)
    assert m.sent == []


def test_buy_sl_too_close_rejected(make):
    a, m = make()
    with pytest.raises(MT5AdapterError, match="too close"):
        order(a, sl=1999.9)
    assert m.sent == []


def test_sell_with_buy_side_levels_rejected(make):
    a, m = make()
    with pytest.raises(MT5AdapterError, match="SELL SL/TP invalid"):
        order(a, side="SELL", sl=1999.0, tp=2002.0)
    assert m.sent == []


def test_duplicate_signal_not_resent(make):
    pos = [{"magic": ad.MAGIC, "comment": ad._comment("dup1")}]
    a, m = make(positions=pos)
    result = order(a, signal_id="dup1")
    assert result["status"] == "DUPLICATE"
    assert m.sent == []
