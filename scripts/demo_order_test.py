"""One explicitly enabled DEMO order, SL/TP verification, and close test."""
import os, time, uuid
from broker.mt5_adapter import MT5Adapter

def main():
    if os.getenv("ALLOW_DEMO_ORDER_TEST", "").lower() != "true":
        raise SystemExit("BLOCKED: set ALLOW_DEMO_ORDER_TEST=true after checking demo terminal.")
    if os.getenv("EXECUTION_MODE", "DEMO").upper() != "DEMO":
        raise SystemExit("BLOCKED: EXECUTION_MODE must be DEMO.")
    a = MT5Adapter()
    try:
        account = a.connect()
        print("ACCOUNT:", account)
        if account["server"] != os.getenv("MT5_DEMO_SERVER", "VantageMarkets-Demo") or account["currency"] != "USD":
            raise SystemExit("BLOCKED: wrong demo server or currency.")
        meta = a.symbol_info()
        print("SYMBOL METADATA:", meta)
        if a.positions(): raise SystemExit("BLOCKED: existing open position; reconcile manually.")
        _, bid, ask = a._quote()
        distance = max(meta["stops_level"], meta["freeze_level"]) * meta["point"]
        distance = max(distance, 10 * meta["tick_size"])
        sl = round(ask - 2 * distance, meta["digits"])
        tp = round(ask + 2 * distance, meta["digits"])
        sid = "DEMO-" + uuid.uuid4().hex[:20]
        response = a.place_order(signal_id=sid, side="BUY", volume=meta["volume_min"], sl=sl, tp=tp)
        print("ORDER RESPONSE:", response)
        print("ORDER RETCODE:", response.get("retcode"))
        until = time.time() + 15
        found = []
        while time.time() < until:
            found = a.find_by_signal(sid)
            if found: break
            time.sleep(1)
        if not found: raise SystemExit("FAIL: position not confirmed. Inspect MT5; do not retry blindly.")
        p = found[0]
        print("VERIFIED POSITION:", p)
        if float(p.get("sl", 0)) <= 0 or float(p.get("tp", 0)) <= 0:
            raise SystemExit("FAIL: broker position missing SL or TP; inspect terminal immediately.")
        closed = a.close_position(int(p["ticket"]))
        print("CLOSE RESPONSE:", closed)
        print("CLOSE RETCODE:", closed.get("retcode"))
        until = time.time() + 15
        while time.time() < until:
            if not any(int(x.get("ticket", -1)) == int(p["ticket"]) for x in a.positions()):
                print("PASS: position is no longer open.")
                return
            time.sleep(1)
        raise SystemExit("FAIL: close not confirmed; inspect MT5 manually.")
    finally:
        a.shutdown()

if __name__ == "__main__": main()
