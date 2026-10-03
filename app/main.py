import os
import datetime
from contextlib import asynccontextmanager

import requests
import numpy as np
from fastapi import FastAPI, Request, BackgroundTasks
from apscheduler.schedulers.background import BackgroundScheduler

try:
    from scripts.generate_synthetic_data import generate_spot_ohlc
except Exception as e:  # huwag mag-crash ang buong app kung wala ang script
    generate_spot_ohlc = None
    print(f"Synthetic data module unavailable: {e}")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

PAIRS = ["XAUUSD", "GBPUSD", "EURUSD"]
MIN_CANDLES = 60          # kailangan para sa totoong EMA50
FETCH_SIZE = 100

SCANS_TODAY = 0
SCAN_DATE = None
LAST_SCAN_PHT = "N/A"
LAST_SIGNAL = {}          # pair -> candle datetime (anti-duplicate alerts)

scheduler = BackgroundScheduler()


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


def fetch_m5_data(symbol: str):
    """Returns closed M5 candles, newest first."""
    sym = f"{symbol[:3]}/{symbol[3:]}"  # Twelve Data format: XAU/USD
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": sym,
        "interval": "5min",
        "outputsize": FETCH_SIZE,
        "timezone": "UTC",
        "apikey": TWELVE_DATA_API_KEY,
    }
    try:
        res = requests.get(url, params=params, timeout=10).json()
        if "values" not in res:
            print(f"Twelve Data error for {symbol}: {res.get('message', res)}")
            return None
        values = res["values"]
        # Tanggalin ang kasalukuyang (hindi pa sarado) na candle para walang repaint
        if values:
            try:
                dt = datetime.datetime.strptime(values[0]["datetime"], "%Y-%m-%d %H:%M:%S")
                if datetime.datetime.utcnow() < dt + datetime.timedelta(minutes=5):
                    values = values[1:]
            except Exception:
                pass
        return values
    except Exception as e:
        print(f"Data fetch error for {symbol}: {e}")
    return None


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
            "score": score,
            "time": candles[0].get("datetime"),
        }
    return None


def run_hybrid_backtest_task(chat_id: str):
    if generate_spot_ohlc is None:
        send_telegram_msg("❌ Backtest unavailable: synthetic data module missing.", chat_id)
        return

    send_telegram_msg("⏳ *Running Dynamic SMC Backtest (7-Day Replay)...*", chat_id)
    try:
        np.random.seed(42)

        summary_msg = "📊 *DYNAMIC FILTER SMC BACKTEST (7-Day, SYNTHETIC DATA)*\n\n"
        for pair in PAIRS:
            _, _, df_m5, _ = generate_spot_ohlc(pair, days=7)

            total_trades = wins = losses = timeouts = 0
            net_r = 0.0

            records = df_m5.to_dict("records")
            total_records = len(records)

            i = MIN_CANDLES
            while i < total_records - 20:
                window = list(reversed(records[i - MIN_CANDLES:i]))
                sig = analyze_hybrid_scalp(pair, window)

                if not sig:
                    i += 1
                    continue

                total_trades += 1
                result = None   # "win" / "loss" / None (timeout)
                exit_offset = 20

                for n, fc in enumerate(records[i:i + 20]):
                    high_p = float(fc["high"])
                    low_p = float(fc["low"])

                    if sig["type"] == "BUY":
                        hit_sl = low_p <= sig["sl"]
                        hit_tp = high_p >= sig["tp"]
                    else:
                        hit_sl = high_p >= sig["sl"]
                        hit_tp = low_p <= sig["tp"]

                    # Conservative: kung pareho sa isang candle, loss muna
                    if hit_sl:
                        result, exit_offset = "loss", n + 1
                        break
                    if hit_tp:
                        result, exit_offset = "win", n + 1
                        break

                if result == "win":
                    wins += 1
                    net_r += 2.0
                elif result == "loss":
                    losses += 1
                    net_r -= 1.0
                else:
                    timeouts += 1  # walang naabot, 0R

                # Walang overlapping trades: hintayin matapos ang trade
                i += max(exit_offset, 1)

            decided = wins + losses
            win_rate = round(wins / decided * 100, 1) if decided else 0.0
            expectancy = round(net_r / total_trades, 2) if total_trades else 0.0

            summary_msg += (
                f"• *{pair}*:\n"
                f"  - Trades: `{total_trades}` | Win Rate: `{win_rate}%`\n"
                f"  - W/L/Timeout: `{wins}/{losses}/{timeouts}`\n"
                f"  - Net R: `{round(net_r, 1)}R` | Expectancy: `{expectancy}R`\n\n"
            )
        summary_msg += "⚠️ _Synthetic data ito — hindi proof na kikita sa live market._"
        send_telegram_msg(summary_msg, chat_id)
    except Exception as err:
        send_telegram_msg(f"❌ Backtest Error: {err}", chat_id)


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


app = FastAPI(title="SMC Scalp Engine V2.2 - Dynamic EURUSD Filter", lifespan=lifespan)


@app.api_route("/telegram-webhook", methods=["GET", "POST"])
@app.api_route("/telegram/webhook", methods=["GET", "POST"])
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        update = await request.json()
        if "message" in update and "text" in update["message"]:
            chat_id = str(update["message"]["chat"]["id"])
            text = update["message"]["text"].strip().split("@")[0]  # handle /scan@botname

            # Ikaw lang ang pwedeng gumamit ng bot
            if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
                return {"status": "ok"}

            if text == "/status":
                msg = (
                    "📊 *ENGINE OPERATIONAL STATUS*\n\n"
                    "• *System Mode:* `SMC_KILLZONE_V2.2`\n"
                    "• *Paper Session:* `True`\n"
                    "• *Data Provider:* `TWELVE_DATA_SPOT`\n"
                    f"• *Scans Today:* `{SCANS_TODAY}`\n"
                    f"• *Last Scan:* `{LAST_SCAN_PHT}`"
                )
                send_telegram_msg(msg, chat_id)

            elif text == "/scan":
                background_tasks.add_task(manual_scan_task, chat_id)

            elif text == "/backtest":
                background_tasks.add_task(run_hybrid_backtest_task, chat_id)

            elif text in ["/help", "/start"]:
                msg = (
                    "🤖 *AI TRADING BOT COMMANDS*\n\n"
                    "• `/status` - Check active system mode & scan counts\n"
                    "• `/scan` - Force manual scan for M5 SMC setups\n"
                    "• `/backtest` - Run instant strategy simulation"
                )
                send_telegram_msg(msg, chat_id)

    except Exception as e:
        print(f"Webhook processing error: {e}")

    return {"status": "ok"}


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "mode": "SMC_KILLZONE_V2.2"}


@app.get("/status")
def status():
    return {
        "system_mode": "SMC_KILLZONE_V2.2",
        "paper_session": True,
        "scans_today": SCANS_TODAY,
        "last_scan_pht": LAST_SCAN_PHT,
    }
