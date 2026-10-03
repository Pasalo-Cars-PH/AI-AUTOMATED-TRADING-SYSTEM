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

# Live alerts naka-OFF by default (negative expectancy pa). Set LIVE_ALERTS=on sa Render para buksan.
LIVE_ALERTS = os.getenv("LIVE_ALERTS", "off").lower() in ("on", "true", "1", "yes")

PAIRS = ["XAUUSD", "GBPUSD", "EURUSD"]
MIN_CANDLES = 60
FETCH_SIZE = 100            # live scan

PIP = {"XAUUSD": 0.1, "GBPUSD": 0.0001, "EURUSD": 0.0001}
DIGITS = {"XAUUSD": 2, "GBPUSD": 4, "EURUSD": 4}
SPREAD_PIPS = {"XAUUSD": 3.0, "GBPUSD": 1.5, "EURUSD": 1.2}

# ---- Backtest settings ----
TIMEOUT_CANDLES = 36        # 36 x M5 = 3 hours
SESSION_START_UTC = 7       # London open
SESSION_END_UTC = 19        # hanggang NY midday/afternoon
BT_TOTAL_DAYS = 180
BT_IS_DAYS = 120            # In-Sample (tuning); ang natira (60d) ay Out-of-Sample
ATR_PERIOD = 14
ATR_SL_MULT = 1.5           # TP = 2 x SL (1:2 RR)
MIN_SL_X_SPREAD = 5         # skip kapag SL < 5x spread (spread-dominated)
MAX_SL_PIPS = {"XAUUSD": 45.0, "GBPUSD": 25.0, "EURUSD": 25.0}
CACHE_TTL = 6 * 3600        # reuse ng history para tipid sa API credits

TD_MAX_OUTPUT = 5000
TD_MAX_PAGES = 15
TD_PAGE_DELAY = 9           # seconds (free plan = 8 credits/min)

SCANS_TODAY = 0
SCAN_DATE = None
LAST_SCAN_PHT = "N/A"
LAST_SIGNAL = {}
BACKTEST_RUNNING = False
DATA_CACHE = {}             # pair -> {"ts", "records", "split_idx", "removed"}
OOS_RUNS = {}               # variant -> ilang beses na tiningnan ang OOS

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
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(path, "rb") as f:
            requests.post(url, data={"chat_id": chat_id, "caption": caption},
                          files={"document": f}, timeout=60)
    except Exception as e:
        print(f"Error sending Telegram document: {e}")


def td_symbol(symbol: str) -> str:
    return f"{symbol[:3]}/{symbol[3:]}"


def td_get(params: dict):
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


def in_session(dt: datetime.datetime) -> bool:
    return SESSION_START_UTC <= dt.hour < SESSION_END_UTC and dt.weekday() < 5


# ------------------------------------------------------------------ live data
def fetch_m5_data(symbol: str):
    """Closed M5 candles, newest first."""
    params = {
        "symbol": td_symbol(symbol), "interval": "5min", "outputsize": FETCH_SIZE,
        "timezone": "UTC", "apikey": TWELVE_DATA_API_KEY,
    }
    try:
        res = td_get(params)
        if "values" not in res:
            print(f"Twelve Data error for {symbol}: {res.get('message', res)}")
            return None
        values = res["values"]
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


# ------------------------------------------------------------------ historical data + cleaning
def fetch_history_m5(symbol: str, days: int):
    """Raw M5 history (oldest first) gamit ang pagination."""
    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=days)
    rows = {}
    end_date = None

    for page in range(TD_MAX_PAGES):
        params = {
            "symbol": td_symbol(symbol), "interval": "5min", "outputsize": TD_MAX_OUTPUT,
            "timezone": "UTC", "apikey": TWELVE_DATA_API_KEY,
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
    if candles and now < parse_dt(candles[-1]["datetime"]) + datetime.timedelta(minutes=5):
        candles = candles[:-1]
    return candles


def is_market_open(dt: datetime.datetime) -> bool:
    """FX hours (summer): Sun 21:00 UTC -> Fri 21:00 UTC."""
    wd = dt.weekday()
    if wd == 5:
        return False
    if wd == 4 and dt.hour >= 21:
        return False
    if wd == 6 and dt.hour < 21:
        return False
    return True


def clean_candles(raw: list):
    """Tanggalin ang weekend/off-market at flat (zero-range) candles. Convert to float."""
    out = []
    removed_wk = removed_flat = 0
    for v in raw:
        dt = parse_dt(v["datetime"])
        if not is_market_open(dt):
            removed_wk += 1
            continue
        o, h, l, c = float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"])
        if h <= l:
            removed_flat += 1
            continue
        out.append({"datetime": v["datetime"], "_dt": dt,
                    "open": o, "high": h, "low": l, "close": c})
    return out, removed_wk, removed_flat


def get_dataset(pair: str):
    """Returns (dataset, fresh). Cached para hindi paulit-ulit ang API calls."""
    c = DATA_CACHE.get(pair)
    if c and (time.time() - c["ts"]) < CACHE_TTL:
        return c, False

    fetched_at = datetime.datetime.utcnow()
    raw = fetch_history_m5(pair, BT_TOTAL_DAYS)
    records, rm_wk, rm_flat = clean_candles(raw)
    if len(records) < MIN_CANDLES + TIMEOUT_CANDLES + 200:
        raise RuntimeError(f"{pair}: kulang ang malinis na data ({len(records)} candles)")

    split_dt = fetched_at - datetime.timedelta(days=BT_TOTAL_DAYS - BT_IS_DAYS)
    split_idx = next((k for k, r in enumerate(records) if r["_dt"] >= split_dt), len(records))

    c = {"ts": time.time(), "records": records, "split_idx": split_idx,
         "removed": (rm_wk, rm_flat), "raw": len(raw)}
    DATA_CACHE[pair] = c
    return c, True


# ------------------------------------------------------------------ strategy
def ema(values_oldest_first, period):
    k = 2 / (period + 1)
    e = sum(values_oldest_first[:period]) / period
    for v in values_oldest_first[period:]:
        e = v * k + e * (1 - k)
    return e


def calc_atr(window_newest_first, period=ATR_PERIOD):
    trs = []
    for k in range(period):
        h = float(window_newest_first[k]["high"])
        l = float(window_newest_first[k]["low"])
        pc = float(window_newest_first[k + 1]["close"])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return sum(trs) / period


def analyze_hybrid_scalp(symbol, candles):
    """candles: newest first. Base entry signal + fixed (V1) SL/TP."""
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
        pip_factor = PIP[symbol]
        digits = DIGITS[symbol]

        if symbol == "XAUUSD":
            sl_pips, tp_pips = 18.0, 36.0
        elif symbol == "GBPUSD":
            sl_pips, tp_pips = 12.0, 24.0
        else:
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
            "pair": symbol, "type": signal_type, "entry": c0, "sl": sl, "tp": tp,
            "sl_pips": float(sl_pips), "tp_pips": float(tp_pips),
            "score": score, "time": candles[0].get("datetime"),
        }
    return None


def apply_variant(sig, window, variant: int):
    """V1 = fixed pips. V2/V3 = ATR stops (1.5 ATR SL, 1:2 RR). Return None kung skip."""
    if variant == 1:
        return sig

    pair = sig["pair"]
    pf = PIP[pair]
    digits = DIGITS[pair]
    atr = calc_atr(window)
    sl_pips = round(ATR_SL_MULT * atr / pf, 1)

    if sl_pips < SPREAD_PIPS[pair] * MIN_SL_X_SPREAD or sl_pips > MAX_SL_PIPS[pair]:
        return None  # masyadong masikip (spread kakainin) o masyadong malapad

    tp_pips = sl_pips * 2.0
    d = 1 if sig["type"] == "BUY" else -1
    out = dict(sig)
    out["sl_pips"] = sl_pips
    out["tp_pips"] = tp_pips
    out["sl"] = round(sig["entry"] - d * sl_pips * pf, digits)
    out["tp"] = round(sig["entry"] + d * tp_pips * pf, digits)
    return out


# ------------------------------------------------------------------ backtest engine
def simulate_pair(pair: str, records: list, variant: int, start_idx: int, end_idx: int, sample: str):
    """Replay ng signal candles sa [start_idx, end_idx). Ang trade ay hindi lalampas ng end_idx."""
    spread = SPREAD_PIPS[pair]
    pf = PIP[pair]
    digits = DIGITS[pair]
    times = [r["_dt"] for r in records]
    trades = []

    i = max(start_idx + 1, MIN_CANDLES)   # i = index ng unang future candle; signal candle = i-1
    while i + TIMEOUT_CANDLES <= end_idx:
        sig_dt = times[i - 1]

        # Session killzone
        if not in_session(sig_dt):
            i += 1
            continue
        # Skip kapag may gap (weekend/daily break) sa window o sa pagitan ng signal at susunod na candle
        if (times[i] - times[i - 1]) > datetime.timedelta(minutes=10) or \
           (times[i - 1] - times[i - MIN_CANDLES]) > datetime.timedelta(minutes=5 * MIN_CANDLES + 30):
            i += 1
            continue

        window = records[i - MIN_CANDLES:i][::-1]   # newest first
        base = analyze_hybrid_scalp(pair, window)
        if not base:
            i += 1
            continue
        sig = apply_variant(base, window, variant)
        if not sig:
            i += 1
            continue

        direction = 1 if sig["type"] == "BUY" else -1
        entry, sl, tp, sl_pips = sig["entry"], sig["sl"], sig["tp"], sig["sl_pips"]
        one_r_price = entry + direction * sl_pips * pf
        be_active = False

        exit_reason = exit_price = exit_idx = None
        future = records[i:i + TIMEOUT_CANDLES]

        for n_bar, fc in enumerate(future):
            hi, lo = fc["high"], fc["low"]
            cur_sl = entry if be_active else sl

            if direction == 1:
                hit_sl, hit_tp, reached_1r = lo <= cur_sl, hi >= tp, hi >= one_r_price
            else:
                hit_sl, hit_tp, reached_1r = hi >= cur_sl, lo <= tp, lo <= one_r_price

            # Conservative: SL muna kapag pareho sa isang candle
            if hit_sl:
                exit_reason = "BE" if be_active else "SL"
                exit_price, exit_idx = cur_sl, i + n_bar
                break
            if hit_tp:
                exit_reason, exit_price, exit_idx = "TP", tp, i + n_bar
                break
            # V3: lilipat sa breakeven simula sa SUSUNOD na candle
            if variant == 3 and not be_active and reached_1r:
                be_active = True

        if exit_reason is None:
            exit_idx = i + len(future) - 1
            exit_price = records[exit_idx]["close"]
            exit_reason = "TIMEOUT"

        gross_pips = direction * (exit_price - entry) / pf
        net_pips = gross_pips - spread
        r_result = net_pips / sl_pips

        if exit_reason in ("TP", "TIMEOUT") and gross_pips > 0 and net_pips <= 0:
            exit_reason = "SPREAD_CUT"

        trades.append({
            "variant": f"V{variant}", "sample": sample, "pair": pair, "type": sig["type"],
            "entry_time": records[i - 1]["datetime"], "entry": round(entry, digits),
            "sl": sl, "tp": tp, "sl_pips": sl_pips,
            "exit_time": records[exit_idx]["datetime"], "exit_price": round(exit_price, digits),
            "exit_reason": exit_reason, "bars_held": exit_idx - i + 1,
            "spread_pips": spread, "gross_pips": round(gross_pips, 1),
            "net_pips": round(net_pips, 1), "r_result": round(r_result, 2),
            "score": sig["score"],
        })

        i = exit_idx + 1   # walang overlapping trades

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


def stat_line(label: str, st):
    if not st:
        return f"`{label}` walang trades\n"
    pf = "inf" if st["profit_factor"] == float("inf") else st["profit_factor"]
    r = st["reasons"]
    small = " ⚠️" if st["trades"] < 30 else ""
    return (
        f"`{label}` n={st['trades']}{small} WR={st['win_rate']}% "
        f"E={st['expectancy']}R PF={pf} DD={st['max_dd']}R "
        f"[TP{r.get('TP', 0)}/SL{r.get('SL', 0)}/BE{r.get('BE', 0)}/"
        f"TO{r.get('TIMEOUT', 0)}/SC{r.get('SPREAD_CUT', 0)}]\n"
    )


CSV_FIELDS = [
    "variant", "sample", "pair", "type", "entry_time", "entry", "sl", "tp", "sl_pips",
    "exit_time", "exit_price", "exit_reason", "bars_held", "spread_pips",
    "gross_pips", "net_pips", "r_result", "score",
]


def send_trades_csv(trades: list, prefix: str, chat_id: str):
    if not trades:
        return
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    path = f"/tmp/{prefix}_{stamp}.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(trades)
    send_telegram_document(path, f"Trade log — {len(trades)} trades", chat_id)
    try:
        os.remove(path)
    except Exception:
        pass


def load_all_datasets(chat_id: str):
    datasets = {}
    for pair in PAIRS:
        send_telegram_msg(f"📥 *{pair}*: kinukuha/chine-check ang {BT_TOTAL_DAYS}-day M5 data...", chat_id)
        ds, fresh = get_dataset(pair)
        datasets[pair] = ds
        rm_wk, rm_flat = ds["removed"]
        is_n = ds["split_idx"]
        send_telegram_msg(
            f"✅ *{pair}*: `{len(ds['records'])}` malinis na candles "
            f"(tinanggal: weekend `{rm_wk}`, flat `{rm_flat}`)\n"
            f"IS: `{is_n}` | OOS: `{len(ds['records']) - is_n}`",
            chat_id,
        )
        if fresh:
            time.sleep(TD_PAGE_DELAY)
    return datasets


def run_in_sample_task(chat_id: str):
    """/backtest -> In-Sample (unang 60 days) para sa V1, V2, V3."""
    global BACKTEST_RUNNING
    if BACKTEST_RUNNING:
        send_telegram_msg("⏳ May tumatakbong backtest pa. Hintayin muna.", chat_id)
        return
    BACKTEST_RUNNING = True
    try:
        if not TWELVE_DATA_API_KEY:
            send_telegram_msg("❌ Walang Twelve Data API key sa environment.", chat_id)
            return
        send_telegram_msg(
            f"⏳ *In-Sample backtest ({BT_IS_DAYS}d)* — cleaned data, killzone "
            f"{SESSION_START_UTC:02d}-{SESSION_END_UTC:02d} UTC, timeout {TIMEOUT_CANDLES} candles, with spread.\n"
            "Mga 2-4 minuto ito.", chat_id)

        datasets = load_all_datasets(chat_id)

        all_trades = []
        report = "📊 *IN-SAMPLE RESULTS (TUNING ONLY)*\n\n"
        names = {1: "V1 Fixed pips", 2: "V2 ATR stops", 3: "V3 ATR + BE@1R"}

        for v in (1, 2, 3):
            report += f"*{names[v]}*\n"
            v_trades = []
            for pair in PAIRS:
                ds = datasets[pair]
                tr = simulate_pair(pair, ds["records"], v, 0, ds["split_idx"], "IS")
                v_trades.extend(tr)
                report += stat_line(pair[:3], calc_stats(tr))
            report += stat_line("ALL", calc_stats(v_trades)) + "\n"
            all_trades.extend(v_trades)

        report += (
            "_E = expectancy kada trade (R), net ng spread. PF = profit factor._\n"
            "_Pumili ng ISANG variant lang, tapos `/oos 1|2|3`. Bawat silip sa OOS = mas mahina ang bisa._"
        )
        send_telegram_msg(report, chat_id)
        send_trades_csv(all_trades, "is_trades", chat_id)
    except Exception as err:
        send_telegram_msg(f"❌ Backtest Error: {err}", chat_id)
    finally:
        BACKTEST_RUNNING = False


def run_out_of_sample_task(chat_id: str, variant: int):
    """/oos <variant> -> Out-of-Sample (huling 30 days). Isang beses lang dapat."""
    global BACKTEST_RUNNING
    if BACKTEST_RUNNING:
        send_telegram_msg("⏳ May tumatakbong backtest pa. Hintayin muna.", chat_id)
        return
    BACKTEST_RUNNING = True
    try:
        if not TWELVE_DATA_API_KEY:
            send_telegram_msg("❌ Walang Twelve Data API key sa environment.", chat_id)
            return

        OOS_RUNS[variant] = OOS_RUNS.get(variant, 0) + 1
        send_telegram_msg(f"⏳ *Out-of-Sample (huling {BT_TOTAL_DAYS - BT_IS_DAYS}d), V{variant}...*", chat_id)
        datasets = load_all_datasets(chat_id)

        report = f"🧪 *OUT-OF-SAMPLE — V{variant}* (silip #{OOS_RUNS[variant]})\n\n"
        trades_all = []
        for pair in PAIRS:
            ds = datasets[pair]
            tr = simulate_pair(pair, ds["records"], variant, ds["split_idx"], len(ds["records"]), "OOS")
            trades_all.extend(tr)
            report += stat_line(pair[:3], calc_stats(tr))
        report += stat_line("ALL", calc_stats(trades_all)) + "\n"

        if OOS_RUNS[variant] > 1:
            report += "⚠️ _Ikalawang+ silip na ito sa OOS — hindi na ito totoong blind test._\n"
        report += "_Kung negative pa rin ang E dito, walang edge. Huwag mag-tweak para lang gumanda ang OOS._"
        send_telegram_msg(report, chat_id)
        send_trades_csv(trades_all, f"oos_v{variant}_trades", chat_id)
    except Exception as err:
        send_telegram_msg(f"❌ OOS Error: {err}", chat_id)
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
    if SCAN_DATE != now.date():
        SCAN_DATE = now.date()
        SCANS_TODAY = 0
    SCANS_TODAY += 1
    LAST_SCAN_PHT = now.strftime("%Y-%m-%d %I:%M:%S %p PHT")

    if not in_session(datetime.datetime.utcnow()):
        return  # killzone lang, kapareho ng backtest

    for pair in PAIRS:
        data = fetch_m5_data(pair)
        if not data:
            continue
        sig = analyze_hybrid_scalp(pair, data)
        if sig and LAST_SIGNAL.get(pair) != sig["time"]:
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
    if LIVE_ALERTS and not scheduler.running:
        scheduler.add_job(scheduled_market_scan, "interval", minutes=5,
                          max_instances=1, coalesce=True)
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)


app = FastAPI(title="SMC Scalp Engine V2.4 - Walk-Forward", lifespan=lifespan)


@app.api_route("/telegram-webhook", methods=["GET", "POST"])
@app.api_route("/telegram/webhook", methods=["GET", "POST"])
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        update = await request.json()
        if "message" in update and "text" in update["message"]:
            chat_id = str(update["message"]["chat"]["id"])
            parts = update["message"]["text"].strip().split()
            text = parts[0].split("@")[0] if parts else ""
            args = parts[1:]

            if TELEGRAM_CHAT_ID and chat_id != str(TELEGRAM_CHAT_ID):
                return {"status": "ok"}

            if text == "/status":
                msg = (
                    "📊 *ENGINE STATUS*\n\n"
                    "• *Mode:* `SMC_WALKFORWARD_V2.4`\n"
                    f"• *Live Alerts:* `{'ON' if LIVE_ALERTS else 'OFF'}`\n"
                    f"• *Scans Today:* `{SCANS_TODAY}`\n"
                    f"• *Last Scan:* `{LAST_SCAN_PHT}`\n"
                    f"• *OOS runs:* `{OOS_RUNS or 'wala pa'}`"
                )
                send_telegram_msg(msg, chat_id)

            elif text == "/scan":
                background_tasks.add_task(manual_scan_task, chat_id)

            elif text == "/backtest":
                background_tasks.add_task(run_in_sample_task, chat_id)

            elif text == "/oos":
                if args and args[0] in ("1", "2", "3"):
                    background_tasks.add_task(run_out_of_sample_task, chat_id, int(args[0]))
                else:
                    send_telegram_msg("Gamitin: `/oos 1`, `/oos 2`, o `/oos 3` (isang variant lang).", chat_id)

            elif text in ["/help", "/start"]:
                msg = (
                    "🤖 *COMMANDS*\n\n"
                    "• `/status` - system status\n"
                    "• `/scan` - manual M5 scan\n"
                    f"• `/backtest` - In-Sample ({BT_IS_DAYS}d) V1/V2/V3, cleaned data + spread + CSV\n"
                    f"• `/oos 1|2|3` - Out-of-Sample ({BT_TOTAL_DAYS - BT_IS_DAYS}d) para sa napiling variant"
                )
                send_telegram_msg(msg, chat_id)

    except Exception as e:
        print(f"Webhook processing error: {e}")

    return {"status": "ok"}


@app.api_route("/health", methods=["GET", "HEAD"])
def health():
    return {"status": "ok", "mode": "SMC_WALKFORWARD_V2.4"}


@app.get("/status")
def status():
    return {
        "mode": "SMC_WALKFORWARD_V2.4",
        "live_alerts": LIVE_ALERTS,
        "scans_today": SCANS_TODAY,
        "last_scan_pht": LAST_SCAN_PHT,
    }
