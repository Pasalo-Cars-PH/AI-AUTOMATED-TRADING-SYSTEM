"""Local demo-only signal executor with HMAC and MT5-history risk locks."""
import hashlib, hmac, json, os, threading, time
from datetime import datetime, time as day_time, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse
import requests
from broker.mt5_adapter import MT5Adapter, MT5AdapterError
try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

HOST = os.getenv("EXECUTOR_HOST", "127.0.0.1")
PORT = int(os.getenv("EXECUTOR_PORT", "8787"))
SECRET = os.getenv("SIGNAL_HMAC_SECRET", "")
MAX_SKEW = int(os.getenv("SIGNAL_MAX_CLOCK_SKEW_SECONDS", "60"))
DAILY_CAP = float(os.getenv("DAILY_LOSS_CAP_PCT", "2.0"))
LOSS_LIMIT = int(os.getenv("MAX_CONSECUTIVE_LOSSES", "4"))
MODE = os.getenv("EXECUTION_MODE", "DEMO").upper()
adapter = MT5Adapter()
lock = threading.RLock()
kill_switch = True
paused = True
seen = set()
seen_order = []


class ExecutorError(RuntimeError): pass


def validate_hmac(body, timestamp, signature):
    if not SECRET:
        raise ExecutorError("SIGNAL_HMAC_SECRET_UNSET")
    try: stamp = int(timestamp)
    except (TypeError, ValueError): raise ExecutorError("INVALID_TIMESTAMP")
    if abs(int(time.time()) - stamp) > MAX_SKEW:
        raise ExecutorError("STALE_TIMESTAMP")
    expected = hmac.new(SECRET.encode(), str(timestamp).encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
    supplied = str(signature).removeprefix("sha256=").lower().strip()
    if not hmac.compare_digest(expected, supplied):
        raise ExecutorError("INVALID_HMAC")


def history_risk(now=None):
    if mt5 is None: raise ExecutorError("MT5_PACKAGE_UNAVAILABLE")
    now = now or datetime.now(timezone.utc)
    start = datetime.combine(now.date(), day_time.min, tzinfo=timezone.utc)
    deals = mt5.history_deals_get(start, now)
    if deals is None: raise ExecutorError(f"HISTORY_UNAVAILABLE: {mt5.last_error()}")
    account = mt5.account_info()
    if account is None: raise ExecutorError(f"ACCOUNT_INFO_UNAVAILABLE: {mt5.last_error()}")
    out_codes = {getattr(mt5, "DEAL_ENTRY_OUT", 1), getattr(mt5, "DEAL_ENTRY_OUT_BY", 3), getattr(mt5, "DEAL_ENTRY_INOUT", 2)}
    rows = []
    for d in deals:
        if getattr(d, "entry", None) not in out_codes: continue
        pnl = sum(float(getattr(d, k, 0.0) or 0.0) for k in ("profit", "commission", "swap", "fee"))
        rows.append((int(getattr(d, "time", 0)), int(getattr(d, "ticket", 0)), pnl))
    rows.sort()
    net = sum(x[2] for x in rows)
    equity = float(account.equity)
    start_equity = equity - net
    if equity <= 0 or start_equity <= 0: raise ExecutorError("INVALID_EQUITY_HISTORY")
    streak = 0
    for _, _, pnl in reversed(rows):
        if pnl < 0: streak += 1
        else: break
    loss_pct = max(0.0, -net / start_equity * 100)
    return {"history_ok": True, "closing_deals": len(rows), "daily_net_pnl": round(net, 2),
            "equity": round(equity, 2), "start_equity_estimate": round(start_equity, 2),
            "daily_loss_pct": round(loss_pct, 4), "daily_loss_locked": loss_pct >= DAILY_CAP,
            "consecutive_losses": streak, "loss_streak_locked": streak >= LOSS_LIMIT}


def execute_signal(s):
    global kill_switch, paused
    required = {"signal_id", "symbol", "side", "volume", "sl", "tp"}
    if not isinstance(s, dict) or required - set(s): raise ExecutorError("MISSING_REQUIRED_SIGNAL_FIELDS")
    if MODE != "DEMO": raise ExecutorError("LIVE_MODE_NOT_IMPLEMENTED")
    with lock:
        if kill_switch: raise ExecutorError("KILL_SWITCH_ACTIVE")
        if paused: raise ExecutorError("EXECUTOR_PAUSED")
        if s["signal_id"] in seen: raise ExecutorError("DUPLICATE_SIGNAL_ID")
    if s["symbol"] != adapter.symbol: raise ExecutorError("SYMBOL_NOT_ALLOWED")
    if s["side"] not in ("BUY", "SELL"): raise ExecutorError("INVALID_SIDE")
    if s["sl"] is None or s["tp"] is None: raise ExecutorError("SL_TP_REQUIRED")
    if len(adapter.positions()) >= 1: raise ExecutorError("MAX_OPEN_POSITIONS_REACHED")
    risk = history_risk()
    if risk["daily_loss_locked"]: raise ExecutorError("DAILY_LOSS_CAP_REACHED")
    if risk["loss_streak_locked"]: raise ExecutorError("FOUR_LOSS_LOCK_REACHED")
    result = adapter.place_order(signal_id=s["signal_id"], side=s["side"],
                                 volume=float(s["volume"]), sl=float(s["sl"]), tp=float(s["tp"]))
    with lock:
        seen.add(s["signal_id"]); seen_order.append(s["signal_id"])
        if len(seen_order) > 10000: seen.discard(seen_order.pop(0))
    return {"status": "ok", "risk": risk, "broker": result}


def telegram_loop():
    global kill_switch, paused
    token, allowed = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not allowed:
        print("Telegram controls disabled: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        return
    offset = 0
    while True:
        try:
            r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates",
                             params={"timeout": 25, "offset": offset}, timeout=30)
            r.raise_for_status()
            for u in r.json().get("result", []):
                offset = max(offset, int(u["update_id"]) + 1)
                m = u.get("message") or {}
                if str((m.get("chat") or {}).get("id", "")) != str(allowed): continue
                parts = str(m.get("text", "")).strip().split()
                if not parts: continue
                cmd = parts[0].split("@")[0].lower()
                with lock:
                    if cmd == "/kill":
                        kill_switch, reply = True, "KILL ON: new entries blocked; open positions unchanged."
                    elif cmd == "/pause":
                        paused, reply = True, "PAUSED: new entries blocked."
                    elif cmd == "/resume":
                        paused, reply = False, "Unpaused; kill switch may still block entries."
                    elif cmd == "/arm_demo":
                        if MODE == "DEMO":
                            kill_switch, reply = False, "DEMO executor armed. Check terminal/account before use."
                        else: reply = "Rejected: only DEMO mode supported."
                    elif cmd == "/status":
                        reply = f"mode={MODE} kill={kill_switch} paused={paused}"
                    else: reply = "Commands: /kill /pause /resume /arm_demo /status"
                requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                              json={"chat_id": allowed, "text": reply}, timeout=10).raise_for_status()
        except Exception as e:
            print(f"Telegram polling error: {type(e).__name__}: {e}")
            time.sleep(5)


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, payload):
        raw = json.dumps(payload, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        if urlparse(self.path).path != "/signal": return self.reply(404, {"error":"not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if n < 1 or n > 16384: raise ExecutorError("INVALID_BODY_SIZE")
            body = self.rfile.read(n)
            validate_hmac(body, self.headers.get("X-Signal-Timestamp"), self.headers.get("X-Signal-Signature"))
            result = execute_signal(json.loads(body.decode("utf-8")))
            self.reply(200, result)
        except (ExecutorError, MT5AdapterError, ValueError) as e:
            self.reply(403, {"status":"blocked", "error":str(e)})
        except Exception as e:
            self.reply(500, {"status":"error", "error":f"{type(e).__name__}: {e}"})
    def log_message(self, fmt, *args): print("HTTP:", fmt % args)


def main():
    if MODE != "DEMO": raise SystemExit("Only EXECUTION_MODE=DEMO is implemented")
    if not SECRET: raise SystemExit("Set SIGNAL_HMAC_SECRET")
    if HOST not in ("127.0.0.1", "localhost"):
        raise SystemExit("Bind localhost only; do not expose this receiver publicly.")
    print("Connected account:", adapter.connect())
    print("START LOCKED: use Telegram /arm_demo only after verifying demo terminal.")
    threading.Thread(target=telegram_loop, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try: server.serve_forever()
    finally: server.server_close(); adapter.shutdown()


if __name__ == "__main__": main()
