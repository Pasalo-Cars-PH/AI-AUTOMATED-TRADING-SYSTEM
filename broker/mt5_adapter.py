"""Fail-closed MT5 adapter for explicitly configured demo trading."""
import hashlib
import math
import os

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

SYMBOL = os.getenv("MT5_SYMBOL", "XAUUSD")
MAGIC = int(os.getenv("MT5_MAGIC", "26102701"))
DEMO_ONLY = os.getenv("MT5_DEMO_ONLY", "true").lower() == "true"


class MT5AdapterError(RuntimeError):
    pass


def _need_mt5():
    if mt5 is None:
        raise MT5AdapterError("Install MetaTrader5 on Windows first")


def _dict(obj):
    return obj._asdict() if hasattr(obj, "_asdict") else dict(obj) if isinstance(obj, dict) else {}


def _comment(signal_id):
    return ("TITAN-" + hashlib.sha256(signal_id.encode()).hexdigest()[:12])[:31]


class MT5Adapter:
    def __init__(self, symbol=SYMBOL):
        self.symbol = symbol
        self.initialized = False

    def connect(self):
        _need_mt5()
        if not mt5.initialize():
            raise MT5AdapterError(f"initialize failed: {mt5.last_error()}")
        self.initialized = True
        a = mt5.account_info()
        if a is None:
            raise MT5AdapterError(f"account_info failed: {mt5.last_error()}")
        server = str(getattr(a, "server", ""))
        if DEMO_ONLY and server != os.getenv("MT5_DEMO_SERVER", "VantageMarkets-Demo"):
            raise MT5AdapterError(f"DEMO_ONLY server mismatch: {server}")
        if DEMO_ONLY and int(getattr(a, "trade_mode", -1)) == getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2):
            raise MT5AdapterError("Real account rejected in DEMO_ONLY mode")
        return {"login": getattr(a, "login", None), "server": server,
                "currency": getattr(a, "currency", None), "balance": getattr(a, "balance", None),
                "equity": getattr(a, "equity", None), "trade_mode": getattr(a, "trade_mode", None)}

    def shutdown(self):
        if self.initialized and mt5 is not None:
            mt5.shutdown()
            self.initialized = False

    def symbol_info(self):
        _need_mt5()
        i = mt5.symbol_info(self.symbol)
        if i is None:
            raise MT5AdapterError(f"symbol_info failed: {mt5.last_error()}")
        if not getattr(i, "visible", False):
            if not mt5.symbol_select(self.symbol, True):
                raise MT5AdapterError(f"symbol_select failed: {mt5.last_error()}")
            i = mt5.symbol_info(self.symbol)
        meta = {
            "symbol": self.symbol, "contract_size": float(i.trade_contract_size),
            "volume_min": float(i.volume_min), "volume_step": float(i.volume_step),
            "volume_max": float(i.volume_max), "stops_level": max(20, int(i.trade_stops_level)),
            "freeze_level": int(getattr(i, "trade_freeze_level", 0)),
            "tick_size": float(i.trade_tick_size), "tick_value": float(i.trade_tick_value),
            "point": float(i.point), "digits": int(i.digits),
        }
        expected = {"contract_size": 100.0, "volume_min": 0.01, "volume_step": 0.01}
        for k, v in expected.items():
            configured = float(os.getenv("MT5_" + {"contract_size":"CONTRACT_SIZE","volume_min":"MIN_VOLUME","volume_step":"VOLUME_STEP"}[k], str(v)))
            if not math.isclose(meta[k], configured, rel_tol=0, abs_tol=1e-6):
                raise MT5AdapterError(f"{k} mismatch expected {configured}, got {meta[k]}")
        if meta["tick_size"] <= 0 or meta["tick_value"] <= 0 or meta["point"] <= 0:
            raise MT5AdapterError("Invalid runtime tick_size/tick_value/point")
        if self.symbol != SYMBOL:
            raise MT5AdapterError(f"Symbol mismatch: {self.symbol}")
        return meta

    def _quote(self):
        t = mt5.symbol_info_tick(self.symbol)
        if t is None or t.bid <= 0 or t.ask < t.bid:
            raise MT5AdapterError(f"Invalid quote: {mt5.last_error()}")
        return t, float(t.bid), float(t.ask)

    def positions(self):
        _need_mt5()
        rows = mt5.positions_get(symbol=self.symbol)
        if rows is None:
            raise MT5AdapterError(f"positions_get failed: {mt5.last_error()}")
        return [_dict(x) for x in rows]

    def find_by_signal(self, signal_id):
        comment = _comment(signal_id)
        return [p for p in self.positions()
                if int(p.get("magic", -1)) == MAGIC and p.get("comment") == comment]

    def place_order(self, *, signal_id, side, volume, sl, tp):
        _need_mt5()
        if not signal_id or sl is None or tp is None:
            raise MT5AdapterError("signal_id, SL and TP are mandatory")
        existing = self.find_by_signal(signal_id)
        if existing:
            return {"status": "DUPLICATE", "positions": existing}
        side = side.upper()
        if side not in ("BUY", "SELL"):
            raise MT5AdapterError("side must be BUY or SELL")
        meta = self.symbol_info()
        _, bid, ask = self._quote()
        volume, sl, tp = float(volume), float(sl), float(tp)
        if not all(math.isfinite(x) for x in (volume, sl, tp)):
            raise MT5AdapterError("Non-finite order field")
        if volume < meta["volume_min"] or volume > meta["volume_max"]:
            raise MT5AdapterError("Volume outside broker min/max")
        if abs((volume-meta["volume_min"])/meta["volume_step"] - round((volume-meta["volume_min"])/meta["volume_step"])) > 1e-7:
            raise MT5AdapterError("Volume not aligned to volume_step")
        entry = ask if side == "BUY" else bid
        distance = max(meta["stops_level"], meta["freeze_level"]) * meta["point"]
        if side == "BUY" and not (sl < entry < tp and entry-sl >= distance and tp-entry >= distance):
            raise MT5AdapterError("BUY SL/TP invalid or too close")
        if side == "SELL" and not (tp < entry < sl and sl-entry >= distance and entry-tp >= distance):
            raise MT5AdapterError("SELL SL/TP invalid or too close")
        request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol, "volume": volume,
                   "type": mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL,
                   "price": entry, "sl": round(sl, meta["digits"]), "tp": round(tp, meta["digits"]),
                   "deviation": int(os.getenv("MT5_DEVIATION_POINTS", "30")), "magic": MAGIC,
                   "comment": _comment(signal_id), "type_time": mt5.ORDER_TIME_GTC,
                   "type_filling": mt5.ORDER_FILLING_IOC}
        check = mt5.order_check(request)
        if check is None:
            raise MT5AdapterError(f"order_check failed: {mt5.last_error()}")
        check_rc = int(getattr(check, "retcode", -1))
        if check_rc not in (0, getattr(mt5, "TRADE_RETCODE_DONE", 10009)):
            raise MT5AdapterError(f"order_check retcode={check_rc}: {_dict(check)}")
        result = mt5.order_send(request)
        if result is None:
            raise MT5AdapterError(f"order_send failed: {mt5.last_error()}")
        rc = int(getattr(result, "retcode", -1))
        if rc not in (getattr(mt5, "TRADE_RETCODE_DONE", 10009),
                      getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010),
                      getattr(mt5, "TRADE_RETCODE_PLACED", 10008)):
            raise MT5AdapterError(f"order_send retcode={rc}: {_dict(result)}")
        return {"status": "SUBMITTED", "signal_id": signal_id, "request": request,
                "result": _dict(result), "retcode": rc}

    def close_position(self, ticket):
        _need_mt5()
        rows = mt5.positions_get(ticket=int(ticket))
        if rows is None:
            raise MT5AdapterError(f"positions_get(ticket) failed: {mt5.last_error()}")
        if not rows:
            return {"status": "ALREADY_CLOSED", "ticket": int(ticket)}
        p = rows[0]
        if p.symbol != self.symbol:
            raise MT5AdapterError("Position symbol mismatch")
        _, bid, ask = self._quote()
        is_buy = int(p.type) == mt5.POSITION_TYPE_BUY
        req = {"action": mt5.TRADE_ACTION_DEAL, "symbol": self.symbol,
               "position": int(ticket), "volume": float(p.volume),
               "type": mt5.ORDER_TYPE_SELL if is_buy else mt5.ORDER_TYPE_BUY,
               "price": bid if is_buy else ask,
               "deviation": int(os.getenv("MT5_DEVIATION_POINTS", "30")),
               "magic": MAGIC, "comment": "TITAN-CLOSE",
               "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC}
        r = mt5.order_send(req)
        if r is None or int(getattr(r, "retcode", -1)) not in (
            getattr(mt5, "TRADE_RETCODE_DONE", 10009),
            getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)):
            raise MT5AdapterError(f"close rejected: {_dict(r)}")
        return {"status": "CLOSE_SUBMITTED", "ticket": int(ticket),
                "retcode": int(r.retcode), "result": _dict(r)}

    def reconcile(self, signal_id):
        matches = self.find_by_signal(signal_id)
        return {"signal_id": signal_id, "matched_positions": matches,
                "position_count": len(matches), "reconciled": True}
