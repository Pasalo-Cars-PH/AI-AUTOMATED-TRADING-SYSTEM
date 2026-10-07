import os, datetime, json, math, bisect, time
from contextlib import asynccontextmanager
import requests, pandas as pd
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

MASTER_LIVE_ENABLE = False

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

PHT = pytz.timezone('Asia/Manila')
scheduler = BackgroundScheduler()

# ===== V7.6 SETTINGS =====
SL_D, TP_D = 1.8, 3.6      # RR 1:2
SPREAD_COST = 0.30         # USD per trade (spread+slippage) para sa backtest
MIN_LAYERS = 3             # sa 7 layers. 3 = mas maraming trade, 4 = mas strict
USE_ATR_SL = True          # SL/TP = ATR(10) multiples (live + backtest). False = fixed SL_D/TP_D
ATR_SL_MULT = 1.5
ATR_TP_MULT = 3.0          # RR 1:2
VERSION = "V7.7"

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
    now = datetime.datetime.utcnow()
    c = _twelve_data_cache.get(interval)
    if c and c.get("data") and c.get("time") and (now - c["time"]).total_seconds() < 120 and len(c["data"]) >= outputsize:
        return c["data"], "LIVE_CACHED_" + interval
    data = fetch_data(symbol, interval, outputsize)
    if data and len(data) >= min(60, outputsize):
        _twelve_data_cache[interval] = {"data": data, "time": now}
        return data, "LIVE_TWELVEDATA_" + interval
    print(f"No live data for {interval} - NO TRADE (synthetic removed)")
    return None, "NO_DATA"

def fetch_live_tf(interval):
    vals, source = fetch_data_with_fallback("XAU/USD", interval, 100)
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
                df = df.iloc[:-1]
        except: pass
        return compute_h1_trend(list(df['high']), list(df['low']), list(df['close']))
    except Exception as e:
        print(f"fetch_h1_supertrend_adx error: {e}")
        return None

def fetch_h1_trend():
    r = fetch_h1_supertrend_adx()
    return r['trend_simple'] if r else "UNKNOWN"

def get_h1_full_status():
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

# ---------- SIGNAL LOGIC V7.6 ----------
def analyze_titan_mtf(window, tf="M5", h1_trend=None):
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

    if (bullish and c0['low'] > c2['high'] and (c0['low'] - c2['high']) > 0.03) or        (bearish and c0['high'] < c2['low'] and (c2['low'] - c0['high']) > 0.03):
        n += 1; logs.append("FVG")

    l10 = [c['low'] for c in window[1:11]]
    h10 = [c['high'] for c in window[1:11]]
    swept = (bullish and c0['low'] <= min(l10) + 0.05) or (bearish and c0['high'] >= max(h10) - 0.05)
    if swept:
        n += 1; logs.append("SWEEP")

    if (bullish and ht == "BULL") or (bearish and ht == "BEAR"):
        n += 1; logs.append(f"H1_{ht}")

    if n < MIN_LAYERS:
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
        "confluence": conf, "model_score": model_score, "ai": model_score, "layers": logs,
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

def sim_trades(records, tf="M5", h1_records=None, cost=SPREAD_COST, max_hold=36, atr_sl=None, atr_tp=None):
    if atr_sl is None and USE_ATR_SL:
        atr_sl, atr_tp = ATR_SL_MULT, ATR_TP_MULT
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
        k = bisect.bisect_left(h1_times, t0.floor('1h'))
        h1_trend = None
        if k >= 60:
            if k not in h1_cache:
                seg = h1[max(0, k-200):k]
                h1_cache[k] = compute_h1_trend([x['high'] for x in seg], [x['low'] for x in seg], [x['close'] for x in seg])
            h1_trend = h1_cache[k]

        sig = analyze_titan_mtf(window, tf=tf, h1_trend=h1_trend)
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
        entry = records[i]['open']
        sl = entry - sl_d if buy else entry + sl_d
        tp = entry + tp_d if buy else entry - tp_d
        fut = records[i:i+max_hold]
        pnl = None
        exit_j = len(fut) - 1
        for j, fc in enumerate(fut):
            if buy:
                if fc['low'] <= sl: pnl = -sl_d; exit_j = j; break
                if fc['high'] >= tp: pnl = tp_d; exit_j = j; break
            else:
                if fc['high'] >= sl: pnl = -sl_d; exit_j = j; break
                if fc['low'] <= tp: pnl = tp_d; exit_j = j; break
        if pnl is None:
            last = fut[-1]['close']
            pnl = (last - entry) if buy else (entry - last)
        trades.append({"idx": i, "type": sig['type'], "hour": t0.hour, "sl_d": sl_d, "r": (pnl - cost) / sl_d})
        i += exit_j + 1
    return trades

def summarize(trades):
    n = len(trades)
    if n == 0:
        return {"total": 0, "wins": 0, "losses": 0, "wr": 0, "net": 0.0, "exp": 0.0, "pf": 0, "be": None, "avg_sl": 0}
    rs = [t['r'] for t in trades]
    w = [x for x in rs if x > 0]
    l = [-x for x in rs if x <= 0]
    gw, gl = sum(w), sum(l)
    if w and l:
        be = round((gl / len(l)) / ((gw / len(w)) + (gl / len(l))) * 100, 1)
    else:
        be = None
    return {"total": n, "wins": len(w), "losses": len(l), "wr": round(len(w) / n * 100, 1),
            "net": round(sum(rs), 2), "exp": round(sum(rs) / n, 3),
            "pf": round(gw / gl, 2) if gl > 0 else round(gw, 2), "be": be,
            "avg_sl": round(sum(t['sl_d'] for t in trades) / n, 2)}

def run_sim_tf(records, tf="M5", h1_records=None, cost=SPREAD_COST, max_hold=36):
    s = summarize(sim_trades(records, tf=tf, h1_records=h1_records, cost=cost, max_hold=max_hold))
    return s['total'], s['wins'], s['losses'], s['wr'], s['net'], s['exp'], s['pf']

def fetch_hist_paged(interval="5min", pages=3, size=5000):  # FIXED 5->3 pages
    url = "https://api.twelvedata.com/time_series"
    allv = {}
    end = None
    for _ in range(pages):
        params = {"symbol": "XAU/USD", "interval": interval, "outputsize": size,
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
        time.sleep(2)  # FIXED 8->2s
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

def get_hist_cached(max_age_s=12*3600, force=False):  # FIXED 6h->12h
    now = time.time()
    if not force and _hist_cache["rec"] and now - _hist_cache["time"] < max_age_s:
        return _hist_cache["rec"]
    rec = fetch_hist_paged("5min", pages=3, size=5000)
    if rec and len(rec) >= 1000:
        _hist_cache["rec"] = rec
        _hist_cache["time"] = now
    return rec

def _fmt(name, s):
    if s['total'] == 0:
        return f"{name}: 0 trades"
    be = f"{s['be']}%" if s['be'] else "-"
    return f"{name}: {s['total']}T | WR {s['wr']}% (BE {be}) | PF {s['pf']} | Exp {s['exp']}R | Net {s['net']}R"

def run_backtest(chat_id):
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - PAPER ONLY", chat_id)
        return
    send_telegram_msg(f"⏳ TITAN {VERSION} backtest (paged data + 70/30 split)... ~1 min", chat_id)
    try:
        rec = get_hist_cached()
        if not rec or len(rec) < 1000:
            send_telegram_msg(f"⚠️ Kulang ang data ({len(rec) if rec else 0} bars). Try ulit mamaya.", chat_id)
            return
        cut = int(len(rec) * 0.7)
        tr = sim_trades(rec)
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

def run_diag(chat_id):
    global MIN_LAYERS
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - PAPER ONLY", chat_id)
        return
    send_telegram_msg(f"🔬 TITAN {VERSION} DIAG... ~2 min", chat_id)
    saved_layers = MIN_LAYERS
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
            MIN_LAYERS = ml
            tr = sim_trades(rec, atr_sl=1.5, atr_tp=3.0)
            tag = " (gates lang)" if ml == 0 else ""
            m2 += _fmt(f"min {ml} all", summarize(tr)) + tag + "\n"
            m2 += _fmt(f"min {ml} oos", oos(tr)) + "\n"
        MIN_LAYERS = saved_layers
        m2 += "\nKung walang pagbuti habang tumataas ang min layers, tanggalin ang layers (simple = mas kaunting overfit)."
        send_telegram_msg(m2, chat_id)
    except Exception as e:
        import traceback; traceback.print_exc()
        send_telegram_msg(f"Diag err {e}", chat_id)
    finally:
        MIN_LAYERS = saved_layers

# ---------- SCAN ----------
def manual_scan(chat_id, auto=False):
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - SAFETY LOCK PAPER ONLY", chat_id)
        return
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
        if MASTER_LIVE_ENABLE: return
        now_utc = datetime.datetime.utcnow()
        if not TELEGRAM_CHAT_ID: return
        if not (7 <= now_utc.hour <= 19): return
        print(f"[AUTO-SCAN {VERSION}] {now_utc} scanning M5...")
        manual_scan(TELEGRAM_CHAT_ID, auto=True)
    except Exception as e:
        print(f"Auto scan error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running:
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
def root(): return {"status": f"XAUUSD TITAN {VERSION} M5 PAPER", "time": pht_now().isoformat(), "live_enabled": MASTER_LIVE_ENABLE, "dashboard": "/dashboard", "api": "/api/stats"}

@app.get("/health")
def health(): return {"status": "ok", "version": VERSION, "live_enabled": MASTER_LIVE_ENABLE}

@app.get("/status")
def status(): return {"status": "ok", "version": VERSION, "live_enabled": MASTER_LIVE_ENABLE}

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
        h1_full = get_h1_full_status()
        h1 = h1_full.get("combined", "UNKNOWN")
        clean = _clean_live()
        source = getattr(fetch_live_tf, 'last_source', 'UNKNOWN')
        if not clean:
            return JSONResponse({"error": "No data", "timestamp": pht_now().isoformat(), "h1_full": h1_full})
        if len(clean) < 60:
            return JSONResponse({"error": f"Not enough bars {len(clean)}<60", "timestamp": pht_now().isoformat(), "h1_full": h1_full})
        # Import detailed analyzer if exists, else simple
        try:
            detailed = analyze_titan_detailed(clean, tf="M5", h1_trend=h1) if 'analyze_titan_detailed' in globals() else {"decision": "N/A"}
        except:
            detailed = {"decision": "N/A", "reason": "No detailed analyzer"}
        detailed["data_source"] = source
        detailed["api_key_set"] = bool(TWELVE_DATA_API_KEY)
        detailed["live_price"] = clean[0]['close']
        detailed["h1_full"] = h1_full
        detailed["h1_trend"] = h1
        detailed["version"] = VERSION
        return JSONResponse(detailed)
    except Exception as e:
        import traceback
        return JSONResponse({"error": str(e), "trace": traceback.format_exc()[:500], "timestamp": pht_now().isoformat()})

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse("<h1>TITAN V7.7 Dashboard - see /api/stats</h1><p>Trades: <a href='/api/stats'>/api/stats</a> | Pretrade: <a href='/api/pretrade'>/api/pretrade</a></p>")

@app.api_route("/telegram-webhook", methods=["GET", "POST"])
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        update = await request.json()
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
                h1 = fetch_h1_trend()
                stats = calculate_stats(load_trades())
                send_telegram_msg(f"🔒 *TITAN {VERSION} M5 PAPER*\nH1 `{h1}`\nTrades `{stats['total_trades']}` Closed `{stats['closed_trades']}` W `{stats['wins']}` L `{stats['losses']}` WR `{stats['wr']}%` PF `{stats['pf']}` Exp `{stats['exp']}R` Net `{stats['net']}R`\nDashboard /dashboard API /api/stats\nTime {pht_now().strftime('%Y-%m-%d %I:%M %p PHT')}", cid)
            elif txt_base == "/scan": background_tasks.add_task(manual_scan, cid)
            elif txt_base == "/backtest": background_tasks.add_task(run_backtest, cid)
            elif txt_base == "/diag": background_tasks.add_task(run_diag, cid)
            elif txt_base == "/dashboard":
                host = str(request.base_url).rstrip('/')
                send_telegram_msg(f"📊 *DASHBOARD*\n{host}/dashboard\nAPI {host}/api/stats\nPretrade {host}/api/pretrade\nClose with /win [id] or /loss [id]", cid)
    except Exception as e:
        print(e)
    return {"status": "ok"}
