import os
import datetime
from contextlib import asynccontextmanager

import requests
import numpy as np
import pandas as pd
from fastapi import FastAPI, Request, BackgroundTasks
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

PAIRS = ["XAUUSD", "GBPUSD", "EURUSD"]
PHT = pytz.timezone('Asia/Manila')

scheduler = BackgroundScheduler()

def pht_now():
    return datetime.datetime.now(PHT)

def format_time_pht(dt_str):
    try:
        if not dt_str:
            return "N/A", ""
        dt = pd.to_datetime(dt_str)
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        pht = dt.astimezone(PHT)
        return pht.strftime("%b %d, %I:%M %p PHT"), dt.strftime("%H:%M UTC")
    except:
        return str(dt_str)[:19], ""

def format_price(symbol, price):
    try:
        if "XAU" in symbol:
            return f"{float(price):.2f}"
        elif "JPY" in symbol:
            return f"{float(price):.3f}"
        else:
            return f"{float(price):.5f}"
    except:
        return str(price)

def send_telegram_msg(message: str, target_chat_id: str = None):
    chat_id = target_chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        print("Telegram tokens missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code!= 200:
            payload["parse_mode"] = None
            requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram alert: {e}")

# --- PINBAR DETECTOR - STRICT FOR XAU, LOOSE FOR OTHERS ---
def is_bullish_pinbar(candle, wick_mult=2.0, max_body_ratio=0.4, max_upper_wick_mult=1.5):
    o, h, l, c = candle['open'], candle['high'], candle['low'], candle['close']
    body = abs(c - o)
    rng = h - l
    if rng == 0:
        return False
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    if lower_wick < wick_mult * max(body, rng*0.05):
        return False
    if upper_wick > body * max_upper_wick_mult + rng*0.05:
        return False
    if body > rng * max_body_ratio:
        return False
    return True

def is_bearish_pinbar(candle, wick_mult=2.0, max_body_ratio=0.4, max_upper_wick_mult=1.5):
    o, h, l, c = candle['open'], candle['high'], candle['low'], candle['close']
    body = abs(c - o)
    rng = h - l
    if rng == 0:
        return False
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    if upper_wick < wick_mult * max(body, rng*0.05):
        return False
    if lower_wick > body * max_upper_wick_mult + rng*0.05:
        return False
    if body > rng * max_body_ratio:
        return False
    return True

def fetch_m5_live(symbol: str):
    sym = "XAU/USD" if symbol == "XAUUSD" else f"{symbol[:3]}/{symbol[3:]}"
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": sym, "interval": "5min", "outputsize": 100, "timezone": "UTC", "apikey": TWELVE_DATA_API_KEY}
    try:
        res = requests.get(url, params=params, timeout=10).json()
        if "values" not in res:
            print(f"Live Error {symbol}: {res}")
            return None
        values = res["values"]
        if values:
            try:
                dt = datetime.datetime.strptime(values[0]["datetime"], "%Y-%m-%d %H:%M:%S")
                if datetime.datetime.utcnow() < dt + datetime.timedelta(minutes=5):
                    values = values[1:]
            except: pass
        return values
    except Exception as e:
        print(f"Live fetch error {symbol}: {e}")
        return None

def fetch_historical_m5_clean(symbol: str, outputsize: int = 2000):
    sym = "XAU/USD" if symbol == "XAUUSD" else f"{symbol[:3]}/{symbol[3:]}"
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": sym, "interval": "5min", "outputsize": outputsize, "timezone": "UTC", "apikey": TWELVE_DATA_API_KEY}
    try:
        res = requests.get(url, params=params, timeout=15).json()
        if "values" not in res:
            print(f"History Error {symbol}: {res.get('message')}")
            return None
        df = pd.DataFrame(res["values"])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        for col in ['open','high','low','close']:
            df[col] = df[col].astype(float)
        df['weekday'] = df['datetime'].dt.weekday
        df = df[df['weekday'] < 5]
        df = df[df['high'] > df['low']]
        return df.to_dict('records')
    except Exception as e:
        print(f"History error {symbol}: {e}")
        return None

def calculate_ema(closes, period):
    if len(closes) < period: return None
    k = 2/(period+1)
    e = sum(closes[:period])/period
    for v in closes[period:]: e = v*k + e*(1-k)
    return e

def calculate_atr(candles_oldest_first, period=14):
    if len(candles_oldest_first) < period+1: return None
    trs=[]
    for i in range(1,len(candles_oldest_first)):
        h=candles_oldest_first[i]['high']; l=candles_oldest_first[i]['low']; pc=candles_oldest_first[i-1]['close']
        trs.append(max(h-l, abs(h-pc), abs(l-pc)))
    return sum(trs[-period:])/period

def analyze_variant(symbol, window_newest_first, variant_id=1):
    if len(window_newest_first) < 60: return None
    dt = pd.to_datetime(window_newest_first[0]['datetime'])
    if dt.hour < 7 or dt.hour > 19: return None

    oldest_first = list(reversed(window_newest_first))
    closes = [c['close'] for c in oldest_first]
    ema20 = calculate_ema(closes,20)
    ema50 = calculate_ema(closes,50)
    if not ema20 or not ema50: return None

    c0 = window_newest_first[0]
    c1 = window_newest_first[1]
    body_size = abs(c0['close']-c0['open'])
    prev_body = abs(c1['close']-c1['open'])

    # OPTION 2 LOGIC: XAU strict, others loose
    if symbol == "XAUUSD":
        body_mult = 1.2
        bullish_pin = is_bullish_pinbar(c0, wick_mult=2.0, max_body_ratio=0.4, max_upper_wick_mult=1.5)
        bearish_pin = is_bearish_pinbar(c0, wick_mult=2.0, max_body_ratio=0.4, max_upper_wick_mult=1.5)
        require_pinbar = True
        pin_label_strict = "Hammer" if bullish_pin else ("Shooting Star" if bearish_pin else "none")
    else:
        body_mult = 1.0 # dati 1.5 kaya 0 trades sa EURUSD, ngayon 1.0 na lang
        bullish_pin = is_bullish_pinbar(c0, wick_mult=1.5, max_body_ratio=0.6, max_upper_wick_mult=2.0)
        bearish_pin = is_bearish_pinbar(c0, wick_mult=1.5, max_body_ratio=0.6, max_upper_wick_mult=2.0)
        require_pinbar = False # wag na require sa forex, displacement lang ok na
        pin_label_strict = "Hammer" if bullish_pin else ("Shooting Star" if bearish_pin else "Displacement")

    signal_type=None
    if c0['close'] > ema20 > ema50 and c0['close'] > c0['open'] and body_size > prev_body*body_mult:
        if require_pinbar and not bullish_pin: return None
        signal_type="BUY"
    elif c0['close'] < ema20 < ema50 and c0['close'] < c0['open'] and body_size > prev_body*body_mult:
        if require_pinbar and not bearish_pin: return None
        signal_type="SELL"
    if not signal_type: return None

    pip_factor = 0.1 if symbol=="XAUUSD" else 0.0001
    spread_pips = 3.0 if symbol=="XAUUSD" else (1.5 if symbol=="GBPUSD" else 1.2)
    spread = spread_pips * pip_factor

    if variant_id==1:
        if symbol=="XAUUSD": sl_pips,tp_pips=18.0,36.0
        elif symbol=="GBPUSD": sl_pips,tp_pips=12.0,24.0
        else: sl_pips,tp_pips=10.0,20.0
    else:
        atr=calculate_atr(oldest_first,14)
        if not atr: return None
        sl_pips=round((atr*1.5)/pip_factor,1); tp_pips=round((atr*3.0)/pip_factor,1)
        sl_pips=max(8.0,min(sl_pips,25.0))

    if symbol=="XAUUSD":
        entry=round(c0['close'],2)
        sl=round(c0['close']-(sl_pips*pip_factor) if signal_type=="BUY" else c0['close']+(sl_pips*pip_factor),2)
        tp=round(c0['close']+(tp_pips*pip_factor) if signal_type=="BUY" else c0['close']-(tp_pips*pip_factor),2)
    else:
        entry=round(c0['close'],5)
        sl=round(c0['close']-(sl_pips*pip_factor) if signal_type=="BUY" else c0['close']+(sl_pips*pip_factor),5)
        tp=round(c0['close']+(tp_pips*pip_factor) if signal_type=="BUY" else c0['close']-(tp_pips*pip_factor),5)

    return {"pair":symbol,"type":signal_type,"entry":entry,"sl":sl,"tp":tp,"spread":spread,"time":window_newest_first[0]['datetime'],"pinbar":pin_label_strict,"reason":f"EMA20>50 + Disp + {pin_label_strict}"}

def run_variant_simulation(records, pair, variant_id=1, timeout_candles=36):
    total=wins=losses=timeouts=spread_cuts=0; net_r=0.0
    i=60; n=len(records)
    while i < n-timeout_candles:
        window=list(reversed(records[i-60:i]))
        sig=analyze_variant(pair,window,variant_id=variant_id)
        if not sig: i+=1; continue
        total+=1
        entry,sl,tp,spread=sig['entry'],sig['sl'],sig['tp'],sig['spread']
        sig_type=sig['type']
        eff_entry=entry+spread if sig_type=="BUY" else entry-spread
        result=None; exit_off=timeout_candles
        for n_idx,fc in enumerate(records[i:i+timeout_candles]):
            if sig_type=="BUY":
                hit_sl=fc['low']<=sl; hit_tp=fc['high']>=tp
            else:
                hit_sl=fc['high']>=sl; hit_tp=fc['low']<=tp
            if hit_sl and hit_tp: result="loss"; exit_off=n_idx+1; break
            elif hit_sl: result="loss"; exit_off=n_idx+1; break
            elif hit_tp: result="win"; exit_off=n_idx+1; break
        if result=="win": wins+=1; net_r+=2.0
        elif result=="loss": losses+=1; net_r-=1.0
        else:
            last_close=records[i+timeout_candles-1]['close']
            pnl=(last_close-eff_entry) if sig_type=="BUY" else (eff_entry-last_close)
            if pnl<=0: spread_cuts+=1; net_r-=0.5
            else: timeouts+=1
        i+=max(exit_off,1)
    return total,wins,losses,timeouts,spread_cuts,round(net_r,1)

def run_walkforward_backtest_task(chat_id: str):
    send_telegram_msg("⏳ *Fetching Clean M5 Data (Option 2 - XAU Strict, Forex Loose)...*", chat_id)
    try:
        report="📊 *WALK-FORWARD BENCHMARK (Option 2)*\n*XAU=Strict Hammer | Forex=Loose*\n\n"
        for pair in PAIRS:
            records=fetch_historical_m5_clean(pair,outputsize=2000)
            if not records or len(records)<500:
                report+=f"• *{pair}*: Data Failed.\n\n"; continue
            split=int(len(records)*0.66)
            in_sample=records[:split]
            report+=f"🔹 *{pair}* (In-Sample: `{len(in_sample)}`):\n"
            for v_id in [1,2]:
                v_name="V1 Fixed" if v_id==1 else "V2 ATR"
                t,w,l,to,sc,nr=run_variant_simulation(in_sample,pair,variant_id=v_id)
                wr=round(w/(w+l)*100,1) if (w+l)>0 else 0.0
                exp=round(nr/t,2) if t>0 else 0.0
                report+=f" • *{v_name}*: Trades `{t}` | WR `{wr}%` | Net `{nr}R` | Exp `{exp}R` | W/L/TO/SC `{w}/{l}/{to}/{sc}`\n"
            report+="\n"
        report+="⚠️ _Option 2: XAU Hammer Strict, GBP/EUR Displacement._"
        send_telegram_msg(report,chat_id)
    except Exception as err:
        send_telegram_msg(f"❌ Backtest Error: {err}",chat_id)

def manual_scan_task(chat_id: str):
    send_telegram_msg("🔍 *Scanning M5 (Option 2)...*\n_XAU=Hammer Required | Forex=Displacement_", chat_id)
    found=False
    for pair in PAIRS:
        data=fetch_m5_live(pair)
        if not data: continue
        clean=[]
        for d in data:
            try: clean.append({"open":float(d["open"]),"high":float(d["high"]),"low":float(d["low"]),"close":float(d["close"]),"datetime":d["datetime"]})
            except: pass
        if len(clean)>=60:
            sig=analyze_variant(pair,clean,variant_id=1)
            if sig:
                found=True
                pht_time,utc_time=format_time_pht(sig['time'])
                pin_emoji="🔨" if "Hammer" in sig['pinbar'] else ("⭐" if "Shooting" in sig['pinbar'] else "📈")
                msg=(f"⚡ *M5 SMC SIGNAL DETECTED* {pin_emoji}\n\n• *Pair:* {sig['pair']} | *Action:* {sig['type']}\n• *Entry:* `{format_price(sig['pair'],sig['entry'])}`\n• *SL:* `{format_price(sig['pair'],sig['sl'])}` | *TP:* `{format_price(sig['pair'],sig['tp'])}`\n• *Candle Time:* `{pht_time}` (`{utc_time}`)\n• *Pinbar:* `{sig['pinbar']}`\n• *Reason:* `{sig['reason']}`")
                send_telegram_msg(msg,chat_id)
    if not found:
        send_telegram_msg("ℹ️ *No active setups (Option 2) right now.*\n_XAU needs Hammer, Forex needs Displacement._", chat_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running: scheduler.start()
    yield
    if scheduler.running: scheduler.shutdown(wait=False)

app=FastAPI(title="SMC Engine V2.3 Option2", lifespan=lifespan)

@app.api_route("/telegram-webhook", methods=["GET","POST"])
@app.api_route("/telegram/webhook", methods=["GET","POST"])
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        update=await request.json()
        if "message" in update and "text" in update["message"]:
            chat_id=str(update["message"]["chat"]["id"])
            text=update["message"]["text"].strip().split("@")[0]
            if TELEGRAM_CHAT_ID and chat_id!=str(TELEGRAM_CHAT_ID): return {"status":"ok"}
            if text=="/status":
                pht_time=pht_now().strftime("%Y-%m-%d %I:%M:%S %p PHT")
                msg=(f"📊 *ENGINE STATUS - Option 2*\n\n• *Mode:* `SMC_V2.3_OPT2`\n• *Paper:* `True`\n• *Data:* `TWELVE_DATA_SPOT`\n• *Time:* `{pht_time}`\n• *XAU:* `Hammer Strict`\n• *GBP/EUR:* `Loose Disp (1.0x)`")
                send_telegram_msg(msg,chat_id)
            elif text=="/scan":
                background_tasks.add_task(manual_scan_task,chat_id)
            elif text=="/backtest":
                background_tasks.add_task(run_walkforward_backtest_task,chat_id)
            elif text in ["/help","/start"]:
                msg=("🤖 *BOT COMMANDS - Option 2*\n\n• `/status`\n• `/scan` - XAU strict, Forex loose\n• `/backtest`")
                send_telegram_msg(msg,chat_id)
    except Exception as e:
        print(f"Webhook error: {e}")
    return {"status":"ok"}

@app.get("/status")
def status():
    return {"status":"ok","mode":"SMC_V2.3_OPT2"}
