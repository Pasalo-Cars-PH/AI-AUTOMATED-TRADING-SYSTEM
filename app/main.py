import os, datetime, json, math, bisect, time, threading, random
from contextlib import asynccontextmanager
import requests, pandas as pd
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

MASTER_LIVE_ENABLE = False
PAPER_SCAN_PAUSED = False

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

PHT = pytz.timezone('Asia/Manila')
scheduler = BackgroundScheduler()

# ===== V7.6 SETTINGS =====
SL_D, TP_D = 1.8, 3.6      # RR 1:2
SPREAD_COST = 0.30         # USD per trade (spread+slippage) para sa backtest
MIN_LAYERS = max(3, min(7, int(os.getenv("MIN_LAYERS", "5"))))  # deterministic confluence gate; default 5/7
USE_ATR_SL = True          # SL/TP = ATR(10) multiples (live + backtest). False = fixed SL_D/TP_D
ATR_SL_MULT = 1.5
ATR_TP_MULT = 3.0          # RR 1:2
VERSION = "V8.0"

# Trade storage for real-time dashboard
TRADES_FILE = "/tmp/titan_trades_v6.json"
TRADES_FILE_PERSIST = "/mnt/data/titan_trades_v6.json"

def pht_now(): return datetime.datetime.now(PHT)
def format_time_pht(dt_str):
    try:
        dt = pd.to_datetime(dt_str)
        if dt.tzinfo is None: dt = pytz.utc.localize(dt)
        pht = dt.astimezone(PHT)
        return pht.strftime("%b %d, %I:%M %p PHT"), dt.strftime("%H:%M UTC")
    except: return str(dt_str)[:19], ""
def format_price(p): return f"{float(p):.2f}"

# ---------- TRADE STORAGE ----------
def get_seed_trades():
    return []   # wala nang fake seed

def load_trades():
    for path in [TRADES_FILE, TRADES_FILE_PERSIST]:
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    if data and len(data) > 0:
                        return data
        except: pass
    return get_seed_trades()

def save_trades(trades):
    for path in [TRADES_FILE, TRADES_FILE_PERSIST]:
        try:
            with open(path, 'w') as f:
                json.dump(trades, f, indent=2)
        except Exception as e:
            print(f"Save trades error {path}: {e}")

def log_new_trade(sig):
    trades = load_trades()
    trade_id = len(trades) + 1
    trade = {
        "id": trade_id,
        "time": sig.get('time', pht_now().isoformat()),
        "pht_time": format_time_pht(sig.get('time', ''))[0],
        "type": sig.get('type', 'BUY'),
        "entry": sig.get('entry', 0),
        "sl": sig.get('sl', 0),
        "tp": sig.get('tp', 0),
        "tf": sig.get('tf', 'M5'),
        "confluence": sig.get('confluence', 0),
        "model_score": sig.get('model_score', 0),
        "layers": sig.get('layers', []),
        "reason": sig.get('reason', ''),
        "status": "OPEN",
        "result": None,
        "r": None,
        "closed_at": None
    }
    trades.append(trade)
    save_trades(trades)
    print(f"Logged new trade #{trade_id} {trade['type']} {trade['entry']}")
    return trade_id

def update_trade_result(trade_id, result):
    trades = load_trades()
    for t in trades:
        if t['id'] == trade_id:
            t['status'] = "CLOSED"
            t['result'] = "WIN" if result == "WIN" else "LOSS"
            t['r'] = 2.0 if result == "WIN" else -1.0
            t['closed_at'] = pht_now().isoformat()
            save_trades(trades)
            return True
    return False

def calculate_stats(trades):
    closed = [t for t in trades if t.get('result') in ['WIN', 'LOSS']]
    wins = len([t for t in closed if t['result'] == 'WIN'])
    losses = len([t for t in closed if t['result'] == 'LOSS'])
    total = wins + losses
    net = sum([t.get('r', 0) for t in closed if t.get('r') is not None])
    wr = round(wins / total * 100, 1) if total > 0 else 0
    pf = round((wins * 2) / (losses * 1), 2) if losses > 0 else round(wins * 2, 2) if wins > 0 else 0
    exp = round(net / total, 2) if total > 0 else 0
    evolution = []
    rw = rl = 0
    rnet = 0
    for i, t in enumerate(closed):
        if t['result'] == 'WIN':
            rw += 1; rnet += 2.0
        else:
            rl += 1; rnet -= 1.0
        rt = rw + rl
        evolution.append({
            "trade": i + 1,
            "wr": round(rw / rt * 100, 1) if rt > 0 else 0,
            "pf": round((rw * 2) / (rl * 1), 2) if rl > 0 else 0,
            "exp": round(rnet / rt, 2) if rt > 0 else 0,
            "net": rnet,
            "result": t['result'],
            "time": t.get('pht_time', '')
        })
    return {
        "total_trades": len(trades), "closed_trades": total, "open_trades": len(trades) - total,
        "wins": wins, "losses": losses, "wr": wr, "pf": pf, "exp": exp, "net": net,
        "evolution": evolution, "trades": trades
    }

# ---------- TELEGRAM ----------
def send_telegram_msg(msg, chat_id=None):
    cid = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        if r.status_code != 200:
            requests.post(url, json={"chat_id": cid, "text": msg}, timeout=10)
    except: pass

def send_telegram_photo(photo_path, caption, chat_id=None):
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - PAPER ONLY", chat_id)
        return
    cid = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as f:
            files = {'photo': f}
            data = {'chat_id': cid, 'caption': caption, 'parse_mode': 'Markdown'}
            requests.post(url, files=files, data=data, timeout=15)
    except Exception as e:
        print(f"Photo send error: {e}")
        send_telegram_msg(caption, chat_id)

def generate_chart_with_markings(clean, sig, tf="M5"):
    # Wala pang chart generator sa file na ito (dati NameError ito at hindi nakakapag-send ng signal).
    # Return None = text message na lang ang ipapadala.
    return None

# ---------- BASIC INDICATORS ----------
def calculate_ema(closes, p):
    if len(closes) < p: return None
    k = 2 / (p + 1); e = sum(closes[:p]) / p
    for v in closes[p:]: e = v * k + e * (1 - k)
    return e

def calculate_rsi(closes, period=14):
    if len(closes) < period + 1: return 50
    gains = []; losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0)); losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_ichimoku(highs, lows, closes, tenkan=16, kijun=44, senkou_b=88):
    """Display lang sa pretrade page. HINDI na gamit sa signal."""
    if len(closes) < senkou_b:
        return None
    try:
        tenkan_sen = (max(highs[-tenkan:]) + min(lows[-tenkan:])) / 2
        kijun_sen = (max(highs[-kijun:]) + min(lows[-kijun:])) / 2
        senkou_a = (tenkan_sen + kijun_sen) / 2
        senkou_span_b = (max(highs[-senkou_b:]) + min(lows[-senkou_b:])) / 2
        chikou_period = 28
        chikou = closes[-1]
        past_close = closes[-chikou_period] if len(closes) > chikou_period else closes[0]
        cp = closes[-1]
        cloud_top = max(senkou_a, senkou_span_b)
        cloud_bottom = min(senkou_a, senkou_span_b)
        above = cp > cloud_top
        below = cp < cloud_bottom
        inside = not above and not below
        bull_cloud = senkou_a > senkou_span_b
        bear_cloud = senkou_a < senkou_span_b
        c_above = chikou > past_close
        c_below = chikou < past_close
        tk_bull = tenkan_sen > kijun_sen
        tk_bear = tenkan_sen < kijun_sen
        if above and bull_cloud and c_above and tk_bull: trend, simple, strength = "STRONG_BULL", "BULL", 90
        elif below and bear_cloud and c_below and tk_bear: trend, simple, strength = "STRONG_BEAR", "BEAR", 90
        elif above and bull_cloud: trend, simple, strength = "BULL", "BULL", 70
        elif below and bear_cloud: trend, simple, strength = "BEAR", "BEAR", 70
        elif inside: trend, simple, strength = "NEUTRAL_CLOUD", "NEUTRAL", 30
        else: trend, simple, strength = "WEAK", "NEUTRAL", 50
        return {
            "tenkan": tenkan_sen, "kijun": kijun_sen, "senkou_a": senkou_a, "senkou_b": senkou_span_b,
            "chikou": chikou, "cloud_top": cloud_top, "cloud_bottom": cloud_bottom,
            "cloud_thickness": abs(senkou_a - senkou_span_b), "current_price": cp,
            "above_cloud": above, "below_cloud": below, "inside_cloud": inside,
            "bullish_cloud": bull_cloud, "bearish_cloud": bear_cloud,
            "chikou_above": c_above, "chikou_below": c_below,
            "tk_bull_cross": tk_bull, "tk_bear_cross": tk_bear,
            "trend": trend, "trend_simple": simple, "strength": strength
        }
    except Exception as e:
        print(f"Ichimoku calc error: {e}")
        return None

# ---------- FIXED INDICATORS (V7.6) ----------
def _atr_series(highs, lows, closes, period):
    n = len(closes)
    atr = [None] * n
    if n <= period:
        return atr
    tr = [0.0] * n
    for i in range(1, n):
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1]))
    a = sum(tr[1:period+1]) / period
    atr[period] = a
    for i in range(period + 1, n):
        a = (a * (period - 1) + tr[i]) / period
        atr[i] = a
    return atr

def calculate_supertrend(highs, lows, closes, period=10, multiplier=3.0):
    """Proper SuperTrend: per-bar ATR + final band ratchet. Input: oldest -> newest."""
    try:
        n = len(closes)
        if n < period + 5:
            return None
        atr = _atr_series(highs, lows, closes, period)
        fub = [0.0] * n; flb = [0.0] * n; st = [0.0] * n; d = [1] * n
        s = period
        hl2 = (highs[s] + lows[s]) / 2
        fub[s] = hl2 + multiplier * atr[s]
        flb[s] = hl2 - multiplier * atr[s]
        d[s] = 1 if closes[s] >= hl2 else -1
        st[s] = flb[s] if d[s] == 1 else fub[s]
        for i in range(s + 1, n):
            hl2 = (highs[i] + lows[i]) / 2
            ub = hl2 + multiplier * atr[i]
            lb = hl2 - multiplier * atr[i]
            fub[i] = ub if (ub < fub[i-1] or closes[i-1] > fub[i-1]) else fub[i-1]
            flb[i] = lb if (lb > flb[i-1] or closes[i-1] < flb[i-1]) else flb[i-1]
            if d[i-1] == 1:
                d[i] = -1 if closes[i] < flb[i] else 1
            else:
                d[i] = 1 if closes[i] > fub[i] else -1
            st[i] = flb[i] if d[i] == 1 else fub[i]
        return {
            "trend": "BULL" if d[-1] == 1 else "BEAR",
            "supertrend": st[-1], "prev_supertrend": st[-2], "direction": d[-1],
            "upper_band": fub[-1], "lower_band": flb[-1], "atr": atr[-1],
        }
    except Exception as e:
        print(f"SuperTrend calc error: {e}")
        return None

def _wma_series(data, per):
    denom = per * (per + 1) / 2
    out = []
    for i in range(per - 1, len(data)):
        seg = data[i - per + 1:i + 1]
        out.append(sum(seg[j] * (j + 1) for j in range(per)) / denom)
    return out

def calculate_hma(closes, period=21):
    try:
        half = max(1, period // 2)
        sq = max(1, int(math.sqrt(period)))
        if len(closes) < period + sq:
            return None
        wh = _wma_series(closes, half)
        wf = _wma_series(closes, period)
        off = len(wh) - len(wf)
        diff = [2 * wh[i + off] - wf[i] for i in range(len(wf))]
        if len(diff) < sq:
            return None
        return _wma_series(diff, sq)[-1]
    except Exception as e:
        print(f"HMA error: {e}")
        return None

def calculate_adx(highs, lows, closes, period=14):
    """Real ADX (Wilder smoothed DX)."""
    try:
        n = len(closes)
        if n < period * 2 + 1:
            return None
        tr, pdm, mdm = [], [], []
        for i in range(1, n):
            tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i-1]), abs(lows[i] - closes[i-1])))
            up = highs[i] - highs[i-1]
            dn = lows[i-1] - lows[i]
            pdm.append(up if (up > dn and up > 0) else 0.0)
            mdm.append(dn if (dn > up and dn > 0) else 0.0)

        def calc(t, p, m):
            pdi = 100 * p / t if t else 0.0
            mdi = 100 * m / t if t else 0.0
            dx = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) else 0.0
            return pdi, mdi, dx

        t_s, p_s, m_s = sum(tr[:period]), sum(pdm[:period]), sum(mdm[:period])
        pdi, mdi, dx = calc(t_s, p_s, m_s)
        dxs = [dx]
        for i in range(period, len(tr)):
            t_s = t_s - t_s / period + tr[i]
            p_s = p_s - p_s / period + pdm[i]
            m_s = m_s - m_s / period + mdm[i]
            pdi, mdi, dx = calc(t_s, p_s, m_s)
            dxs.append(dx)
        if len(dxs) < period:
            return None
        adx = sum(dxs[:period]) / period
        for v in dxs[period:]:
            adx = (adx * (period - 1) + v) / period
        trend = "BULL" if pdi > mdi else "BEAR" if mdi > pdi else "NEUTRAL"
        return {"adx": adx, "plus_di": pdi, "minus_di": mdi, "trend": trend, "strong_trend": adx >= 20}
    except Exception as e:
        print(f"ADX calc error: {e}")
        return None

def compute_h1_trend(hh, hl, hc):
    """H1 SuperTrend(10,3) + price vs EMA50. Input oldest->newest, completed bars lang."""
    if len(hc) < 60:
        return None
    st = calculate_supertrend(hh, hl, hc, period=10, multiplier=3.0)
    e50 = calculate_ema(hc, 50)
    if not st or not e50:
        return None
    cur = hc[-1]
    if st['trend'] == "BULL" and cur > e50: t = "BULL"
    elif st['trend'] == "BEAR" and cur < e50: t = "BEAR"
    else: t = "NEUTRAL"
    return {"trend": t, "trend_simple": t, "strength": 70 if t != "NEUTRAL" else 30}

def is_bullish_engulfing(c0, c1):
    try:
        o0, cl0 = c0['open'], c0['close']
        o1, cl1 = c1['open'], c1['close']
        body0 = abs(cl0 - o0); body1 = abs(cl1 - o1)
        engulfs = (o0 <= min(cl1, o1) + body1 * 0.1) and (cl0 >= max(cl1, o1) - body1 * 0.1) and (body0 > body1 * 0.9)
        return (cl1 < o1) and (cl0 > o0) and engulfs
    except:
        return False

def is_bearish_engulfing(c0, c1):
    try:
        o0, cl0 = c0['open'], c0['close']
        o1, cl1 = c1['open'], c1['close']
        body0 = abs(cl0 - o0); body1 = abs(cl1 - o1)
        engulfs = (o0 >= max(cl1, o1) - body1 * 0.1) and (cl0 <= min(cl1, o1) + body1 * 0.1) and (body0 > body1 * 0.9)
        return (cl1 > o1) and (cl0 < o0) and engulfs
    except:
        return False

# ---------- DATA (NO SYNTHETIC) ----------
def fetch_data(symbol, interval, outputsize):
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": symbol, "interval": interval, "outputsize": outputsize, "timezone": "UTC", "apikey": TWELVE_DATA_API_KEY}
    try:
        if not TWELVE_DATA_API_KEY:
            print("ERROR: TWELVE_DATA_API_KEY not set!")
            return None
        res = requests.get(url, params=params, timeout=12).json()
        if "values" not in res:
            print(f"TwelveData error: {res}")
            return None
        return res["values"]
    except Exception as e:
        print(f"fetch_data exception: {e}")
        return None

_price_cache = {"price": 0, "time": None, "source": "INIT"}
_twelve_data_cache = {}

def get_free_gold_price():
    try:
        res = requests.get("https://api.gold-api.com/price/XAU", timeout=8).json()
        price = float(res.get("price", 0))
        if price > 1000:
            _price_cache["price"] = price
            _price_cache["source"] = "GOLD-API.COM"
            _price_cache["time"] = datetime.datetime.utcnow()
            return price
    except: pass
    return _price_cache["price"]

def fetch_data_with_fallback(symbol="XAU/USD", interval="5min", outputsize=100):
    """TwelveData only + symbol/interval scoped 2-min cache. No synthetic data."""
    now = datetime.datetime.utcnow()
    cache_key = (symbol.upper(), interval, int(outputsize))
    cached = _twelve_data_cache.get(cache_key)
    if cached and cached.get("data") and cached.get("time") and (now - cached["time"]).total_seconds() < 120:
        return cached["data"], "LIVE_CACHED_" + interval
    data = fetch_data(symbol, interval, outputsize)
    if data and len(data) >= min(60, outputsize):
        _twelve_data_cache[cache_key] = {"data": data, "time": now, "symbol": symbol, "interval": interval}
        return data, "LIVE_TWELVEDATA_" + interval
    print(f"No live data for {symbol} {interval} - NO TRADE (synthetic removed)")
    return None, "NO_DATA"

def fetch_live_tf(interval, symbol="XAU/USD"):
    vals, source = fetch_data_with_fallback(symbol, interval, 100)
    fetch_live_tf.last_source = source
    if not vals: return None
    try:
        dt = datetime.datetime.strptime(vals[0]["datetime"], "%Y-%m-%d %H:%M:%S")
        delta = 1 if interval == "1min" else 5 if interval == "5min" else 15
        if datetime.datetime.utcnow() < dt + datetime.timedelta(minutes=delta): vals = vals[1:]
    except: pass
    return vals
fetch_live_tf.last_source = "UNKNOWN"

def fetch_h1_supertrend_adx():
    """H1 trend: SuperTrend(10,3) + EMA50, completed bars lang."""
    try:
        vals, source = fetch_data_with_fallback("XAU/USD", "1h", 200)
        if not vals or len(vals) < 60:
            return None
        df = pd.DataFrame(vals)
        for col in ['high', 'low', 'close']:
            df[col] = df[col].astype(float)
        df = df.sort_values('datetime')
        try:
            last_dt = pd.to_datetime(df['datetime'].iloc[-1])
            if datetime.datetime.utcnow() < last_dt.to_pydatetime() + datetime.timedelta(hours=1):
                df = df.iloc[:-1]   # drop forming H1 bar
        except: pass
        return compute_h1_trend(list(df['high']), list(df['low']), list(df['close']))
    except Exception as e:
        print(f"fetch_h1_supertrend_adx error: {e}")
        return None

def fetch_h1_trend():
    """Returns string: BULL / BEAR / NEUTRAL / UNKNOWN."""
    r = fetch_h1_supertrend_adx()
    return r['trend_simple'] if r else "UNKNOWN"

def get_h1_full_status():
    """H1 status para sa pretrade page (EMA + Ichimoku display + combined V7.6 trend)."""
    try:
        vals, source = fetch_data_with_fallback("XAU/USD", "1h", 200)
        if not vals:
            return {"ema_trend": "UNKNOWN", "ichi": None, "combined": "UNKNOWN"}
        df = pd.DataFrame(vals)
        for col in ['close', 'high', 'low']:
            df[col] = df[col].astype(float)
        df = df.sort_values('datetime')
        closes = list(df['close']); highs = list(df['high']); lows = list(df['low'])
        e20 = calculate_ema(closes, 20); e50 = calculate_ema(closes, 50)
        ema_trend = "BULL" if e20 and e50 and e20 > e50 else "BEAR" if e20 and e50 and e20 < e50 else "UNKNOWN"
        ichi = calculate_ichimoku(highs, lows, closes, tenkan=16, kijun=44, senkou_b=88)
        return {"ema_trend": ema_trend, "ema20": e20, "ema50": e50, "ichi": ichi,
                "combined": fetch_h1_trend(), "source": source}
    except Exception as e:
        return {"ema_trend": "UNKNOWN", "ichi": None, "combined": "UNKNOWN", "error": str(e)}

# ---------- DETAILED ANALYZER (pretrade page) ----------
def analyze_titan_detailed(window, tf="M5", h1_trend=None):
    """Pretrade page view. Same gates/layers as analyze_titan_mtf V7.6."""
    result = {"timestamp": pht_now().isoformat(), "tf": tf, "h1_trend": h1_trend, "gates": [], "layers": [], "boosters": [],
              "candle": None, "indicators": None, "decision": "SKIP", "reason": "", "signal": None,
              "confluence": 0, "passed_layers": 0, "model_score": 0, "swept": False}
    if len(window) < 60:
        result["reason"] = f"Not enough bars {len(window)}<60"
        return result
    try:
        dt = pd.to_datetime(window[0]['datetime'])
        c0, c1, c2 = window[0], window[1], window[2]
        oldest = window[::-1]
        closes = [c['close'] for c in oldest]; highs = [c['high'] for c in oldest]; lows = [c['low'] for c in oldest]
        e20 = calculate_ema(closes, 20); e50 = calculate_ema(closes, 50)
        hma21 = calculate_hma(closes, 21); rsi = calculate_rsi(closes, 14)
        st = calculate_supertrend(highs, lows, closes, 10, 3.0); adx = calculate_adx(highs, lows, closes, 14)
        body = abs(c0['close'] - c0['open']); prev = abs(c1['close'] - c1['open']); rng = c0['high'] - c0['low']
        bull = is_bullish_engulfing(c0, c1); bear = is_bearish_engulfing(c0, c1)
        sc = 0
        if rng > 0:
            sc = (c0['close'] - c0['low']) / rng if bull else (c0['high'] - c0['close']) / rng
        result["candle"] = {"open": c0['open'], "high": c0['high'], "low": c0['low'], "close": c0['close'],
                            "body": body, "prev_body": prev, "range": rng, "sc": sc,
                            "is_bull_pin": bull, "is_bear_pin": bear, "datetime": str(c0.get('datetime', ''))}
        result["indicators"] = {"ema20": e20, "ema50": e50, "hma21": hma21, "rsi": rsi,
                                "supertrend": st['supertrend'] if st else None, "st_trend": st['trend'] if st else None,
                                "adx": adx['adx'] if adx else None}
        gates = []
        g1 = prev > 0 and body >= prev * 0.70
        gates.append({"id": 1, "name": "DISP (0.70x)", "desc": f"body {body:.2f} vs prev {prev:.2f}", "required": "0.70x",
                      "actual": round(body / prev, 2) if prev > 0 else 0, "pass": g1, "fail_reason": "" if g1 else "body too small"})
        g2 = bull or bear
        gates.append({"id": 2, "name": "ENGULFING", "desc": "Bull/Bear engulfing", "required": "Engulfing",
                      "actual": "BULL" if bull else "BEAR" if bear else "NONE", "pass": g2, "fail_reason": "" if g2 else "no engulfing"})
        ema_ok = bool(e20 and e50 and ((bull and c0['close'] > e20 > e50) or (bear and c0['close'] < e20 < e50)))
        gates.append({"id": 3, "name": "EMA + SC50%", "desc": f"EMA aligned, SC {sc*100:.0f}%", "required": "EMA aligned & SC>=50%",
                      "actual": f"SC{sc*100:.0f}%", "pass": ema_ok and sc >= 0.5, "fail_reason": "" if (ema_ok and sc >= 0.5) else "EMA/SC fail"})
        result["gates"] = gates
        if not all(g['pass'] for g in gates):
            result["reason"] = "Failed gate: " + ", ".join(g['name'] for g in gates if not g['pass'])
            return result
        ht = h1_trend.get('trend_simple') if isinstance(h1_trend, dict) else h1_trend
        layers = []
        layers.append({"id": 1, "name": "HMA21", "desc": "HMA vs EMA50", "pass": bool(hma21 and e50 and ((bull and hma21 > e50 and c0['close'] > hma21) or (bear and hma21 < e50 and c0['close'] < hma21)))})
        layers.append({"id": 2, "name": "SuperTrend", "desc": f"ST {st['trend'] if st else None}", "pass": bool(st and ((bull and st['trend'] == "BULL") or (bear and st['trend'] == "BEAR")))})
        layers.append({"id": 3, "name": "ADX+DI", "desc": f"ADX {adx['adx']:.1f}" if adx else "no ADX", "pass": bool(adx and adx['adx'] >= 20 and ((bull and adx['plus_di'] > adx['minus_di']) or (bear and adx['minus_di'] > adx['plus_di'])))})
        hi = max(c['high'] for c in window[:60]); lo = min(c['low'] for c in window[:60]); r = hi - lo
        layers.append({"id": 4, "name": "PD60", "desc": "premium/discount", "pass": bool(r > 0 and ((bull and c0['close'] <= lo + r * 0.6) or (bear and c0['close'] >= lo + r * 0.4)))})
        layers.append({"id": 5, "name": "FVG", "desc": "fair value gap", "pass": bool((bull and c0['low'] > c2['high'] and c0['low'] - c2['high'] > 0.03) or (bear and c0['high'] < c2['low'] and c2['low'] - c0['high'] > 0.03))})
        swept = bool((bull and c0['low'] <= min(c['low'] for c in window[1:11]) + 0.05) or (bear and c0['high'] >= max(c['high'] for c in window[1:11]) - 0.05))
        layers.append({"id": 6, "name": "SWEEP", "desc": "liquidity sweep", "pass": swept})
        layers.append({"id": 7, "name": "H1 aligned", "desc": f"H1 {ht}", "pass": (bull and ht == "BULL") or (bear and ht == "BEAR")})
        n = sum(1 for l in layers if l['pass'])
        conf = n / 7 * 100
        result.update({"layers": layers, "passed_layers": n, "confluence": conf, "swept": swept})
        blocked = (bull and ht == "BEAR") or (bear and ht == "BULL")
        result["boosters"] = [
            {"id": 1, "name": "KILL ZONE", "desc": "07-19 UTC", "required": "07-19 UTC", "actual": f"{dt.hour} UTC", "pass": 7 <= dt.hour <= 19},
            {"id": 2, "name": "H1 NOT OPPOSITE", "desc": "no counter-trend", "required": "not opposite", "actual": str(ht), "pass": not blocked},
            {"id": 3, "name": "RSI", "desc": f"RSI {rsi:.1f}", "required": "<=68 buy / >=32 sell", "actual": f"{rsi:.1f}", "pass": not ((bull and rsi > 68) or (bear and rsi < 32))},
        ]
        sig = analyze_titan_mtf(window, tf=tf, h1_trend=h1_trend)
        if sig:
            result["decision"] = sig["type"]
            result["signal"] = sig
            result["model_score"] = sig["model_score"]
            result["reason"] = sig["reason"]
        else:
            result["reason"] = f"Layers {n}/7 (need {MIN_LAYERS}) / kill zone / H1 / RSI filter"
        return result
    except Exception as e:
        import traceback; traceback.print_exc(); result["reason"] = f"Error: {e}"; return result

# ---------- SIGNAL LOGIC V7.6 ----------
def analyze_titan_mtf(window, tf="M5", h1_trend=None, min_layers=None):
    """V7.6 - window[0] = newest candle. 3 gates + 7 real scoring layers."""
    if len(window) < 60:
        return None
    dt = pd.to_datetime(window[0]['datetime'])
    if dt.hour < 7 or dt.hour > 19:
        return None

    oldest = window[::-1]
    closes = [c['close'] for c in oldest]
    highs = [c['high'] for c in oldest]
    lows = [c['low'] for c in oldest]

    e20 = calculate_ema(closes, 20)
    e50 = calculate_ema(closes, 50)
    if not e20 or not e50:
        return None

    c0, c1, c2 = window[0], window[1], window[2]
    body = abs(c0['close'] - c0['open'])
    prev = abs(c1['close'] - c1['open'])
    rng = c0['high'] - c0['low']
    if rng == 0 or prev == 0 or body < prev * 0.70:
        return None

    bullish = is_bullish_engulfing(c0, c1)
    bearish = is_bearish_engulfing(c0, c1)
    if not bullish and not bearish:
        return None
    candle_type = "Bullish_Engulfing" if bullish else "Bearish_Engulfing"

    if bullish and not (c0['close'] > e20 > e50):
        return None
    if bearish and not (c0['close'] < e20 < e50):
        return None

    sc = (c0['close'] - c0['low']) / rng if bullish else (c0['high'] - c0['close']) / rng
    if sc < 0.50:
        return None

    rsi = calculate_rsi(closes, 14)
    if bullish and rsi > 68:
        return None
    if bearish and rsi < 32:
        return None

    if isinstance(h1_trend, dict):
        ht = h1_trend.get('trend_simple') or h1_trend.get('trend')
    else:
        ht = h1_trend
    if (bullish and ht == "BEAR") or (bearish and ht == "BULL"):
        return None

    logs = []
    n = 0

    hma21 = calculate_hma(closes, 21)
    if hma21 and ((bullish and hma21 > e50 and c0['close'] > hma21) or
                  (bearish and hma21 < e50 and c0['close'] < hma21)):
        n += 1; logs.append("HMA21")

    st = calculate_supertrend(highs, lows, closes, period=10, multiplier=3.0)
    if st and ((bullish and st['trend'] == "BULL") or (bearish and st['trend'] == "BEAR")):
        n += 1; logs.append("ST")

    adx = calculate_adx(highs, lows, closes, period=14)
    adx_ok = False
    if adx and adx['adx'] >= 20:
        if (bullish and adx['plus_di'] > adx['minus_di']) or (bearish and adx['minus_di'] > adx['plus_di']):
            adx_ok = True
            n += 1; logs.append(f"ADX{int(adx['adx'])}")

    hi = max(c['high'] for c in window[:60])
    lo = min(c['low'] for c in window[:60])
    r = hi - lo
    if r > 0:
        if bullish and c0['close'] <= lo + r * 0.6:
            n += 1; logs.append("PD60")
        elif bearish and c0['close'] >= lo + r * 0.4:
            n += 1; logs.append("PD60")

    if (bullish and c0['low'] > c2['high'] and (c0['low'] - c2['high']) > 0.03) or \
       (bearish and c0['high'] < c2['low'] and (c2['low'] - c0['high']) > 0.03):
        n += 1; logs.append("FVG")

    l10 = [c['low'] for c in window[1:11]]
    h10 = [c['high'] for c in window[1:11]]
    swept = (bullish and c0['low'] <= min(l10) + 0.05) or (bearish and c0['high'] >= max(h10) - 0.05)
    if swept:
        n += 1; logs.append("SWEEP")

    if (bullish and ht == "BULL") or (bearish and ht == "BEAR"):
        n += 1; logs.append(f"H1_{ht}")

    if n < (MIN_LAYERS if min_layers is None else min_layers):
        return None

    conf = n / 7 * 100
    model_score = min(98, 44 + conf * 0.55 + (8 if swept else 0) + (5 if adx_ok else 0))

    sl_d, tp_d = SL_D, TP_D
    if USE_ATR_SL:
        atr_v = _atr_series(highs, lows, closes, 10)[-1]
        if atr_v:
            sl_d, tp_d = ATR_SL_MULT * atr_v, ATR_TP_MULT * atr_v
    entry = round(c0['close'], 2)
    sl = round(entry - sl_d if bullish else entry + sl_d, 2)
    tp = round(entry + tp_d if bullish else entry - tp_d, 2)
    return {
        "pair": "XAUUSD", "type": "BUY" if bullish else "SELL", "entry": entry, "sl": sl, "tp": tp,
        "time": window[0]['datetime'], "pinbar": candle_type, "h1": ht,
        "confluence": conf, "model_score": model_score, "layers": logs,
        "reason": f"{VERSION} {candle_type} {n}/7 layers | {'+'.join(logs)} | RR1:2 SL{sl_d:.2f} TP{tp_d:.2f}",
        "tf": "M5",
    }

# ---------- BACKTEST V7.6 ----------
def build_h1_from_m5(records):
    df = pd.DataFrame(records)
    df['datetime'] = pd.to_datetime(df['datetime'])
    df = df.set_index('datetime')
    h = df.resample('1h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'}).dropna()
    return h.reset_index().to_dict('records')

def sim_trades(records, tf="M5", h1_records=None, cost=SPREAD_COST, max_hold=36, atr_sl=None, atr_tp=None, min_layers=None):
    """records: oldest -> newest. Returns list ng trades (dict) na may R after cost.
    atr_sl/atr_tp = multiplier ng ATR(10) para sa SL/TP; None = fixed SL_D/TP_D."""
    if atr_sl is None and USE_ATR_SL:
        atr_sl, atr_tp = ATR_SL_MULT, ATR_TP_MULT      # config mode. Pass atr_sl=0 para fixed.
    n = len(records)
    h1 = h1_records or build_h1_from_m5(records)
    h1_times = [pd.Timestamp(x['datetime']) for x in h1]
    h1_cache = {}
    trades = []
    i = 60
    while i < n - max_hold - 1:
        window = records[i-60:i][::-1]
        t0 = pd.Timestamp(window[0]['datetime'])
        if t0.hour < 7 or t0.hour > 19:
            i += 1
            continue
        k = bisect.bisect_left(h1_times, t0.floor('1h'))   # completed H1 bars lang
        h1_trend = None
        if k >= 60:
            if k not in h1_cache:
                seg = h1[max(0, k-200):k]
                h1_cache[k] = compute_h1_trend([x['high'] for x in seg], [x['low'] for x in seg], [x['close'] for x in seg])
            h1_trend = h1_cache[k]

        sig = analyze_titan_mtf(window, tf=tf, h1_trend=h1_trend, min_layers=min_layers)
        if not sig:
            i += 1
            continue

        sl_d, tp_d = SL_D, TP_D
        if atr_sl:
            o = window[::-1]
            atr = _atr_series([c['high'] for c in o], [c['low'] for c in o], [c['close'] for c in o], 10)[-1]
            if not atr:
                i += 1
                continue
            sl_d, tp_d = atr_sl * atr, atr_tp * atr

        buy = sig['type'] == "BUY"
        entry = records[i]['open']                      # entry sa NEXT candle open
        sl = entry - sl_d if buy else entry + sl_d
        tp = entry + tp_d if buy else entry - tp_d
        fut = records[i:i+max_hold]
        pnl = None
        exit_j = len(fut) - 1
        for j, fc in enumerate(fut):
            if buy:
                if fc['low'] <= sl: pnl = -sl_d; exit_j = j; break     # SL muna (conservative)
                if fc['high'] >= tp: pnl = tp_d; exit_j = j; break
            else:
                if fc['high'] >= sl: pnl = -sl_d; exit_j = j; break
                if fc['low'] <= tp: pnl = tp_d; exit_j = j; break
        if pnl is None:                                  # timeout: mark-to-market
            last = fut[-1]['close']
            pnl = (last - entry) if buy else (entry - last)
        trades.append({"idx": i, "type": sig['type'], "hour": t0.hour, "sl_d": sl_d, "r": (pnl - cost) / sl_d})
        i += exit_j + 1                                  # skip bars habang open ang trade
    return trades

def summarize(trades):
    n = len(trades)
    if n == 0:
        return {"se": 0.0, "total": 0, "wins": 0, "losses": 0, "wr": 0, "net": 0.0, "exp": 0.0, "pf": 0, "be": None, "avg_sl": 0}
    rs = [t['r'] for t in trades]
    w = [x for x in rs if x > 0]
    l = [-x for x in rs if x <= 0]
    gw, gl = sum(w), sum(l)
    be = round((gl / len(l)) / ((gw / len(w)) + (gl / len(l))) * 100, 1) if w and l else None
    mean = sum(rs) / n
    se = (sum((x - mean) ** 2 for x in rs) / (n - 1) / n) ** 0.5 if n > 1 else 0.0
    return {"se": round(se, 2), "total": n, "wins": len(w), "losses": len(l), "wr": round(len(w) / n * 100, 1),
            "net": round(sum(rs), 2), "exp": round(sum(rs) / n, 3),
            "pf": round(gw / gl, 2) if gl > 0 else round(gw, 2), "be": be,
            "avg_sl": (lambda v: round(v, 2) if v >= 1 else round(v, 5))(sum(t['sl_d'] for t in trades) / n)}

def run_sim_tf(records, tf="M5", h1_records=None, cost=SPREAD_COST, max_hold=36):
    """Compat wrapper: total,wins,losses,wr,net,exp,pf (R, after cost)."""
    s = summarize(sim_trades(records, tf=tf, h1_records=h1_records, cost=cost, max_hold=max_hold))
    return s['total'], s['wins'], s['losses'], s['wr'], s['net'], s['exp'], s['pf']

def fetch_hist_paged(interval="5min", pages=5, size=5000, symbol="XAU/USD"):
    """Hatak ng mas maraming history gamit end_date paging. 1 credit/page."""
    url = "https://api.twelvedata.com/time_series"
    allv = {}
    end = None
    for _ in range(pages):
        params = {"symbol": symbol, "interval": interval, "outputsize": size,
                  "timezone": "UTC", "apikey": TWELVE_DATA_API_KEY}
        if end:
            params["end_date"] = end
        try:
            res = requests.get(url, params=params, timeout=40).json()
        except Exception as e:
            print(f"paged fetch error: {e}")
            break
        vals = res.get("values")
        if not vals:
            print(f"paged fetch stop: {res}")
            break
        for v in vals:
            allv[v['datetime']] = v
        oldest = min(v['datetime'] for v in vals)
        if end == oldest:
            break
        end = oldest
        time.sleep(8)
    if not allv:
        return None
    df = pd.DataFrame(list(allv.values()))
    df['datetime'] = pd.to_datetime(df['datetime'])
    for col in ['open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)
    df = df.sort_values('datetime').reset_index(drop=True)
    df = df[df['datetime'].dt.weekday < 5]
    df = df[df['high'] > df['low']]
    return df.to_dict('records')

_hist_cache = {"rec": None, "time": 0}
_job_lock = threading.Lock()      # isa lang na backtest/diag sa isang oras

def get_hist_cached(max_age_s=6*3600, force=False, pages=5, symbol="XAU/USD"):
    """Single-slot cache (iwas OOM sa Render). Iisang symbol lang ang nasa memory."""
    now = time.time()
    if (not force and _hist_cache["rec"] and now - _hist_cache["time"] < max_age_s
            and _hist_cache.get("pages", 0) >= pages and _hist_cache.get("symbol", "XAU/USD") == symbol):
        return _hist_cache["rec"]
    _hist_cache["rec"] = None            # palayain ang lumang data bago kumuha ng bago
    rec = fetch_hist_paged("5min", pages=pages, size=5000, symbol=symbol)
    if rec and len(rec) >= 1000:
        _hist_cache["rec"] = rec
        _hist_cache["time"] = now
        _hist_cache["pages"] = pages
        _hist_cache["symbol"] = symbol
    return rec

def _fmt(name, s):
    if s['total'] == 0:
        return f"{name}: 0 trades"
    be = f"{s['be']}%" if s['be'] else "-"
    return f"{name}: {s['total']}T | WR {s['wr']}% (BE {be}) | PF {s['pf']} | Exp {s['exp']}R ±{s['se']} | Net {s['net']}R"

def run_backtest(chat_id, pages=10, symbol="XAU/USD"):
    if STRATEGY == "SMC":
        return run_backtest_smc(chat_id, pages, symbol)
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - PAPER ONLY", chat_id)
        return
    if not _job_lock.acquire(blocking=False):
        send_telegram_msg("⏳ May tumatakbo pang /backtest o /diag. Hintayin muna matapos.", chat_id)
        return
    send_telegram_msg(f"⏳ TITAN {VERSION} backtest (paged data + 70/30 split)... ~1 min", chat_id)
    try:
        rec = get_hist_cached()
        if not rec or len(rec) < 1000:
            send_telegram_msg(f"⚠️ Kulang ang data ({len(rec) if rec else 0} bars). Try ulit mamaya.", chat_id)
            return
        cut = int(len(rec) * 0.7)
        tr = sim_trades(rec)     # isang sim sa ALL, hati by time (tama ang H1 warm-up sa OOS)
        sl_txt = f"SL {ATR_SL_MULT}xATR / TP {ATR_TP_MULT}xATR" if USE_ATR_SL else f"SL {SL_D} / TP {TP_D} fixed"
        msg = f"📊 TITAN {VERSION} | {len(rec)} bars | cost ${SPREAD_COST}/trade | MIN_LAYERS {MIN_LAYERS} | {sl_txt}\n\n"
        msg += _fmt("ALL", summarize(tr)) + "\n"
        msg += _fmt("IN-SAMPLE 70%", summarize([t for t in tr if t['idx'] < cut])) + "\n"
        msg += _fmt("OUT-OF-SAMPLE 30%", summarize([t for t in tr if t['idx'] >= cut])) + "\n\n"
        msg += "BE = breakeven WR pagkatapos ng cost. Panuorin ang OOS. Para sa mas malalim: /diag"
        send_telegram_msg(msg, chat_id)
    except Exception as e:
        import traceback; traceback.print_exc()
        send_telegram_msg(f"Err {e}", chat_id)
    finally:
        _job_lock.release()

def run_diag(chat_id, pages=10, symbol="XAU/USD"):
    """Diagnostics: cost, ATR SL/TP, BUY/SELL, oras, at kung may naidagdag ba ang layers."""
    if STRATEGY == "SMC":
        return run_diag_smc(chat_id, pages, symbol)
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - PAPER ONLY", chat_id)
        return
    if not _job_lock.acquire(blocking=False):
        send_telegram_msg("⏳ May tumatakbo pang /backtest o /diag. Hintayin muna matapos.", chat_id)
        return
    send_telegram_msg(f"🔬 TITAN {VERSION} DIAG... ~2 min", chat_id)
    try:
        rec = get_hist_cached()
        if not rec or len(rec) < 1000:
            send_telegram_msg(f"⚠️ Kulang ang data ({len(rec) if rec else 0} bars). Try ulit mamaya.", chat_id)
            return
        cut = int(len(rec) * 0.7)
        oos = lambda trs: summarize([t for t in trs if t['idx'] >= cut])

        fix_net = sim_trades(rec, atr_sl=0)
        fix_gross = sim_trades(rec, atr_sl=0, cost=0.0)
        atr_net = sim_trades(rec, atr_sl=1.5, atr_tp=3.0)
        atr_gross = sim_trades(rec, atr_sl=1.5, atr_tp=3.0, cost=0.0)

        m1 = f"🔬 DIAG {VERSION} | {len(rec)} bars | MIN_LAYERS {MIN_LAYERS}\n\n"
        m1 += "A) FIXED SL 1.8 / TP 3.6\n"
        m1 += _fmt("GROSS all", summarize(fix_gross)) + "\n" + _fmt("NET   all", summarize(fix_net)) + "\n"
        m1 += _fmt("NET   oos", oos(fix_net)) + "\n"
        m1 += "\nB) ATR 1.5x SL / 3.0x TP (RR 1:2)\n"
        sa = summarize(atr_net)
        m1 += _fmt("GROSS all", summarize(atr_gross)) + "\n"
        m1 += _fmt("NET   all", sa) + f" | avgSL ${sa['avg_sl']}\n"
        m1 += _fmt("NET   oos", oos(atr_net)) + "\n"
        # rolling stability: hati sa 4 pantay na bahagi ng panahon
        q = len(rec) // 4
        m1 += "\nF) STABILITY (ATR net, 4 hati ng panahon)\n"
        for qi in range(4):
            part = [t for t in atr_net if qi * q <= t['idx'] < (qi + 1) * q]
            m1 += _fmt(f"Q{qi+1}", summarize(part)) + "\n"
        send_telegram_msg(m1, chat_id)

        m2 = "C) BUY vs SELL (ATR net)\n"
        for typ in ("BUY", "SELL"):
            m2 += _fmt(typ, summarize([t for t in atr_net if t['type'] == typ])) + "\n"
        m2 += "\nD) ORAS UTC (ATR net)\n"
        for label, lo_h, hi_h in [("07-10 London", 7, 10), ("11-14 Overlap", 11, 14), ("15-19 NY", 15, 19)]:
            m2 += _fmt(label, summarize([t for t in atr_net if lo_h <= t['hour'] <= hi_h])) + "\n"

        m2 += "\nE) LAYERS sa ATR mode (net)\n"
        for ml in (0, 2, 3, 4):
            tr = sim_trades(rec, atr_sl=1.5, atr_tp=3.0, min_layers=ml)
            tag = " (gates lang)" if ml == 0 else ""
            m2 += _fmt(f"min {ml} all", summarize(tr)) + tag + "\n"
            m2 += _fmt(f"min {ml} oos", oos(tr)) + "\n"
        m2 += "\nKung walang pagbuti habang tumataas ang min layers, tanggalin ang layers (simple = mas kaunting overfit)."
        send_telegram_msg(m2, chat_id)
    except Exception as e:
        import traceback; traceback.print_exc()
        send_telegram_msg(f"Diag err {e}", chat_id)
    finally:
        _job_lock.release()

# ============================================================
# SMC STRATEGY (V8.0): PDH/PDL liquidity sweep + displacement/FVG, killzones lang.
# LAHAT NG PARAMETER AY NAKA-FIX BAGO TUMINGIN SA RESULTS. Huwag i-tune sa parehong data.
# ============================================================
STRATEGY = os.getenv("TITAN_STRATEGY", "SMC").upper()   # "SMC" o "ENGULF" (luma)
SMC_KZ = [(7, 10), (12, 16)]      # UTC hours, candle-open hour [start, end). London + NY
SMC_SWEEP_LOOKBACK = 12           # bars (1h) para sa sweep bago ang displacement
SMC_DISP = 0.8                    # displacement candle body >= 0.8 x ATR
SMC_GAP = 0.1                     # FVG gap >= 0.1 x ATR
SMC_SL_BUF = 0.1                  # SL = sweep extreme +/- 0.1 x ATR
SMC_RR = 2.0
SMC_MIN_RISK, SMC_MAX_RISK = 0.5, 5.0   # risk (entry->SL) sa ATR units
SMC_MAX_HOLD = 48                 # bars (4h)
SMC_LIMIT_WAIT = 6                # bars para sa limit-entry variant (backtest lang)
SPLIT_FRAC = 2 / 3                # 2/3 in-sample, 1/3 out-of-sample

SYMBOL_COST = {"XAU/USD": 0.30, "EUR/USD": 0.00008, "GBP/USD": 0.00010, "USD/JPY": 0.008}   # spread+slippage sa presyo

def norm_symbol(x):
    x = x.upper().replace("_", "/")
    if "/" not in x and len(x) == 6:
        x = x[:3] + "/" + x[3:]
    return x if x in SYMBOL_COST else None

def in_killzone(h):
    return any(a <= h < b for a, b in SMC_KZ)

def smc_day_levels(records):
    d = {}
    for r in records:
        day = pd.Timestamp(r['datetime']).date()
        e = d.get(day)
        if e is None:
            d[day] = [r['high'], r['low'], 1]
        else:
            e[0] = max(e[0], r['high']); e[1] = min(e[1], r['low']); e[2] += 1
    return d

def smc_prev_map(levels, min_bars=100):
    """day -> (PDH, PDL) ng huling buong araw bago nito (UTC calendar day)."""
    out = {}
    last = None
    for day in sorted(levels):
        out[day] = last
        if levels[day][2] >= min_bars:
            last = (levels[day][0], levels[day][1])
    return out

def smc_signal(win, pdh, pdl, explain=False):
    """win: oldest->newest (dict: open/high/low/close/datetime). Huling candle = signal candle (sarado na).
    Returns (sig|None, checks). Entry sa signal ay c0 close (market)."""
    checks = []
    def chk(name, ok, actual=""):
        if explain:
            checks.append({"name": name, "pass": bool(ok), "actual": str(actual)})
        return bool(ok)
    if len(win) < 30:
        chk("Data", False, f"{len(win)} bars")
        return None, checks
    c0, c1, c2 = win[-1], win[-2], win[-3]
    t0 = pd.Timestamp(c0['datetime'])
    if not chk("Killzone", in_killzone(t0.hour), f"{t0.hour}:{t0.minute:02d} UTC"):
        return None, checks
    if pdh is None or pdl is None:
        chk("PDH/PDL", False, "walang prev day")
        return None, checks
    chk("PDH/PDL", True, f"{pdh:.2f} / {pdl:.2f}")
    o = win[-40:]
    atr = _atr_series([c['high'] for c in o], [c['low'] for c in o], [c['close'] for c in o], 10)[-1]
    if not atr:
        chk("ATR", False, "none")
        return None, checks
    rng = win[-(SMC_SWEEP_LOOKBACK + 2):-1]            # bars hanggang c1
    hi_ext = max(b['high'] for b in rng)
    lo_ext = min(b['low'] for b in rng)
    swept_hi = hi_ext > pdh and c0['close'] < pdh      # wick sa taas ng PDH, balik sa loob
    swept_lo = lo_ext < pdl and c0['close'] > pdl
    if swept_hi and swept_lo:
        chk("Sweep", False, "parehong PDH at PDL (skip)")
        return None, checks
    if not chk("Sweep PDH/PDL", swept_hi or swept_lo, f"hi {hi_ext:.2f} lo {lo_ext:.2f}"):
        return None, checks
    side = "SELL" if swept_hi else "BUY"
    body1 = abs(c1['close'] - c1['open'])
    if side == "SELL":
        gap = c2['low'] - c0['high']; dir_ok = c1['close'] < c1['open']
    else:
        gap = c0['low'] - c2['high']; dir_ok = c1['close'] > c1['open']
    fvg_ok = dir_ok and body1 >= SMC_DISP * atr and gap >= SMC_GAP * atr
    if not chk("Displacement+FVG", fvg_ok, f"{side} body {body1/atr:.2f}xATR gap {gap/atr:.2f}xATR"):
        return None, checks
    entry = c0['close']
    ext = hi_ext if side == "SELL" else lo_ext
    sl = ext + SMC_SL_BUF * atr if side == "SELL" else ext - SMC_SL_BUF * atr
    risk = abs(sl - entry)
    if not chk("Risk size", SMC_MIN_RISK * atr <= risk <= SMC_MAX_RISK * atr, f"risk ${risk:.2f} = {risk/atr:.2f}xATR"):
        return None, checks
    tp = entry - SMC_RR * risk if side == "SELL" else entry + SMC_RR * risk
    if side == "SELL":
        fvg_lo, fvg_hi = c0['high'], c2['low']
    else:
        fvg_lo, fvg_hi = c2['high'], c0['low']
    level = "PDH" if side == "SELL" else "PDL"
    sig = {
        "pair": "XAUUSD", "type": side, "entry": round(entry, 5), "sl": round(sl, 5), "tp": round(tp, 5),
        "time": str(c0['datetime']), "level": level, "atr": atr, "risk": risk,
        "fvg_lo": fvg_lo, "fvg_hi": fvg_hi, "pinbar": f"SMC_{level}_sweep+FVG",
        "confluence": 0, "model_score": 0, "layers": [f"{level}_SWEEP", "DISP", "FVG", "KZ"],
        "reason": f"{VERSION} SMC {side} after {level} sweep + FVG | risk ${risk:.2f} ({risk/atr:.1f}xATR) RR1:{SMC_RR:g}",
        "tf": "M5",
    }
    return sig, checks

def _eval_trade(records, j0, buy, entry, sl, tp, max_hold, tp_on_first=True):
    """Returns (pnl sa presyo, exit_index). SL muna kapag sabay na tinamaan."""
    end = min(len(records), j0 + max_hold)
    for j in range(j0, end):
        fc = records[j]
        if buy:
            if fc['low'] <= sl: return -abs(entry - sl), j
            if (tp_on_first or j > j0) and fc['high'] >= tp: return abs(tp - entry), j
        else:
            if fc['high'] >= sl: return -abs(sl - entry), j
            if (tp_on_first or j > j0) and fc['low'] <= tp: return abs(entry - tp), j
    last = records[end - 1]['close']
    return ((last - entry) if buy else (entry - last)), end - 1

def sim_smc(records, mode="market", rr=None, cost=SPREAD_COST):
    """records: oldest->newest. mode: 'market' (entry sa next open, ito ang live) o 'limit' (50% FVG, backtest lang)."""
    rr = SMC_RR if rr is None else rr
    n = len(records)
    ts = [pd.Timestamp(r['datetime']) for r in records]
    prevmap = smc_prev_map(smc_day_levels(records))
    used = set()
    trades = []
    i = 40
    while i < n - SMC_MAX_HOLD - SMC_LIMIT_WAIT - 2:
        t0 = ts[i-1]
        if not in_killzone(t0.hour):
            i += 1
            continue
        pl = prevmap.get(t0.date())
        if not pl:
            i += 1
            continue
        sig, _ = smc_signal(records[i-40:i], pl[0], pl[1])
        if not sig:
            i += 1
            continue
        key = (t0.date(), sig['level'])
        if key in used:                       # isang attempt bawat level bawat araw
            i += 1
            continue
        used.add(key)
        buy = sig['type'] == "BUY"
        sl = sig['sl']
        if mode == "market":
            entry = records[i]['open']
            j0 = i
            risk = abs(entry - sl)
            if risk <= 0 or (buy and entry <= sl) or ((not buy) and entry >= sl):
                i += 1
                continue
        else:
            entry = (sig['fvg_lo'] + sig['fvg_hi']) / 2
            risk = abs(entry - sl)
            if not (SMC_MIN_RISK * sig['atr'] <= risk <= SMC_MAX_RISK * sig['atr']):
                i += 1
                continue
            j0 = None
            for j in range(i, i + SMC_LIMIT_WAIT):
                fc = records[j]
                if (buy and fc['low'] <= entry) or ((not buy) and fc['high'] >= entry):
                    j0 = j
                    break
            if j0 is None:
                i += 1
                continue
        tp = entry + rr * risk if buy else entry - rr * risk
        pnl, ej = _eval_trade(records, j0, buy, entry, sl, tp, SMC_MAX_HOLD, tp_on_first=(mode == "market"))
        trades.append({"idx": i, "type": sig['type'], "hour": t0.hour, "sl_d": risk, "atr": sig['atr'],
                       "level": sig['level'], "r": (pnl - cost) / risk})
        i = ej + 1
    return trades

def sim_smc_baseline(records, direction="RANDOM", sl_atr=1.5, rr=None, cost=SPREAD_COST, seed=7):
    """Null model: pasok sa killzone na walang sweep/FVG logic. Para makita kung may naidagdag ang SMC."""
    rr = SMC_RR if rr is None else rr
    rnd = random.Random(seed)
    n = len(records)
    ts = [pd.Timestamp(r['datetime']) for r in records]
    trades = []
    i = 40
    while i < n - SMC_MAX_HOLD - 2:
        if not in_killzone(ts[i-1].hour):
            i += 1
            continue
        o = records[i-40:i]
        atr = _atr_series([c['high'] for c in o], [c['low'] for c in o], [c['close'] for c in o], 10)[-1]
        if not atr:
            i += 1
            continue
        buy = (rnd.random() < 0.5) if direction == "RANDOM" else (direction == "BUY")
        entry = records[i]['open']
        risk = sl_atr * atr
        sl = entry - risk if buy else entry + risk
        tp = entry + rr * risk if buy else entry - rr * risk
        pnl, ej = _eval_trade(records, i, buy, entry, sl, tp, SMC_MAX_HOLD)
        trades.append({"idx": i, "type": "BUY" if buy else "SELL", "hour": ts[i-1].hour, "sl_d": risk, "atr": atr,
                       "level": "-", "r": (pnl - cost) / risk})
        i = ej + 1
    return trades

def smc_funnel(records):
    """Ilang killzone bars ang pumapasa sa bawat hakbang. Walang kinalaman sa PnL, kaya
    ligtas gamitin para tingnan kung masyadong mahigpit ang isang filter."""
    ts = [pd.Timestamp(r['datetime']) for r in records]
    prevmap = smc_prev_map(smc_day_levels(records))
    names = ["Killzone", "PDH/PDL", "Sweep PDH/PDL", "Displacement+FVG", "Risk size"]
    reached = [0] * (len(names) + 1)       # reached[k] = bars na pumasa sa unang k checks
    for i in range(40, len(records) + 1):
        t0 = ts[i-1]
        if not in_killzone(t0.hour):
            continue
        pl = prevmap.get(t0.date())
        sig, checks = smc_signal(records[i-40:i], pl[0] if pl else None, pl[1] if pl else None, explain=True)
        k = 0
        for c in checks:
            if c['pass']: k += 1
            else: break
        if sig: k = len(names)
        for q in range(k + 1):
            reached[q] += 1
    return names, reached

# ---------- SMC BACKTEST / DIAG ----------
def run_backtest_smc(chat_id, pages=10, symbol="XAU/USD"):
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - PAPER ONLY", chat_id)
        return
    if not _job_lock.acquire(blocking=False):
        send_telegram_msg("⏳ May tumatakbo pang /backtest o /diag. Hintayin muna matapos.", chat_id)
        return
    send_telegram_msg(f"⏳ TITAN {VERSION} SMC backtest {symbol}... {pages} pages (~{pages*10//60+1} min kung walang cache)", chat_id)
    try:
        cost = SYMBOL_COST[symbol]
        rec = get_hist_cached(pages=pages, symbol=symbol)
        if not rec or len(rec) < 3000:
            send_telegram_msg(f"⚠️ Kulang ang data ({len(rec) if rec else 0} bars). Try ulit mamaya.", chat_id)
            return
        cut = int(len(rec) * SPLIT_FRAC)
        days = len({pd.Timestamp(r['datetime']).date() for r in rec})
        tr = sim_smc(rec, "market", cost=cost)
        msg = (f"📊 TITAN {VERSION} SMC {symbol} | {len(rec)} bars (~{days} araw) | cost {cost:g}/trade\n"
               f"PDH/PDL sweep + FVG | KZ 07-10 & 12-16 UTC | SL sa sweep extreme | RR 1:{SMC_RR:g} | market entry\n\n")
        msg += _fmt("ALL", summarize(tr)) + "\n"
        msg += _fmt("IN-SAMPLE 2/3", summarize([t for t in tr if t['idx'] < cut])) + "\n"
        msg += _fmt("OUT-OF-SAMPLE 1/3", summarize([t for t in tr if t['idx'] >= cut])) + "\n\n"
        msg += "BE = breakeven WR pagkatapos ng cost. Para sa baseline at stability: /diag"
        send_telegram_msg(msg, chat_id)
    except Exception as e:
        import traceback; traceback.print_exc()
        send_telegram_msg(f"Err {e}", chat_id)
    finally:
        _job_lock.release()

def run_diag_smc(chat_id, pages=10, symbol="XAU/USD"):
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - PAPER ONLY", chat_id)
        return
    if not _job_lock.acquire(blocking=False):
        send_telegram_msg("⏳ May tumatakbo pang /backtest o /diag. Hintayin muna matapos.", chat_id)
        return
    send_telegram_msg(f"🔬 TITAN {VERSION} SMC DIAG {symbol}... {pages} pages (~{pages*10//60+2} min kung walang cache)", chat_id)
    try:
        cost = SYMBOL_COST[symbol]
        rec = get_hist_cached(pages=pages, symbol=symbol)
        if not rec or len(rec) < 3000:
            send_telegram_msg(f"⚠️ Kulang ang data ({len(rec) if rec else 0} bars). Try ulit mamaya.", chat_id)
            return
        cut = int(len(rec) * SPLIT_FRAC)
        days = len({pd.Timestamp(r['datetime']).date() for r in rec})
        oos = lambda trs: summarize([t for t in trs if t['idx'] >= cut])
        mk = sim_smc(rec, "market", cost=cost)
        mk_g = sim_smc(rec, "market", cost=0.0)
        lm = sim_smc(rec, "limit", cost=cost)
        s_mk = summarize(mk)

        m1 = f"🔬 SMC DIAG {VERSION} {symbol} | cost {cost:g} | {len(rec)} bars (~{days} araw) | {len(mk)} trades ({len(mk)/max(days,1):.2f}/araw)\n\n"
        m1 += f"A) MARKET entry, RR 1:{SMC_RR:g} (ito ang live)\n"
        m1 += _fmt("GROSS all", summarize(mk_g)) + "\n"
        m1 += _fmt("NET   all", s_mk) + f" | avg risk ${s_mk['avg_sl']}\n"
        m1 += _fmt("NET   oos", oos(mk)) + "\n"
        m1 += "\nB) LIMIT 50% FVG (backtest lang, hindi live)\n"
        m1 += _fmt("NET   all", summarize(lm)) + "\n" + _fmt("NET   oos", oos(lm)) + "\n"
        m1 += "\nC) RR variants (info lang, huwag piliin ang pinakamaganda)\n"
        for rr_v in (1.5, 3.0):
            t_rr = sim_smc(rec, "market", rr=rr_v, cost=cost)
            m1 += _fmt(f"RR {rr_v:g} all", summarize(t_rr)) + "\n" + _fmt(f"RR {rr_v:g} oos", oos(t_rr)) + "\n"
        names, reached = smc_funnel(rec)
        m1 += "\nG) FUNNEL (killzone bars na pumasa, hindi PnL)\n"
        m1 += f"Killzone bars: {reached[0]}\n"
        for k, nm in enumerate(names):
            m1 += f"→ {nm}: {reached[k+1]}\n"
        m1 += "Kung <60 trades ang lumabas, kulang ang sample para sa anumang konklusyon."
        send_telegram_msg(m1, chat_id)

        ratios = sorted(t['sl_d'] / t['atr'] for t in mk if t.get('atr'))
        ratio = ratios[len(ratios) // 2] if ratios else 1.5
        m2 = f"D) BASELINE: killzone entries na walang sweep/FVG (SL {ratio:.1f}xATR, RR {SMC_RR:g}, net)\n"
        base = {}
        for d in ("RANDOM", "BUY", "SELL"):
            base[d] = sim_smc_baseline(rec, d, sl_atr=ratio, cost=cost)
            m2 += _fmt(f"{d:6s}", summarize(base[d])) + "\n"
        if symbol in _pool_store and _pool_store[symbol]["pages"] > pages:
            m2 += f"\n(Hindi na-overwrite ang pool entry ng {symbol}: mas malaki ang naka-store na {_pool_store[symbol]['pages']} pages.)\n"
        else:
          _pool_store[symbol] = {"mk": mk, "oos": [t for t in mk if t['idx'] >= cut], "rand": base["RANDOM"],
                               "base": base, "pages": pages, "days": days}
        m2 += _fmt("SMC   ", s_mk) + "\n"
        m2 += _fmt("SMC SELL", summarize([t for t in mk if t['type'] == "SELL"])) + "  ← ikumpara sa SELL baseline\n"
        m2 += _fmt("SMC BUY ", summarize([t for t in mk if t['type'] == "BUY"])) + "  ← ikumpara sa BUY baseline\n"
        m2 += "→ Kung ang SMC ay hindi mas mataas sa baseline, walang naidagdag ang sweep/FVG logic.\n"

        m2 += "\nE) SIDE / SESSION (SMC net)\n"
        for lbl, flt in [("SELL (PDH sweep)", lambda t: t['type'] == "SELL"), ("BUY (PDL sweep)", lambda t: t['type'] == "BUY"),
                         ("London 07-10", lambda t: 7 <= t['hour'] < 10), ("NY 12-16", lambda t: 12 <= t['hour'] < 16)]:
            m2 += _fmt(lbl, summarize([t for t in mk if flt(t)])) + "\n"
        q = len(rec) // 4
        m2 += "\nF) STABILITY (SMC net, 4 hati ng panahon)\n"
        for qi in range(4):
            m2 += _fmt(f"Q{qi+1}", summarize([t for t in mk if qi * q <= t['idx'] < (qi + 1) * q])) + "\n"
        send_telegram_msg(m2, chat_id)
    except Exception as e:
        import traceback; traceback.print_exc()
        send_telegram_msg(f"Diag err {e}", chat_id)
    finally:
        _job_lock.release()

_pool_store = {}
HYPOTHESIS_USED = ("XAU/USD", "EUR/USD")   # post-hoc na tiningnan na; hindi puwedeng gamitin bilang ebidensya

def run_pool_smc(chat_id):
    """Pinagsamang resulta ng lahat ng symbol na na-/diag na (trade lists lang ang naka-store)."""
    if not _pool_store:
        send_telegram_msg("Wala pang /diag results. Mag-/diag 30 [symbol] muna (hal. /diag 30 EUR/USD).", chat_id)
        return
    lines, all_tr, oos_tr, rnd_tr = [], [], [], []
    for sym, d in _pool_store.items():
        lines.append(_fmt(f"{sym} ({d['pages']}p)", summarize(d['mk'])))
        all_tr += d['mk']; oos_tr += d['oos']; rnd_tr += d['rand']
    sa, so, sr = summarize(all_tr), summarize(oos_tr), summarize(rnd_tr)
    msg = "🧺 POOLED SMC (market, net, lahat ng symbol)\n" + "\n".join(lines) + "\n\n"
    msg += _fmt("POOL all", sa) + "\n" + _fmt("POOL oos", so) + "\n" + _fmt("POOL random baseline", sr) + "\n"
    if sa['se'] > 0:
        z0 = sa['exp'] / sa['se']
        zb = (sa['exp'] - sr['exp']) / ((sa['se'] ** 2 + sr['se'] ** 2) ** 0.5) if sr['total'] else 0
        msg += f"\nz vs zero: {z0:.1f} | z vs baseline: {zb:.1f} (kailangan ≥2 sa pareho, at positive sa karamihan ng symbol)"
    # PRE-REGISTERED HYPOTHESIS: napansin sa XAU/USD at EUR/USD (post-hoc) -> i-test LANG sa mga symbol na hindi pa nagamit
    fresh = [sym for sym in _pool_store if sym not in HYPOTHESIS_USED]
    msg += "\n🧪 HYPOTHESIS TEST (fresh symbols lang: " + (", ".join(fresh) if fresh else "wala pa") + ")\n"
    if fresh:
        sm = [t for sym in fresh for t in _pool_store[sym]['mk']]
        def _cmp(name, trs, base_trs):
            a, b = summarize(trs), summarize(base_trs)
            z = (a['exp'] - b['exp']) / ((a['se'] ** 2 + b['se'] ** 2) ** 0.5) if a['total'] and b['total'] and (a['se'] or b['se']) else 0
            return _fmt(name, a) + f"\n   baseline: Exp {b['exp']}R ±{b['se']} ({b['total']}T) | z vs baseline {z:.1f}\n"
        sells = [t for t in sm if t['type'] == "SELL"]
        bsell = [t for sym in fresh for t in _pool_store[sym]['base']['SELL']]
        lon = [t for t in sm if 7 <= t['hour'] < 10]
        blon = [t for sym in fresh for t in _pool_store[sym]['base']['RANDOM'] if 7 <= t['hour'] < 10]
        msg += _cmp("H1 SELL-only (PDH sweep)", sells, bsell)
        msg += _cmp("H2 London-only", lon, blon)
        msg += "Pasa kung z vs baseline ≥ 2 AT positive sa bawat fresh symbol. Dalawang hypothesis ang tine-test, kaya 2.5 ang mas tapat na bar."
    else:
        msg += "Mag-/diag 30 GBP/USD at /diag 30 USD/JPY, tapos /pool ulit."
    send_telegram_msg(msg, chat_id)

# ---------- SMC LIVE ----------
_smc_live_cache = {"recs": None, "time": None}
_smc_used_live = set()

def fetch_m5_live(n=900):
    now = datetime.datetime.utcnow()
    c = _smc_live_cache
    if c["recs"] and c["time"] and (now - c["time"]).total_seconds() < 60:
        return c["recs"]
    vals = fetch_data("XAU/USD", "5min", n)
    if not vals or len(vals) < 200:
        return None
    recs = []
    for v in reversed(vals):                   # newest-first -> oldest-first
        try:
            o, h, l, cl = float(v["open"]), float(v["high"]), float(v["low"]), float(v["close"])
            if h > l and o > 0 and cl > 0:
                recs.append({"datetime": pd.Timestamp(v["datetime"]), "open": o, "high": h, "low": l, "close": cl})
        except: pass
    if len(recs) < 200:
        return None
    try:
        if now < recs[-1]['datetime'].to_pydatetime() + datetime.timedelta(minutes=5):
            recs = recs[:-1]                   # drop forming candle
    except: pass
    c["recs"] = recs
    c["time"] = now
    return recs

def smc_live_signal(explain=False):
    recs = fetch_m5_live(900)
    if not recs:
        return None, [], None
    t0 = pd.Timestamp(recs[-1]['datetime'])
    age_min = (datetime.datetime.utcnow() - (t0.to_pydatetime() + datetime.timedelta(minutes=5))).total_seconds() / 60
    if age_min > 15:
        return None, [{"name": "Data fresh", "pass": False, "actual": f"{age_min:.0f} min old"}], recs
    pl = smc_prev_map(smc_day_levels(recs)).get(t0.date())
    pdh, pdl = pl if pl else (None, None)
    sig, checks = smc_signal(recs[-40:], pdh, pdl, explain=explain)
    return sig, checks, recs

def smc_scan(chat_id, auto=False):
    sig, checks, recs = smc_live_signal(explain=not auto)
    if recs is None:
        if not auto: send_telegram_msg("Data fail - no data, no trade", chat_id)
        return
    if sig:
        key = (pd.Timestamp(sig['time']).date(), sig['level'])
        if key in _smc_used_live:
            if not auto: send_telegram_msg(f"ℹ️ Na-log na ang {sig['level']} sweep setup ngayong araw.", chat_id)
            return
        _smc_used_live.add(key)
        trade_id = log_new_trade(sig)
        pht, utc = format_time_pht(sig['time'])
        caption = (f"{'🤖 AUTO' if auto else '⚡ MANUAL'} XAUUSD M5 SMC {VERSION} PAPER ID #{trade_id}\n"
                   f"• {sig['type']} after {sig['level']} sweep + FVG\n"
                   f"• Entry `{format_price(sig['entry'])}`\n"
                   f"• SL `{format_price(sig['sl'])}` TP `{format_price(sig['tp'])}` RR 1:{SMC_RR:g}\n"
                   f"• Risk `${sig['risk']:.2f}` ({sig['risk']/sig['atr']:.1f}xATR)\n"
                   f"• FVG zone `{sig['fvg_lo']:.2f}-{sig['fvg_hi']:.2f}`\n"
                   f"• Time `{pht}` ({utc})\n"
                   f"• PAPER ONLY - Close with /win {trade_id} or /loss {trade_id}")
        send_telegram_msg(caption, chat_id)
    elif not auto:
        lines = "\n".join(f"{'✅' if c['pass'] else '❌'} {c['name']}: {c['actual']}" for c in checks)
        send_telegram_msg(f"ℹ️ No SMC setup ({VERSION})\n{lines}", chat_id)

def smc_pretrade():
    sig, checks, recs = smc_live_signal(explain=True)
    out = {"timestamp": pht_now().isoformat(), "tf": "M5", "h1_trend": "n/a (SMC)", "version": VERSION,
           "data_source": "LIVE_TWELVEDATA_5min", "h1_full": {}, "ichi": None, "layers": [], "boosters": [],
           "indicators": {}, "passed_layers": 0, "confluence": 0, "model_score": 0}
    if not recs:
        out["error"] = "No data"
        return out
    c = recs[-1]
    out["live_price"] = c['close']
    out["candle"] = {"open": c['open'], "high": c['high'], "low": c['low'], "close": c['close'],
                     "body": abs(c['close'] - c['open']), "range": c['high'] - c['low'], "sc": 0,
                     "datetime": str(c['datetime'])}
    out["gates"] = [{"id": i + 1, "name": ck['name'], "desc": "", "required": "", "actual": ck['actual'],
                     "pass": ck['pass'], "fail_reason": "" if ck['pass'] else "failed"} for i, ck in enumerate(checks)]
    out["signal"] = sig
    out["decision"] = sig['type'] if sig else "SKIP"
    failed = [ck['name'] for ck in checks if not ck['pass']]
    out["reason"] = sig['reason'] if sig else ("Failed: " + ", ".join(failed) if failed else "No setup")
    return out


# ---------- SCAN ----------
def manual_scan(chat_id, auto=False):
    if PAPER_SCAN_PAUSED:
        if not auto: send_telegram_msg("PAPER SCAN PAUSED. Use /resume-paper.", chat_id)
        return
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - SAFETY LOCK PAPER ONLY", chat_id)
        return
    if STRATEGY == "SMC":
        return smc_scan(chat_id, auto)
    h1 = fetch_h1_supertrend_adx()
    data = fetch_live_tf("5min")
    if not data:
        if not auto: send_telegram_msg("Data fail - no data, no trade", chat_id)
        return
    clean = []
    for d in data:
        try:
            o = float(d["open"]); h = float(d["high"]); lo = float(d["low"]); c = float(d["close"])
            if h > lo and o > 0 and c > 0:
                clean.append({"open": o, "high": h, "low": lo, "close": c, "datetime": d["datetime"]})
        except: pass
    if len(clean) < 60:
        if not auto: send_telegram_msg("Not enough bars", chat_id)
        return
    sig = analyze_titan_mtf(clean, tf="M5", h1_trend=h1)
    if sig:
        trade_id = log_new_trade(sig)
        pht, utc = format_time_pht(sig['time'])
        caption = (f"{'🤖 AUTO' if auto else '⚡ MANUAL'} XAUUSD M5 {VERSION} PAPER ID #{trade_id}\n"
                   f"• {sig['pair']} {sig['type']} {sig['pinbar']}\n"
                   f"• Entry `{format_price(sig['entry'])}`\n"
                   f"• SL `{format_price(sig['sl'])}` TP `{format_price(sig['tp'])}` RR 1:2\n"
                   f"• Time `{pht}` ({utc})\n"
                   f"• Conf `{sig['confluence']:.0f}%` MODEL `{sig['model_score']:.0f}%`\n"
                   f"• Layers `{' + '.join(sig['layers'])}`\n"
                   f"• PAPER ONLY - logged to dashboard\n"
                   f"• Close with /win {trade_id} or /loss {trade_id}")
        chart_path = generate_chart_with_markings(clean, sig, tf="M5")
        if chart_path and os.path.exists(chart_path):
            send_telegram_photo(chart_path, caption, chat_id)
        else:
            send_telegram_msg(caption, chat_id)
    else:
        if not auto:
            h1s = h1['trend_simple'] if isinstance(h1, dict) else h1
            send_telegram_msg(f"ℹ️ No setup M5 {VERSION} PAPER ONLY\nH1 `{h1s}`\nTry ulit sa 5 mins.\nDashboard: /dashboard", chat_id)

def auto_scan_job():
    try:
        if MASTER_LIVE_ENABLE or PAPER_SCAN_PAUSED: return
        now_utc = datetime.datetime.utcnow()
        if not TELEGRAM_CHAT_ID: return
        if STRATEGY == "SMC":
            if not in_killzone((now_utc - datetime.timedelta(minutes=5)).hour): return
            smc_scan(TELEGRAM_CHAT_ID, auto=True)
            return
        if not (7 <= now_utc.hour <= 19): return
        print(f"[AUTO-SCAN {VERSION}] {now_utc} scanning M5...")
        manual_scan(TELEGRAM_CHAT_ID, auto=True)
    except Exception as e:
        print(f"Auto scan error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running:
        if STRATEGY == "SMC":
            # every 5 min, ilang segundo pagkatapos magsara ang M5 candle (killzone lang ang aktibo sa loob ng job)
            scheduler.add_job(auto_scan_job, 'cron', minute='*/5', second=40, id='titan_autoscan', replace_existing=True)
        else:
            scheduler.add_job(auto_scan_job, 'interval', minutes=15, id='titan_autoscan', replace_existing=True)
        scheduler.start()
        print(f"✅ TITAN {VERSION} auto-scan 07-19 UTC started!")
    yield
    if scheduler.running: scheduler.shutdown(wait=False)

app = FastAPI(title=f"TITAN {VERSION} M5", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "status": f"XAUUSD TITAN {VERSION} M5 PAPER",
        "mode": "PAPER",
        "master_enable": False,
        "kill_switch": True,
        "live_enabled": False,
        "time": pht_now().isoformat(),
        "dashboard": "/dashboard",
        "api": "/api/stats",
    }

@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": VERSION,
        "mode": "PAPER",
        "master_enable": False,
        "kill_switch": True,
        "live_enabled": False,
    }

@app.get("/status")
def status():
    return {
        "status": "ok",
        "version": VERSION,
        "mode": "PAPER",
        "master_enable": False,
        "kill_switch": True,
        "live_enabled": False,
    }

@app.get("/signal")
def strict_signal_lock():
    """Legacy safety endpoint: never returns an executable trade signal."""
    return JSONResponse({
        "symbol": "NONE",
        "action": "NONE",
        "reason": "STRICT_EXECUTION_LOCK_ACTIVE",
        "mode": "PAPER",
        "master_enable": False,
        "kill_switch": True,
    })

@app.get("/api/trades")
def api_trades():
    return JSONResponse(calculate_stats(load_trades()))

@app.get("/api/stats")
def api_stats():
    return JSONResponse(calculate_stats(load_trades()))

def _clean_live():
    data = fetch_live_tf("5min")
    if not data:
        return None
    clean = []
    for d in data:
        try:
            o = float(d["open"]); h = float(d["high"]); lo = float(d["low"]); c = float(d["close"])
            if h > lo and o > 0 and c > 0:
                clean.append({"open": o, "high": h, "low": lo, "close": c, "datetime": d["datetime"]})
        except: pass
    return clean

@app.get("/api/pretrade")
def api_pretrade():
    try:
        if STRATEGY == "SMC":
            return JSONResponse(smc_pretrade())
        h1_full = get_h1_full_status()
        h1 = h1_full.get("combined", "UNKNOWN")
        clean = _clean_live()
        source = getattr(fetch_live_tf, 'last_source', 'UNKNOWN')
        if not clean:
            return JSONResponse({"error": "No data", "timestamp": pht_now().isoformat(), "h1_full": h1_full})
        if len(clean) < 60:
            return JSONResponse({"error": f"Not enough bars {len(clean)}<60", "timestamp": pht_now().isoformat(), "h1_full": h1_full})
        detailed = analyze_titan_detailed(clean, tf="M5", h1_trend=h1)
        detailed["data_source"] = source
        detailed["api_key_set"] = bool(TWELVE_DATA_API_KEY)
        detailed["live_price"] = clean[0]['close']
        detailed["h1_full"] = h1_full
        detailed["h1_trend"] = h1
        detailed["ichi"] = h1_full.get("ichi")
        detailed["version"] = VERSION
        return JSONResponse(detailed)
    except Exception as e:
        import traceback
        return JSONResponse({"error": str(e), "trace": traceback.format_exc()[:500], "timestamp": pht_now().isoformat()})

@app.get("/api/signal")
def api_signal():
    try:
        if STRATEGY == "SMC":
            sig, checks, recs = smc_live_signal(explain=True)
            return JSONResponse({"signal": sig, "checks": checks, "timestamp": pht_now().isoformat()})
        h1 = fetch_h1_supertrend_adx()
        clean = _clean_live()
        if not clean:
            return JSONResponse({"signal": None, "reason": "No data"})
        sig = analyze_titan_mtf(clean, tf="M5", h1_trend=h1)
        if sig:
            return JSONResponse({"signal": sig, "h1": h1, "timestamp": pht_now().isoformat()})
        detailed = analyze_titan_detailed(clean, tf="M5", h1_trend=h1)
        return JSONResponse({"signal": None, "reason": detailed.get("reason", "No setup"), "detailed": detailed, "h1": h1})
    except Exception as e:
        return JSONResponse({"error": str(e)})

@app.get("/api/debug")
def api_debug():
    try:
        has_key = bool(TWELVE_DATA_API_KEY)
        key_preview = TWELVE_DATA_API_KEY[:4] + "..." if has_key else "NOT SET"
        url = "https://api.twelvedata.com/time_series"
        params = {"symbol": "XAU/USD", "interval": "5min", "outputsize": 5, "timezone": "UTC", "apikey": TWELVE_DATA_API_KEY}
        try:
            res = requests.get(url, params=params, timeout=15).json()
            has_values = "values" in res
            error_msg = res.get("message", res.get("code", "No message")) if not has_values else "OK"
        except Exception as e:
            res = {"exception": str(e)}; has_values = False; error_msg = str(e)
        gold_price = None
        try:
            gold_price = requests.get("https://api.gold-api.com/price/XAU", timeout=10).json().get("price")
        except Exception as e:
            gold_price = f"Error: {e}"
        return JSONResponse({
            "has_api_key": has_key, "key_preview": key_preview,
            "twelvedata_test": {"has_values": has_values, "error": error_msg, "raw_response": str(res)[:500]},
            "free_gold_api_price": gold_price,
            "data_source": getattr(fetch_live_tf, 'last_source', 'UNKNOWN'),
            "timestamp": pht_now().isoformat()
        })
    except Exception as e:
        import traceback
        return JSONResponse({"error": str(e), "trace": traceback.format_exc()[:500]})

@app.get("/api/live-price")
def api_live_price():
    try:
        td_price = None; td_error = None
        try:
            vals, src = fetch_data_with_fallback("XAU/USD", "5min", 100)
            if vals: td_price = float(vals[0]['close'])
        except Exception as e:
            td_error = str(e)
        free_price = None
        try:
            free_price = requests.get("https://api.gold-api.com/price/XAU", timeout=10).json().get("price")
        except: pass
        return JSONResponse({"twelvedata_price": td_price, "twelvedata_error": td_error,
                             "free_api_price": free_price, "timestamp": pht_now().isoformat()})
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/pretrade", response_class=HTMLResponse)
@app.get("/signal-dashboard", response_class=HTMLResponse)
@app.get("/gates", response_class=HTMLResponse)
def pretrade_dashboard():
    html = """
<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TITAN V7.6 PRE-TRADE</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#000;color:#fff;font-family:monospace;padding:8px;font-size:11px}
.header{border:2px solid #22c55e;padding:10px;margin-bottom:8px;background:#0a0a0a}
.header h1{color:#22c55e;font-size:14px}
.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:8px}
.card{border:1px solid #333;padding:8px;background:#0a0a0a}
.card.pass{border-color:#22c55e;background:#052e16}
.card.fail{border-color:#ef4444;background:#2e0a0a}
.card h3{font-size:10px;color:#888;margin-bottom:2px}
.card .status{font-size:12px;font-weight:bold}
.status.pass{color:#22c55e}
.status.fail{color:#ef4444}
.decision{border:2px solid #22c55e;padding:12px;text-align:center;margin:8px 0;font-size:14px;font-weight:bold}
.decision.execute{border-color:#22c55e;background:#052e16;color:#22c55e}
.decision.skip{border-color:#ef4444;background:#2e0a0a;color:#ef4444}
.candle{border:1px solid #333;padding:8px;background:#0a0a0a;margin-bottom:8px}
.btn{padding:6px 10px;border:1px solid #22c55e;background:#000;color:#22c55e;cursor:pointer;font-size:10px;margin:2px}
</style>
</head>
<body>
<div class="header">
<h1>🔍 TITAN V7.6 PRE-TRADE - 3 GATES / 7 LAYERS (need 3) <span style="color:#22c55e">● LIVE</span></h1>
<p>Bakit pumasa / bumagsak ang setup bago mag-signal. H1 = SuperTrend(10,3)+EMA50. Ichimoku box ay display lang.</p>
<p id="last" style="font-size:9px;color:#666"></p>
</div>
<div id="decision" class="decision skip">Loading...</div>
<div class="candle" id="candleInfo">Loading candle...</div>
<div class="candle" id="ichiInfo" style="border:1px solid #f59e0b; background:#1a1200">Loading H1...</div>
<h2 style="color:#22c55e;font-size:12px;margin:8px 0">🚪 GATES (must all PASS)</h2>
<div class="grid" id="gates"></div>
<h2 style="color:#22c55e;font-size:12px;margin:8px 0">📚 LAYERS</h2>
<div class="grid" id="layers"></div>
<h2 style="color:#22c55e;font-size:12px;margin:8px 0">🚀 FILTERS</h2>
<div class="grid" id="boosters"></div>
<div style="margin-top:12px">
<button class="btn" onclick="load()">🔄 REFRESH</button>
<button class="btn" onclick="window.open('/dashboard','_blank')">📊 PERFORMANCE DASHBOARD</button>
<button class="btn" onclick="window.open('/api/pretrade','_blank')">🔧 RAW API</button>
</div>
<script>
async function load(){
 try{
  const res = await fetch('/api/pretrade');
  const data = await res.json();
  if(data.error){ document.getElementById('decision').textContent = 'No data: '+data.error; return; }
  document.getElementById('last').textContent = 'Last: '+new Date().toLocaleString()+' | TF '+data.tf+' H1 '+data.h1_trend+' | '+data.timestamp;
  const dec = document.getElementById('decision');
  dec.textContent = data.decision+' - '+data.reason;
  dec.className = 'decision '+(data.decision==='BUY'||data.decision==='SELL'?'execute':'skip');
  const ci = data.candle||{};
  document.getElementById('candleInfo').innerHTML =
   `<b>CANDLE:</b> ${ci.datetime||''} O:${ci.open} H:${ci.high} L:${ci.low} C:${ci.close} Body:${(ci.body||0).toFixed(3)} Range:${(ci.range||0).toFixed(3)} SC:${((ci.sc||0)*100).toFixed(1)}%<br>`+
   `<b>INDICATORS:</b> EMA20:${(data.indicators?.ema20||0).toFixed(2)} EMA50:${(data.indicators?.ema50||0).toFixed(2)} RSI:${(data.indicators?.rsi||0).toFixed(1)} | Layers ${data.passed_layers||0}/7 | Source ${data.data_source||''} Price ${data.live_price||''}`;
  const ichi = data.ichi || data.h1_full?.ichi;
  const h1f = data.h1_full || {};
  document.getElementById('ichiInfo').innerHTML = `<b>H1 TREND (V7.6):</b> ${data.h1_trend} | EMA20/50 H1: ${h1f.ema_trend||''}` + (ichi ? ` | Ichimoku (display lang): ${ichi.trend} ${ichi.inside_cloud?'(inside cloud)':''}` : '');
  const gatesDiv = document.getElementById('gates'); gatesDiv.innerHTML='';
  (data.gates||[]).forEach(g=>{
   const d=document.createElement('div');
   d.className='card '+(g.pass?'pass':'fail');
   d.innerHTML=`<h3>GATE ${g.id} ${g.name}</h3><div class="status ${g.pass?'pass':'fail'}">${g.pass?'✅ PASS':'❌ FAIL'} - ${g.actual}</div><div style="font-size:9px;color:#888">${g.desc} | Req ${g.required}</div>${g.fail_reason?'<div style="font-size:9px;color:#ef4444">'+g.fail_reason+'</div>':''}`;
   gatesDiv.appendChild(d);
  });
  const layersDiv = document.getElementById('layers'); layersDiv.innerHTML='';
  (data.layers||[]).forEach(l=>{
   const d=document.createElement('div');
   d.className='card '+(l.pass?'pass':'fail');
   d.innerHTML=`<h3>LAYER ${l.id} ${l.name}</h3><div class="status ${l.pass?'pass':'fail'}">${l.pass?'✅ PASS':'❌ FAIL'}</div><div style="font-size:9px;color:#888">${l.desc}</div>`;
   layersDiv.appendChild(d);
  });
  const boostDiv = document.getElementById('boosters'); boostDiv.innerHTML='';
  (data.boosters||[]).forEach(b=>{
   const d=document.createElement('div');
   d.className='card '+(b.pass?'pass':'fail');
   d.innerHTML=`<h3>${b.name}</h3><div class="status ${b.pass?'pass':'fail'}">${b.pass?'✅ PASS':'❌ FAIL'} - ${b.actual}</div><div style="font-size:9px;color:#888">${b.desc} | Req ${b.required}</div>`;
   boostDiv.appendChild(d);
  });
  if(data.signal){
   dec.innerHTML+='<br>ENTRY '+data.signal.entry+' SL '+data.signal.sl+' TP '+data.signal.tp+' '+data.signal.type;
  }
 }catch(e){
  document.getElementById('decision').textContent='Error '+e;
 }
}
load();
setInterval(load, 30000);
</script>
</body></html>
"""
    return HTMLResponse(content=html)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>TITAN V7.6 PAPER DASHBOARD</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#000;color:#fff;font-family:'Courier New',monospace;padding:12px}
.header{border:1px solid #22c55e;padding:12px;margin-bottom:12px;background:#0a0a0a}
.header h1{color:#22c55e;font-size:16px;margin-bottom:4px}
.header p{color:#888;font-size:11px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-bottom:12px}
.card{border:1px solid #333;padding:10px;background:#0a0a0a}
.card.green{border-color:#22c55e}
.card.red{border-color:#ef4444}
.card h3{font-size:10px;color:#888;margin-bottom:4px}
.card .val{font-size:18px;font-weight:bold}
.card .val.green{color:#22c55e}
.card .val.red{color:#ef4444}
.card .val.white{color:#fff}
.evolution{border:1px solid #333;padding:10px;margin-bottom:12px;background:#0a0a0a;overflow-x:auto}
.evolution h3{font-size:11px;color:#22c55e;margin-bottom:8px}
.bar{display:flex;gap:2px;align-items:end;height:60px;margin:8px 0}
.bar div{flex:1;min-width:4px}
.win{background:#22c55e}
.loss{background:#ef4444}
table{width:100%;border-collapse:collapse;font-size:10px;margin-top:8px}
th,td{border:1px solid #333;padding:4px;text-align:left}
th{background:#111;color:#888}
.trades{max-height:300px;overflow-y:auto;border:1px solid #333;padding:8px;background:#0a0a0a}
.lesson{border:1px solid #f59e0b;padding:10px;background:#0a0a0a;margin-bottom:12px}
.lesson h3{color:#f59e0b;font-size:11px;margin-bottom:6px}
.lesson li{font-size:10px;margin:2px 0;color:#ccc}
.btn{padding:6px 10px;border:1px solid #22c55e;background:#000;color:#22c55e;cursor:pointer;font-size:10px;margin:2px}
#auto{color:#22c55e;font-size:10px}
</style>
</head>
<body>
<div class="header">
<h1>🔒 TITAN V7.6 M5 PAPER - HONEST DASHBOARD <span id="auto">● LIVE</span></h1>
<p>Live paper trades lang (walang fake seed). Breakeven sa RR 1:2 = 33.3% WR. Kailangan ng 100+ closed trades bago pagkatiwalaan.</p>
<p id="lastUpdate" style="color:#666;font-size:9px;margin-top:4px">Last update: loading...</p>
</div>

<div class="grid" id="statsGrid">
<div class="card"><h3>TOTAL TRADES</h3><div class="val white" id="total">0</div></div>
<div class="card green"><h3>WINS</h3><div class="val green" id="wins">0</div></div>
<div class="card red"><h3>LOSSES</h3><div class="val red" id="losses">0</div></div>
<div class="card"><h3>WIN RATE</h3><div class="val white" id="wr">0%</div></div>
<div class="card"><h3>PROFIT FACTOR</h3><div class="val white" id="pf">0</div></div>
<div class="card"><h3>EXPECTANCY</h3><div class="val white" id="exp">0R</div></div>
<div class="card green"><h3>NET R</h3><div class="val green" id="net">0R</div></div>
<div class="card"><h3>OPEN</h3><div class="val white" id="open">0</div></div>
</div>

<div class="evolution">
<h3>📈 EVOLUTION - running WR</h3>
<canvas id="wrChart" width="800" height="120" style="width:100%;background:#000;border:1px solid #222"></canvas>
<div class="bar" id="tradeBar"></div>
<div style="display:flex;gap:8px;margin-top:8px">
<button class="btn" onclick="fetchStats()">🔄 REFRESH</button>
</div>
</div>

<div class="lesson">
<h3>🎯 BREAKEVEN MATH - 1:2 RR</h3>
<ul>
<li>Need 33.3% WR para breakeven (1 win +2R per 2 losses -1R), bago pa ang spread.</li>
<li>Progress: <span id="progress">0/100</span> closed trades</li>
</ul>
</div>

<div class="trades">
<h3 style="font-size:11px;color:#22c55e;margin-bottom:8px">📋 LIVE PAPER TRADES (auto-logged via /scan → /win /loss)</h3>
<table id="tradesTable">
<tr><th>ID</th><th>Time</th><th>Type</th><th>Entry</th><th>SL</th><th>TP</th><th>Conf</th><th>Result</th><th>R</th></tr>
</table>
<p style="font-size:9px;color:#666;margin-top:6px">Commands: /scan, /win [id], /loss [id], /trades, /dashboard</p>
</div>

<script>
let tradesData = {evolution:[], trades:[]};

async function fetchStats(){
 try{
  const res = await fetch('/api/stats');
  const data = await res.json();
  tradesData = data;
  updateUI(data);
 }catch(e){
  console.error('Fetch error', e);
  document.getElementById('lastUpdate').textContent = 'Fetch failed - bot offline?';
 }
}

function updateUI(data){
 document.getElementById('total').textContent = data.total_trades;
 document.getElementById('wins').textContent = data.wins;
 document.getElementById('losses').textContent = data.losses;
 document.getElementById('wr').textContent = data.wr + '%';
 document.getElementById('pf').textContent = data.pf;
 document.getElementById('exp').textContent = data.exp + 'R';
 document.getElementById('net').textContent = data.net + 'R';
 document.getElementById('open').textContent = data.open_trades;
 document.getElementById('progress').textContent = data.closed_trades + '/100';
 document.getElementById('lastUpdate').textContent = 'Last update: ' + new Date().toLocaleString() + ' | Auto-refresh every 10s';

 const bar = document.getElementById('tradeBar');
 bar.innerHTML = '';
 data.trades.slice(-60).forEach(t=>{
  const d = document.createElement('div');
  d.style.height = t.result==='WIN' ? '40px' : '20px';
  d.className = t.result==='LOSS' ? 'loss' : 'win';
  d.style.opacity = t.result ? '1' : '0.3';
  d.title = `#${t.id} ${t.type} ${t.result||'OPEN'} ${t.r||0}R`;
  bar.appendChild(d);
 });

 const table = document.getElementById('tradesTable');
 table.innerHTML = '<tr><th>ID</th><th>Time</th><th>Type</th><th>Entry</th><th>SL</th><th>TP</th><th>Conf</th><th>Result</th><th>R</th></tr>';
 data.trades.slice().reverse().slice(0,20).forEach(t=>{
  const row = table.insertRow();
  row.innerHTML = `<td>#${t.id}</td><td>${t.pht_time||''}</td><td style="color:${t.type==='BUY'?'#22c55e':'#ef4444'}">${t.type}</td><td>${t.entry}</td><td>${t.sl}</td><td>${t.tp}</td><td>${t.confluence?.toFixed(0)||0}%</td><td style="color:${t.result==='WIN'?'#22c55e':t.result==='LOSS'?'#ef4444':'#888'}">${t.result||'OPEN'}</td><td>${t.r!==null&&t.r!==undefined?t.r+'R':'-'}</td>`;
 });

 updateChart(data.evolution);
}

function updateChart(evolution){
 const canvas = document.getElementById('wrChart');
 const ctx = canvas.getContext('2d');
 ctx.clearRect(0,0,canvas.width,canvas.height);
 ctx.strokeStyle = '#222';
 ctx.beginPath();
 const be = canvas.height - (33.3/100)*canvas.height;
 ctx.moveTo(0, be); ctx.lineTo(canvas.width, be); ctx.stroke();
 ctx.fillStyle = '#666';
 ctx.font = '10px monospace';
 ctx.fillText('33.3% breakeven', 0, be-2);
 if(!evolution || evolution.length<2) return;
 const maxTrades = Math.max(20, evolution.length);
 ctx.beginPath();
 evolution.forEach((p,i)=>{
  const x = (p.trade / maxTrades) * canvas.width;
  const y = canvas.height - (p.wr/100)*canvas.height;
  if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
 });
 ctx.strokeStyle = '#22c55e';
 ctx.lineWidth = 2;
 ctx.stroke();
 evolution.forEach(p=>{
  const x = (p.trade / maxTrades) * canvas.width;
  const y = canvas.height - (p.wr/100)*canvas.height;
  ctx.beginPath();
  ctx.arc(x,y,3,0,Math.PI*2);
  ctx.fillStyle = p.result==='WIN' ? '#22c55e' : '#ef4444';
  ctx.fill();
 });
}

fetchStats();
setInterval(fetchStats, 10000);
</script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


_seen_updates = []

@app.api_route("/telegram-webhook", methods=["GET", "POST"])
@app.api_route("/telegram/webhook", methods=["GET", "POST"])
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    global PAPER_SCAN_PAUSED
    try:
        update = await request.json()
        uid = update.get("update_id")
        if uid is not None:
            if uid in _seen_updates:
                return {"status": "dup"}
            _seen_updates.append(uid)
            if len(_seen_updates) > 200:
                del _seen_updates[:100]
        if "message" in update and "text" in update["message"]:
            cid = str(update["message"]["chat"]["id"])
            txt = update["message"]["text"].strip()
            txt_base = txt.split("@")[0].split()[0]
            args = txt.split()[1:]
            if TELEGRAM_CHAT_ID and cid != str(TELEGRAM_CHAT_ID): return {"status": "ok"}
            if MASTER_LIVE_ENABLE:
                send_telegram_msg("🚫 SAFETY LOCK ACTIVE - PAPER ONLY", cid)
                return {"status": "blocked"}
            if txt_base == "/status":
                h1 = "n/a (SMC)" if STRATEGY == "SMC" else fetch_h1_trend()
                stats = calculate_stats(load_trades())
                send_telegram_msg(f"🔒 *TITAN {VERSION} {STRATEGY} M5 PAPER*\nH1 `{h1}`\nTrades `{stats['total_trades']}` Closed `{stats['closed_trades']}` W `{stats['wins']}` L `{stats['losses']}` WR `{stats['wr']}%` PF `{stats['pf']}` Exp `{stats['exp']}R` Net `{stats['net']}R`\nDashboard /dashboard API /api/stats\nTime {pht_now().strftime('%Y-%m-%d %I:%M %p PHT')}", cid)
            elif txt_base in ("/scan", "/bestsetup"):
                if PAPER_SCAN_PAUSED:
                    send_telegram_msg("Paper scanning is paused. Use /resume-paper.", cid)
                else:
                    background_tasks.add_task(manual_scan, cid)
            elif txt_base == "/paperstatus":
                s = calculate_stats(load_trades())
                send_telegram_msg("PAPER STATUS\nMode PAPER | Scan %s | Live DISABLED\nOpen %s | Closed %s | WR %s%%\nNet %sR | PF %s | Exp %sR" % ("PAUSED" if PAPER_SCAN_PAUSED else "RUNNING", s["open_trades"], s["closed_trades"], s["wr"], s["net"], s["pf"], s["exp"]), cid)
            elif txt_base == "/positions":
                opens = [t for t in load_trades() if t.get("status") == "OPEN"]
                msg = "PAPER POSITIONS\n" + ("No open paper positions." if not opens else "\n".join("#%s %s %s | SL %s | TP %s" % (t["id"], t.get("type","?"), t.get("entry","?"), t.get("sl","?"), t.get("tp","?")) for t in opens[-10:]))
                send_telegram_msg(msg, cid)
            elif txt_base == "/performance":
                s = calculate_stats(load_trades())
                send_telegram_msg("PERFORMANCE\nTrades %s | Closed %s | W/L %s/%s | WR %s%% | PF %s | Exp %sR | Net %sR | Open %s" % (s["total_trades"], s["closed_trades"], s["wins"], s["losses"], s["wr"], s["pf"], s["exp"], s["net"], s["open_trades"]), cid)
            elif txt_base == "/risk":
                send_telegram_msg("RISK / SAFETY\nLive execution DISABLED\nMaster live enable FALSE\nKill switch ACTIVE\nRR 1:2 | ATR SL 1.5x\nMinimum confluence %s/7\nSynthetic fallback DISABLED\nExecution commands BLOCKED" % MIN_LAYERS, cid)
            elif txt_base == "/journal":
                trades = load_trades()
                msg = "PAPER JOURNAL - LAST 10\n" + ("No paper trades recorded." if not trades else "\n".join("#%s %s %s %s %sR" % (t["id"], t.get("pht_time",""), t.get("type","?"), t.get("result") or "OPEN", t.get("r") if t.get("r") is not None else "-") for t in trades[-10:]))
                send_telegram_msg(msg, cid)
            elif txt_base in ("/pause", "/pause-paper"):
                PAPER_SCAN_PAUSED = True
                send_telegram_msg("PAPER SCANS PAUSED. Use /resume-paper. Live execution remains DISABLED.", cid)
            elif txt_base in ("/resume-paper", "/resume"):
                PAPER_SCAN_PAUSED = False
                send_telegram_msg("PAPER SCANS RESUMED. Live execution remains DISABLED.", cid)
            elif txt_base in ("/backtest", "/diag"):
                pages, symbol = 10, "XAU/USD"
                for a_ in args:
                    if a_.isdigit():
                        pages = max(3, min(30, int(a_)))
                    elif norm_symbol(a_):
                        symbol = norm_symbol(a_)
                    else:
                        send_telegram_msg(f"Hindi kilalang '{a_}'. Symbols: {', '.join(SYMBOL_COST)}. Halimbawa: {txt_base} 30 EUR/USD", cid)
                        return {"status": "ok"}
                if STRATEGY == "SMC":
                    background_tasks.add_task(run_backtest if txt_base == "/backtest" else run_diag, cid, pages, symbol)
                else:
                    background_tasks.add_task(run_backtest if txt_base == "/backtest" else run_diag, cid, pages)
            elif txt_base == "/pool": background_tasks.add_task(run_pool_smc, cid)
            elif txt_base == "/dashboard":
                host = str(request.base_url).rstrip('/')
                send_telegram_msg(f"📊 *DASHBOARD*\n{host}/dashboard\nAPI {host}/api/stats\nPretrade {host}/pretrade\nClose with /win [id] or /loss [id]", cid)
            elif txt_base == "/trades":
                stats = calculate_stats(load_trades())
                msg = f"📋 *LIVE TRADES* Total `{stats['total_trades']}` Closed `{stats['closed_trades']}` Open `{stats['open_trades']}`\n"
                for t in stats['trades'][-10:]:
                    msg += f"#{t['id']} {t['type']} {t['entry']} {t.get('result') or 'OPEN'} {t.get('r') if t.get('r') is not None else '-'}R\n"
                send_telegram_msg(msg, cid)
            elif txt_base in ("/win", "/loss"):
                res = "WIN" if txt_base == "/win" else "LOSS"
                icon = "✅" if res == "WIN" else "❌"
                rv = "+2R" if res == "WIN" else "-1R"
                tid = None
                if args:
                    try: tid = int(args[0])
                    except: send_telegram_msg(f"Usage {txt_base} [id]", cid); return {"status": "ok"}
                else:
                    open_trades = [t for t in load_trades() if t.get('status') == 'OPEN']
                    if open_trades: tid = open_trades[-1]['id']
                if tid is None:
                    send_telegram_msg("No open trades", cid)
                elif update_trade_result(tid, res):
                    stats = calculate_stats(load_trades())
                    send_telegram_msg(f"{icon} Trade #{tid} {res} {rv} | WR {stats['wr']}% PF {stats['pf']} Exp {stats['exp']}R Net {stats['net']}R | /dashboard", cid)
                else:
                    send_telegram_msg(f"Trade #{tid} not found", cid)
            elif txt_base == "/testtrade":
                test_sig = {"type": "BUY", "entry": 4142.47, "sl": 4140.67, "tp": 4146.07, "time": pht_now().isoformat(),
                            "tf": "M5", "confluence": 60, "model_score": 70, "layers": ["TEST"], "reason": "TEST TRADE - dashboard testing"}
                tid = log_new_trade(test_sig)
                send_telegram_msg(f"🧪 Test trade #{tid} OPEN | /win {tid} or /loss {tid}", cid)
            elif txt_base == "/reset":
                try:
                    for path in [TRADES_FILE, TRADES_FILE_PERSIST]:
                        if os.path.exists(path):
                            os.remove(path)
                    send_telegram_msg("🔄 Reset: 0 trades. Fresh start.", cid)
                except Exception as e:
                    send_telegram_msg(f"Reset error {e}", cid)
            elif txt_base in ["/help", "/start"]:
                send_telegram_msg(f"🔒 *TITAN {VERSION} M5 PAPER*\n• /status • /scan • /backtest [pages] [symbol] • /diag [pages] [symbol] • /pool\n• /dashboard • /trades\n• /win [id] • /loss [id]\n• /testtrade • /reset (clears ALL trades)", cid)
    except Exception as e:
        print(e)
        import traceback; traceback.print_exc()
    return {"status": "ok"}
