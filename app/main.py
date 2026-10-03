import os
import csv
import time
import datetime
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, Request, BackgroundTasks
from apscheduler.schedulers.background import BackgroundScheduler

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY") or os.getenv("TWELVEDATA_API_KEY", "")

PAIRS = ["XAUUSD", "GBPUSD", "EURUSD"]
MIN_CANDLES = 60            # kailangan para sa totoong EMA50
FETCH_SIZE = 100            # live scan

# ---- Backtest settings ----
SPREAD_PIPS = {"XAUUSD": 3.0, "GBPUSD": 1.5, "EURUSD": 1.2}
TIMEOUT_CANDLES = 20        # 20 x M5 = 100 minutes max hold
DEFAULT_BT_DAYS = 60
MAX_BT_DAYS = int(os.getenv("BACKTEST_MAX_DAYS", "180"))
TD_MAX_OUTPUT = 5000        # max ng Twelve Data per request
TD_MAX_PAGES = 15
TD_PAGE_DELAY = 8           # seconds, iwas rate limit (free plan = 8 credits/min)

SCANS_TODAY = 0
SCAN_DATE = None
LAST_SCAN_PHT = "N/A"
LAST_SIGNAL = {}            # pair -> candle datetime (anti-duplicate alerts)
BACKTEST_RUNNING = False

scheduler = BackgroundScheduler()


# ------------------------------------------------------------------ helpers
def pht_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=8)


def send_telegram_msg(message: str, target_chat_id: str = None):
    chat_id = target_chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print("Telegram tokens missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")


def send_telegram_document(path: str, caption: str, target_chat_id: str = None):
    chat_id = target_chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print("Telegram tokens missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(path, "rb") as f:
            requests.post(
                url,
                data={"chat_id": chat_id, "caption": caption},
                files={"document": f},
                timeout=60,
            )
    except Exception as e:
        print(f"Error sending Telegram document: {e}")


def td_symbol(symbol: str) -> str:
    return f"{symbol[:3]}/{symbol[3:]}"  # XAUUSD -> XAU/USD


def td_get(params: dict):
    """Twelve Data request na may retry kapag rate-limited."""
    url = "https://api.twelvedata.com/time_series"
    res = {}
    for _ in range(3):
        res = requests.get(url, params=params, timeout=30).json()
        msg = str(res.get("message", "")).lower()
        if res.get("code") == 429 or "credits" in msg:
            time.sleep(65)
            continue
        return res
    return res


def parse_dt(s: str):
    return datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S")


# ------------------------------------------------------------------ live data
def fetch_m5_data(symbol: str):
    """Closed M5 candles, newest first."""
    params = {
        "symbol": td_symbol(symbol),
        "interval": "5min",
        "outputsize": FETCH_SIZE,
        "timezone": "UTC",
        "apikey": TWELVE_DATA_API_KEY,
    }
    try:
        res = td_get(params)
        if "values" not in res:
            print(f"Twelve Data error for {symbol}: {res.get('message', res)}")
            return None
        values = res["values"]
        # Tanggalin ang kasalukuyang (hindi pa sarado) na candle para walang repaint
        if values:
            try:
                dt = parse_dt(values[0]["datetime"])
                if datetime.datetime.utcnow() < dt + datetime.timedelta(minutes=5):
                    values = values[1:]
            except Exception:
                pass
        return values
    except Exception as e:
        print(f"Data fetch error for {symbol}: {e}")
    return None


def fetch_history_m5(symbol: str, days: int):
    """Historical M5 candles (oldest first) gamit ang pagination (end_date)."""
    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=days)
    rows = {}
    end_date = None

    for page in range(TD_MAX_PAGES):
        params = {
            "symbol": td_symbol(symbol),
            "interval": "5min",
            "outputsize": TD_MAX_OUTPUT,
            "timezone": "UTC",
            "apikey": TWELVE_DATA_API_KEY,
        }
        if end_date:
            params["end_date"] = end_date

        res = td_get(params)
        values = res.get("values")
        if not values:
            if page == 0:
                raise RuntimeError(f"{symbol}: {res.get('message', 'walang data')}")
            break

        for v in values:
            rows[v["datetime"]] = v

        oldest = values[-1]["datetime"]
        if parse_dt(oldest) <= cutoff or len(values) < TD_MAX_OUTPUT or oldest == end_date:
            break
        end_date = oldest
        time.sleep(TD_PAGE_DELAY)

    candles = [rows[k] for k in sorted(rows.keys()) if parse_dt(k) >= cutoff]
    # tanggalin ang hindi pa sarado na candle
    if candles and now < parse_dt(candles[-1]["datetime"]) + datetime.timedelta(minutes=5):
        candles = candles[:-1]
    return candles


# ------------------------------------------------------------------ strategy
def ema(values_oldest_first, period):
    k = 2 / (period + 1)
    e = sum(values_oldest_first[:period]) / period
    for v in values_oldest_first[period:]:
        e = v * k + e * (1 - k)
    return e


def analyze_hybrid_scalp(symbol, candles):
    """candles: newest first."""
    if not candles or len(candles) < MIN_CANDLES:
        return None

    closes_old_first = [float(c["close"]) for c in reversed(candles)]
    ema20 = ema(closes_old_first, 20)
    ema50 = ema(closes_old_first, 50)

    c0 = float(candles[0]["close"])
    o0 = float(candles[0]["open"])
    h0 = float(candles[0]["high"])
    l0 = float(candles[0]["low"])

    c1 = float(candles[1]["close"])
    o1 = float(candles[1]["open"])

    recent_high = max(float(c["high"]) for c in candles[1:8])
    recent_low = min(float(c["low"]) for c in candles[1:8])

    body_size = abs(c0 - o0)
    prev_body = abs(c1 - o1)

    score = 0
    signal_type = None

    body_multiplier = 1.5 if symbol == "EURUSD" else 1.2

    if c0 > ema20 > ema50:
        if c0 > o0 and body_size > prev_body * body_multiplier:
            score += 35
            if l0 < recent_low:
                score += 25
            if c0 > float(candles[1]["high"]):
                score += 15
            signal_type = "BUY"

    elif c0 < ema20 < ema50:
        if c0 < o0 and body_size > prev_body * body_multiplier:
            score += 35
            if h0 > recent_high:
                score += 25
            if c0 < float(candles[1]["low"]):
                score += 15
            signal_type = "SELL"

    required_score = 70 if symbol == "EURUSD" else 65

    if signal_type and score >= required_score:
        is_gold = symbol == "XAUUSD"
        pip_factor = 0.1 if is_gold else 0.0001
        digits = 2 if is_gold else 4

        if is_gold:
            sl_pips, tp_pips = 18, 36
        elif symbol == "GBPUSD":
            sl_pips, tp_pips = 12, 24
        else:  # EURUSD dynamic swing SL + buffer
            if signal_type == "BUY":
                calculated_sl = round(abs(c0 - recent_low) / pip_factor, 1) + 2.0
            else:
                calculated_sl = round(abs(recent_high - c0) / pip_factor, 1) + 2.0
            sl_pips = max(8.0, min(calculated_sl, 12.0))
            tp_pips = sl_pips * 2.0

        if signal_type == "BUY":
            sl = round(c0 - sl_pips * pip_factor, digits)
            tp = round(c0 + tp_pips * pip_factor, digits)
        else:
            sl = round(c0 + sl_pips * pip_factor, digits)
            tp = round(c0 - tp_pips * pip_factor, digits)

        return {
            "pair": symbol,
            "type": signal_type,
            "entry": c0,
            "sl": sl,
            "tp": tp,
            "sl_pips": float(sl_pips),
            "tp_pips": float(tp_pips),
            "score": score,
            "time": candles[0].get("datetime"),
        }
    return None


# ------------------------------------------------------------------ backtest
def simulate_pair(pair: str, records: list):
    """Walk-forward replay. records = oldest first. Returns list ng trade dicts."""
    spread = SPREAD_PIPS[pair]
    pip_factor = 0.1 if pair == "XAUUSD" else 0.0001
    digits = 2 if pair == "XAUUSD" else 4
    times = [parse_dt(r["datetime"]) for r in records]
    n = len(records)
    trades = []

    i = MIN_CANDLES
    while i < n - TIMEOUT_CANDLES:
        window = records[i - MIN_CANDLES:i][::-1]  # newest first
        sig = analyze_hybrid_scalp(pair, window)
        if not sig:
            i += 1
            continue

        # Iwasan ang signals na may gap (weekend/market close) sa pagitan
        if (times[i] - times[i - 1]) > datetime.timedelta(minutes=10):
            i += 1
            continue

        direction = 1 if sig["type"] == "BUY" else -1
        exit_reason = None
        exit_price = None
        exit_idx = None

        future = records[i:i + TIMEOUT_CANDLES]
        for n_bar, fc in enumerate(future):
            high_p = float(fc["high"])
            low_p = float(fc["low"])

            if sig["type"] == "BUY":
                hit_sl = low_p <= sig["sl"]
                hit_tp = high_p >= sig["tp"]
            else:
                hit_sl = high_p >= sig["sl"]
                hit_tp = low_p <= sig["tp"]

            # Conservative: kapag pareho sa isang candle, SL ang bilang
            if hit_sl:
                exit_reason, exit_price, exit_idx = "SL", sig["sl"], i + n_bar
                break
            if hit_tp:
                exit_reason, exit_price, exit_idx = "TP", sig["tp"], i + n_bar
                break

        if exit_reason is None:
            exit_idx = i + len(future) - 1
            exit_price = float(records[exit_idx]["close"])
            exit_reason = "TIMEOUT"

        gross_pips = direction * (exit_price - sig["entry"]) / pip_factor
        net_pips = gross_pips - spread
        r_result = net_pips / sig["sl_pips"]

        # Spread Cut: gross positibo pero kinain ng spread (net <= 0)
        if exit_reason in ("TP", "TIMEOUT") and gross_pips > 0 and net_pips <= 0:
            exit_reason = "SPREAD_CUT"

        trades.append({
            "pair": pair,
            "type": sig["type"],
            "entry_time": records[i - 1]["datetime"],
            "entry": round(sig["entry"], digits),
            "sl": sig["sl"],
            "tp": sig["tp"],
            "exit_time": records[exit_idx]["datetime"],
            "exit_price": round(exit_price, digits),
            "exit_reason": exit_reason,
            "bars_held": exit_idx - i + 1,
            "spread_pips": spread,
            "gross_pips": round(gross_pips, 1),
            "net_pips": round(net_pips, 1),
            "r_result": round(r_result, 2),
            "score": sig["score"],
        })

        # Walang overlapping trades: hintayin matapos ang kasalukuyang trade
        i = exit_idx + 1

    return trades


def calc_stats(trades: list):
    total = len(trades)
    if total == 0:
        return None
    rs = [t["r_result"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    net_r = sum(rs)
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))

    peak = equity = max_dd = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    reasons = {}
    for t in trades:
        reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1

    return {
        "trades": total,
        "win_rate": round(len(wins) / total * 100, 1),
        "net_r": round(net_r, 1),
        "expectancy": round(net_r / total, 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else float("inf"),
        "max_dd": round(max_dd, 1),
        "reasons": reasons,
    }


def format_stats_block(title: str, st):
    if not st:
        return f"• *{title}*: walang trades\n\n"
    r = st["reasons"]
    pf = st["profit_factor"]
    pf_txt = "inf" if pf == float("inf") else pf
    warn = " ⚠️ maliit pa" if st["trades"] < 100 else ""
    return (
        f"• *{title}*:\n"
        f"  - Trades: `{st['trades']}`{warn} | Win Rate: `{st['win_rate']}%`\n"
        f"  - TP/SL/TO/SC: `{r.get('TP', 0)}/{r.get('SL', 0)}/{r.get('TIMEOUT', 0)}/{r.get('SPREAD_CUT', 0)}`\n"
        f"  - Net R: `{st['net_r']}R` | Expectancy: `{st['expectancy']}R`\n"
        f"  - Profit Factor: `{pf_txt}` | Max DD: `{st['max_dd']}R`\n\n"
    )


CSV_FIELDS = [
    "pair", "type", "entry_time", "entry", "sl", "tp", "exit_time", "exit_price",
    "exit_reason", "bars_held", "spread_pips", "gross_pips", "net_pips", "r_result", "score",
]


def run_hybrid_backtest_task(chat_id: str, days: int = DEFAULT_BT_DAYS):
    global BACKTEST_RUNNING
    if BACKTEST_RUNNING:
        send_telegram_msg("⏳ May tumatakbong backtest pa. Hintayin muna.", chat_id)
        return
    BACKTEST_RUNNING = True

    try:
        if not TWELVE_DATA_API_KEY:
            send_telegram_msg("❌ Walang `TWELVE_DATA_API_KEY`.", chat_id)
            return

        send_telegram_msg(
            f"⏳ *Backtest started: {days} days, real Twelve Data M5*\n"
            f"Spread: XAU `3.0` | GBP `1.5` | EUR `1.2` pips\n"
            f"Mga 1-3 minuto ito (pagination + rate limit).",
            chat_id,
        )

        all_trades = []
        by_pair = {}
        coverage = {}

        for idx, pair in enumerate(PAIRS):
            if idx > 0:
                time.sleep(TD_PAGE_DELAY)
            send_telegram_msg(f"📥 Kinukuha ang history ng *{pair}*...", chat_id)
            records = fetch_history_m5(pair, days)
            if len(records) < MIN_CANDLES + TIMEOUT_CANDLES + 10:
                send_telegram_msg(f"⚠️ {pair}: kulang ang data ({len(records)} candles).", chat_id)
                by_pair[pair] = []
                continue
            coverage[pair] = (records[0]["datetime"], records[-1]["datetime"], len(records))
            trades = simulate_pair(pair, records)
            by_pair[pair] = trades
            all_trades.extend(trades)

        summary = f"📊 *SMC BACKTEST — REAL DATA, {days}D, WITH SPREAD*\n\n"
        for pair in PAIRS:
            summary += format_stats_block(pair, calc_stats(by_pair.get(pair, [])))
        summary += format_stats_block("ALL PAIRS", calc_stats(all_trades))

        for pair, (start, end, cnt) in coverage.items():
            summary += f"_{pair}: {cnt} candles, {start[:10]} → {end[:10]}_\n"
        summary += (
            "\n_TP/SL/TO/SC = TP / SL / Timeout / Spread Cut._\n"
            "_Fixed spread lang ito — mas malala ang totoong spread kapag news/rollover. "
            "100+ trades per pair bago pagkatiwalaan._"
        )
        send_telegram_msg(summary, chat_id)

        if all_trades:
            stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            path = f"/tmp/backtest_trades_{stamp}.csv"
            with open(path, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                w.writeheader()
                w.writerows(all_trades)
            send_telegram_document(path, f"Trade log — {len(all_trades)} trades, {days} days", chat_id)
            try:
                os.remove(path)
            except Exception:
                pass
    except Exception as err:
        send_telegram_msg(f"❌ Backtest Error: {err}", chat_id)
    finally:
        BACKTEST_RUNNING = False


# ------------------------------------------------------------------ live scan
def format_signal(sig, title="⚡ *M5 SMC SIGNAL DETECTED*"):
    return (
        f"{title}\n\n"
        f"• *Pair:* `{sig['pair']}`\n"
        f"• *Action:* `{sig['type']}`\n"
        f"• *Entry Price:* `{sig['entry']}`\n"
        f"• *Stop Loss:* `{sig['sl']}`\n"
        f"• *Take Profit:* `{sig['tp']}` (1:2 RR)\n"
        f"• *Confluence Score:* `{sig['score']}/100`\n\n"
        f"⚠️ *Execution Mode:* Paper Trade Verification"
    )


def scheduled_market_scan():
    global SCANS_TODAY, SCAN_DATE, LAST_SCAN_PHT

    now = pht_now()
    if SCAN_DATE != now.date():  # reset counter kada araw
        SCAN_DATE = now.date()
        SCANS_TODAY = 0
    SCANS_TODAY += 1
    LAST_SCAN_PHT = now.strftime("%Y-%m-%d %I:%M:%S %p PHT")

    for pair in PAIRS:
        data = fetch_m5_data(pair)
        if not data:
            continue
        sig = analyze_hybrid_scalp(pair, data)
        if sig and LAST_SIGNAL.get(pair) != sig["time"]:  # iwas duplicate alert
            LAST_SIGNAL[pair] = sig["time"]
            send_telegram_msg(format_signal(sig))


def manual_scan_task(chat_id: str):
    send_telegram_msg("🔍 *Scanning M5 SMC setups... Please wait.*", chat_id)
    found = False
    for pair in PAIRS:
        data = fetch_m5_data(pair)
        if not data:
            continue
        sig = analyze_hybrid_scalp(pair, data)
        if sig:
            found = True
            send_telegram_msg(format_signal(sig, "⚡ *SMC SIGNAL*"), chat_id)
    if not found:
        send_telegram_msg("ℹ️ *No high-confluence M5 SMC setups detected right now.*", chat_id)


# ------------------------------------------------------------------ app
@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running:
        scheduler.add_job(
            scheduled_market_scan, "interval", minutes=5,
            max_instances=1, coalesce=True,
        )
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="SMC Scalp Engine V2.3 - Real Data Backtest", lifespan=lifespan)


@app.api_route("/telegram-webhook", methods=["GET", "POST"])
@app.api_route("/telegram/webhook", methods=["GET", "POST"])
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        update = await request.json()
        if "message" in update and "text" in update["message"]:
            chat_id = str(update["message"]["chat"]["id"])
            parts = update["message"]["text"].strip().split()
            text = parts[0].split("@")[0] if parts else ""  # handle /scan@botname
            args = parts[1:]

            # Ikaw lang ang pwedeng gumamit ng bot
            if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
                return {"status": "ok"}

            if text == "/status":
                msg = (
                    "📊 *ENGINE OPERATIONAL STATUS*\n\n"
                    "• *System Mode:* `SMC_KILLZONE_V2.3`\n"
                    "• *Paper Session:* `True`\n"
                    "• *Data Provider:* `TWELVE_DATA_SPOT`\n"
                    f"• *Scans Today:* `{SCANS_TODAY}`\n"
                    f"• *Last Scan:* `{LAST_SCAN_PHT}`"
                )
                send_telegram_msg(msg, chat_id)

            elif text == "/scan":
                background_tasks.add_task(manual_scan_task, chat_id)

            elif text == "/backtest":
                days = DEFAULT_BT_DAYS
                if args and args[0].isdigit():
                    days = max(7, min(int(args[0]), MAX_BT_DAYS))
                background_tasks.add_task(run_hybrid_backtest_task, chat_id, days)

            elif text in ["/help", "/start"]:
                msg = (
                    "🤖 *AI TRADING BOT COMMANDS*\n\n"
                    "• `/status` - Check active system mode & scan counts\n"
                    "• `/scan` - Force manual scan for M5 SMC setups\n"
                    f"• `/backtest [days]` - Real-data backtest w/ spread + CSV (default {DEFAULT_BT_DAYS}, max {MAX_BT_DAYS})"
                )
                send_telegram_msg(msg, chat_id)

    except Exception as e:
        print(f"Webhook processing error: {e}")

    return {"status": "ok"}


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "mode": "SMC_KILLZONE_V2.3"}


@app.get("/status")
def status():
    return {
        "system_mode": "SMC_KILLZONE_V2.3",
        "paper_session": True,
        "scans_today": SCANS_TODAY,
        "last_scan_pht": LAST_SCAN_PHT,
    }
