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
    POSITION_TYPE_BUY = 0

    def __init__(self, positions=None, ticket_rows=None, check_rc=0,
                 send_rc=10009, send_none=False):
        self._positions = positions or []
        self._ticket_rows = ticket_rows
        self.check_rc = check_rc
        self.send_rc = send_rc
        self.send_none = send_none
        self.sent = []
        self.calls = []

    def symbol_info(self, s):
        return N(name=s, visible=True, trade_contract_size=100,
                 volume_min=0.01, volume_step=0.01, volume_max=100,
                 digits=2, trade_stops_level=20, trade_tick_size=0.01,
                 trade_tick_value=1.0, point=0.01)

    def symbol_select(self, *a):
        return True

    def symbol_info_tick(self, s):
        return N(ask=2000.0, bid=1999.98)

    def positions_get(self, **kw):
        if "ticket" in kw:
            return self._ticket_rows
        return self._positions

    def last_error(self):
        return (0, "ok")

    def order_check(self, r):
        self.calls.append("check")
        return N(retcode=self.check_rc)

    def order_send(self, r):
        self.calls.append("send")
        self.sent.append(r)
        if self.send_none:
            return None
        return N(retcode=self.send_rc)


@pytest.fixture
def make(monkeypatch):
    def _make(**kw):
        for k in ("MT5_CONTRACT_SIZE", "MT5_MIN_VOLUME", "MT5_VOLUME_STEP"):
            monkeypatch.delenv(k, raising=False)
        m = Mock(**kw)
        monkeypatch.setattr(ad, "mt5", m)
        return MT5Adapter(), m
    return _make


def buy(a, **kw):
    args = dict(signal_id="s1", side="BUY", volume=0.01, sl=1999.0, tp=2002.0)
    args.update(kw)
    return a.place_order(**args)


def test_successful_order_has_sl_tp_ioc_magic(make):
    a, m = make()
    r = buy(a)
    assert r["status"] == "SUBMITTED" and r["retcode"] == 10009
    req = m.sent[0]
    assert req["sl"] == 1999.0 and req["tp"] == 2002.0
    assert req["type_filling"] == 1 and req["type"] == 0
    assert req["price"] == 2000.0 and req["volume"] == 0.01
    assert req["magic"] == ad.MAGIC and req["comment"].startswith("TITAN-")
    assert m.calls == ["check", "send"]


def test_sell_order_uses_bid(make):
    a, m = make()
    buy(a, side="SELL", sl=2001.0, tp=1998.0)
    assert m.sent[0]["type"] == 1 and m.sent[0]["price"] == 1999.98


def test_order_check_rejection_blocks_send(make):
    a, m = make(check_rc=10013)
    with pytest.raises(MT5AdapterError, match="order_check retcode"):
        buy(a)
    assert m.sent == []


def test_order_send_rejection_raises(make):
    a, m = make(send_rc=10006)
    with pytest.raises(MT5AdapterError, match="order_send retcode"):
        buy(a)


def test_order_send_none_raises(make):
    a, m = make(send_none=True)
    with pytest.raises(MT5AdapterError, match="order_send failed"):
        buy(a)


def test_close_buy_position_sells_at_bid(make):
    rows = [N(symbol="XAUUSD", type=0, volume=0.01)]
    a, m = make(ticket_rows=rows)
    r = a.close_position(777)
    assert r["status"] == "CLOSE_SUBMITTED"
    req = m.sent[0]
    assert req["position"] == 777 and req["type"] == 1
    assert req["price"] == 1999.98 and req["volume"] == 0.01


def test_close_already_closed_sends_nothing(make):
    a, m = make(ticket_rows=[])
    assert a.close_position(777)["status"] == "ALREADY_CLOSED"
    assert m.sent == []


def test_close_rejected_raises(make):
    rows = [N(symbol="XAUUSD", type=0, volume=0.01)]
    a, m = make(ticket_rows=rows, send_rc=10006)
    with pytest.raises(MT5AdapterError, match="close rejected"):
        a.close_position(777)


def test_close_wrong_symbol_refused(make):
    rows = [N(symbol="EURUSD", type=0, volume=0.01)]
    a, m = make(ticket_rows=rows)
    with pytest.raises(MT5AdapterError, match="symbol mismatch"):
        a.close_position(777)
    assert m.sent == []


def test_reconcile_matches_only_own_magic_and_signal(make):
    pos = [{"magic": ad.MAGIC, "comment": ad._comment("s1")},
           {"magic": 999, "comment": ad._comment("s1")}]
    a, m = make(positions=pos)
    assert a.reconcile("s1")["position_count"] == 1
    assert a.reconcile("other")["position_count"] == 0


def _conn(monkeypatch, server, trade_mode):
    m = N(initialize=lambda: True,
          account_info=lambda: N(server=server, trade_mode=trade_mode, login=1,
                                 currency="USD", balance=1.0, equity=1.0),
          last_error=lambda: (0, "ok"), shutdown=lambda: None,
          ACCOUNT_TRADE_MODE_REAL=2)
    monkeypatch.setattr(ad, "mt5", m)
    monkeypatch.setattr(ad, "DEMO_ONLY", True)
    monkeypatch.delenv("MT5_DEMO_SERVER", raising=False)


def test_connect_rejects_non_demo_server(monkeypatch):
    _conn(monkeypatch, "Vantage-Live", 2)
    with pytest.raises(MT5AdapterError, match="server mismatch"):
        MT5Adapter().connect()


def test_connect_rejects_real_trade_mode(monkeypatch):
    _conn(monkeypatch, "VantageMarkets-Demo", 2)
    with pytest.raises(MT5AdapterError, match="Real account rejected"):
        MT5Adapter().connect()


def test_connect_accepts_demo(monkeypatch):
    _conn(monkeypatch, "VantageMarkets-Demo", 0)
    assert MT5Adapter().connect()["server"] == "VantageMarkets-Demo"
