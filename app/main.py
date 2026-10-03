import os
import datetime
from contextlib import asynccontextmanager

import requests
import numpy as np
import pandas as pd
from fastapi import FastAPI, Request, BackgroundTasks
from apscheduler.schedulers.background import BackgroundScheduler

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

PAIRS = ["XAUUSD", "GBPUSD", "EURUSD"]

SCANS_TODAY = 0
SCAN_DATE = None
LAST_SCAN_PHT = "N/A"
LAST_SIGNAL = {}

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

def fetch_m5_live(symbol: str):
    """Fetches recent M5 candles for live market scanning."""
    sym = f"{symbol[:3]}/{symbol[3:]}"
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": sym,
        "interval": "5min",
        "outputsize": 100,
        "timezone": "UTC",
        "apikey": TWELVE_DATA_API_KEY,
    }
    try:
        res = requests.get(url, params=params, timeout=10).json()
        if "values" not in res:
            return None
        values = res["values"]
        # Tanggalin ang hindi pa saradong candle
        if values:
            try:
                dt = datetime.datetime.strptime(values[0]["datetime"], "%Y-%m-%d %H:%M:%S")
                if datetime.datetime.utcnow() < dt + datetime.timedelta(minutes=5):
                    values = values[1:]
            except Exception:
                pass
        return values
    except Exception as e:
        print(f"Live fetch error for {symbol}: {e}")
        return None

def fetch_historical_m5_clean(symbol: str, outputsize: int = 2000):
    """Fetches M5 data from Twelve Data and strictly filters weekends and flat candles."""
    sym = f"{symbol[:3]}/{symbol[3:]}"
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": sym,
        "interval": "5min",
        "outputsize": outputsize,
        "timezone": "UTC",
        "apikey": TWELVE_DATA_API_KEY,
    }
    try:
        res = requests.get(url, params=params, timeout=15).json()
        if "values" not in res:
            print(f"Twelve Data Error for {symbol}: {res.get('message', res)}")
            return None
        
        raw_values = res["values"]
        df = pd.DataFrame(raw_values)
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        
        for col in ['open', 'high', 'low', 'close']:
            df[col] = df[col].astype(float)

        # Filter Weekend Candles
        df['weekday'] = df['datetime'].dt.weekday
        df = df[df['weekday'] < 5]

        # Filter Flat/Zero-Range Candles
        df = df[df['high'] > df['low']]

        return df.to_dict('records')
    except Exception as e:
        print(f"Data fetch error for {symbol}: {e}")
        return None

def calculate_ema(closes, period):
    if len(closes) < period:
        return None
    k = 2 / (period + 1)
    e = sum(closes[:period]) / period
    for v in closes[period:]:
        e = v * k + e * (1 - k)
    return e

def calculate_atr(candles_oldest_first, period=14):
    if len(candles_oldest_first) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles_oldest_first)):
        h = candles_oldest_first[i]['high']
        l = candles_oldest_first[i]['low']
        pc = candles_oldest_first[i-1]['close']
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period

def analyze_variant(symbol, window_newest_first, variant_id=1):
    if len(window_newest_first) < 60:
        return None

    dt = pd.to_datetime(window_newest_first[0]['datetime'])
    hour_utc = dt.hour

    # Session Killzone Filter (07:00 UTC - 19:00 UTC)
    if hour_utc < 7 or hour_utc > 19:
        return None

    oldest_first = list(reversed(window_newest_first))
    closes = [c['close'] for c in oldest_first]
    
    ema20 = calculate_ema(closes, 20)
    ema50 = calculate_ema(closes, 50)
    if not ema20 or not ema50:
        return None

    c0, o0 = window_newest_first[0]['close'], window_newest_first[0]['open']
    c1, o1 = window_newest_first[1]['close'], window_newest_first[1]['open']

    body_size = abs(c0 - o0)
    prev_body = abs(c1 - o1)
    body_mult = 1.5 if symbol == "EURUSD" else 1.2

    signal_type = None
    if c0 > ema20 > ema50 and c0 > o0 and body_size > prev_body * body_mult:
        signal_type = "BUY"
    elif c0 < ema20 < ema50 and c0 < o0 and body_size > prev_body * body_mult:
        signal_type = "SELL"

    if not signal_type:
        return None

    pip_factor = 0.1 if symbol == "XAUUSD" else 0.0001
    spread_pips = 3.0 if symbol == "XAUUSD" else (1.5 if symbol == "GBPUSD" else 1.2)
    spread = spread_pips * pip_factor

    if variant_id == 1:
        if symbol == "XAUUSD": sl_pips, tp_pips = 18.0, 36.0
        elif symbol == "GBPUSD": sl_pips, tp_pips = 12.0, 24.0
        else: sl_pips, tp_pips = 10.0, 20.0
    else:
        atr = calculate_atr(oldest_first, 14)
        if not atr: return None
        sl_pips = round((atr * 1.5) / pip_factor, 1)
        tp_pips = round((atr * 3.0) / pip_factor, 1)
        sl_pips = max(8.0, min(sl_pips, 25.0))

    if signal_type == "BUY":
        sl = round(c0 - (sl_pips * pip_factor), 2 if symbol == "XAUUSD" else 4)
        tp = round(c0 + (tp_pips * pip_factor), 2 if symbol == "XAUUSD" else 4)
    else:
        sl = round(c0 + (sl_pips * pip_factor), 2 if symbol == "XAUUSD" else 4)
        tp = round(c0 - (tp_pips * pip_factor), 2 if symbol == "XAUUSD" else 4)

    return {
        "pair": symbol, "type": signal_type, "entry": c0,
        "sl": sl, "tp": tp, "spread": spread, "time": window_newest_first[0]['datetime']
    }

def run_variant_simulation(records, pair, variant_id=1, timeout_candles=36):
    total_trades = wins = losses = timeouts = spread_cuts = 0
    net_r = 0.0
    
    i = 60
    n_records = len(records)

    while i < n_records - timeout_candles:
        window = list(reversed(records[i-60:i]))
        sig = analyze_variant(pair, window, variant_id=variant_id)

        if not sig:
            i += 1
            continue

        total_trades += 1
        entry_price = sig['entry']
        sl, tp, spread = sig['sl'], sig['tp'], sig['spread']
        sig_type = sig['type']

        effective_entry = entry_price + spread if sig_type == "BUY" else entry_price - spread
        result = None
        exit_offset = timeout_candles

        for n, fc in enumerate(records[i:i + timeout_candles]):
            high_p, low_p = fc['high'], fc['low']

            if sig_type == "BUY":
                hit_sl = low_p <= sl
                hit_tp = high_p >= tp
            else:
                hit_sl = high_p >= sl
                hit_tp = low_p <= tp

            if hit_sl and hit_tp:
                result, exit_offset = "loss", n + 1
                break
            elif hit_sl:
                result, exit_offset = "loss", n + 1
                break
            elif hit_tp:
                result, exit_offset = "win", n + 1
                break

        if result == "win":
            wins += 1
            net_r += 2.0
        elif result == "loss":
            losses += 1
            net_r -= 1.0
        else:
            last_close = records[i + timeout_candles - 1]['close']
            pnl = (last_close - effective_entry) if sig_type == "BUY" else (effective_entry - last_close)
            if pnl <= 0:
                spread_cuts += 1
                net_r -= 0.5
            else:
                timeouts += 1

        i += max(exit_offset, 1)

    return total_trades, wins, losses, timeouts, spread_cuts, round(net_r, 1)

def run_walkforward_backtest_task(chat_id: str):
    send_telegram_msg("⏳ *Fetching Clean M5 Historical Data & Running Backtest...*", chat_id)
    try:
        report = "📊 *WALK-FORWARD IN-SAMPLE BENCHMARK (CLEANED M5 DATA)*\n\n"
        
        for pair in PAIRS:
            records = fetch_historical_m5_clean(pair, outputsize=2000)
            if not records or len(records) < 500:
                report += f"• *{pair}*: Data Fetch Failed or Insufficient.\n\n"
                continue

            total_clean = len(records)
            split_idx = int(total_clean * 0.66)
            in_sample_records = records[:split_idx]

            report += f"🔹 *{pair}* (Clean In-Sample Candles: `{len(in_sample_records)}`):\n"
            
            for v_id in [1, 2]:
                v_name = "V1 (Fixed + Killzone + 36TO)" if v_id == 1 else "V2 (ATR Dynamic + Killzone)"
                t, w, l, to, sc, nr = run_variant_simulation(in_sample_records, pair, variant_id=v_id, timeout_candles=36)
                wr = round(w / (w + l) * 100, 1) if (w + l) > 0 else 0.0
                exp = round(nr / t, 2) if t > 0 else 0.0
                
                report += (
                    f"  • *{v_name}*:\n"
                    f"    - Trades: `{t}` | WR: `{wr}%` | Net R: `{nr}R` | Expectancy: `{exp}R`\n"
                    f"    - W/L/TO/SC: `{w}/{l}/{to}/{sc}`\n"
                )
            report += "\n"

        report += "⚠️ _Clean Data Benchmark Phase._"
        send_telegram_msg(report, chat_id)
    except Exception as err:
        send_telegram_msg(f"❌ Backtest Error: {err}", chat_id)

def manual_scan_task(chat_id: str):
    send_telegram_msg("🔍 *Scanning M5 setups on Live Market Data...*", chat_id)
    found = False
    for pair in PAIRS:
        data = fetch_m5_live(pair)
        if not data:
            continue
        # Convert to dict format suitable for analyze_variant
        clean_data = []
        for d in data:
            try:
                clean_data.append({
                    "open": float(d["open"]), "high": float(d["high"]),
                    "low": float(d["low"]), "close": float(d["close"]),
                    "datetime": d["datetime"]
                })
            except Exception:
                pass
        
        if len(clean_data) >= 60:
            sig = analyze_variant(pair, clean_data, variant_id=1)
            if sig:
                found = True
                msg = (
                    f"⚡ *M5 SMC SIGNAL DETECTED*\n\n"
                    f"• *Pair:* `{sig['pair']}` | *Action:* `{sig['type']}`\n"
                    f"• *Entry:* `{sig['entry']}`\n"
                    f"• *SL:* `{sig['sl']}` | *TP:* `{sig['tp']}`\n"
                    f"• *Time:* `{sig['time']}`"
                )
                send_telegram_msg(msg, chat_id)
    if not found:
        send_telegram_msg("ℹ️ *No active Killzone M5 setups detected right now.*", chat_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running:
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)

app = FastAPI(title="SMC Engine V2.3 - Cleaned Data Walk-Forward Engine", lifespan=lifespan)

@app.api_route("/telegram-webhook", methods=["GET", "POST"])
@app.api_route("/telegram/webhook", methods=["GET", "POST"])
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        update = await request.json()
        if "message" in update and "text" in update["message"]:
            chat_id = str(update["message"]["chat"]["id"])
            text = update["message"]["text"].strip().split("@")[0]

            if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
                return {"status": "ok"}

            if text == "/status":
                pht_time = pht_now().strftime("%Y-%m-%d %I:%M:%S %p PHT")
                msg = (
                    "📊 *ENGINE OPERATIONAL STATUS*\n\n"
                    "• *System Mode:* `SMC_CLEANED_WALKFORWARD_V2.3`\n"
                    "• *Paper Session:* `True`\n"
                    "• *Data Provider:* `TWELVE_DATA_SPOT`\n"
                    f"• *Current Time:* `{pht_time}`"
                )
                send_telegram_msg(msg, chat_id)

            elif text == "/scan":
                background_tasks.add_task(manual_scan_task, chat_id)

            elif text == "/backtest":
                background_tasks.add_task(run_walkforward_backtest_task, chat_id)

            elif text in ["/help", "/start"]:
                msg = (
                    "🤖 *AI TRADING BOT COMMANDS*\n\n"
                    "• `/status` - System status\n"
                    "• `/scan` - Force manual scan for live M5 setups\n"
                    "• `/backtest` - Run 60-Day In-Sample Clean Data Benchmark"
                )
                send_telegram_msg(msg, chat_id)
    except Exception as e:
        print(f"Webhook error: {e}")
    return {"status": "ok"}

@app.get("/status")
def status():
    return {"status": "ok", "mode": "SMC_CLEANED_WALKFORWARD_V2.3"}
