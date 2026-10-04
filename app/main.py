import os, datetime
from contextlib import asynccontextmanager
import requests, pandas as pd
from fastapi import FastAPI, Request, BackgroundTasks
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

PAIRS = ["XAUUSD"]
PHT = pytz.timezone('Asia/Manila')
scheduler = BackgroundScheduler()

def pht_now(): return datetime.datetime.now(PHT)
def format_time_pht(dt_str):
    try:
        dt = pd.to_datetime(dt_str)
        if dt.tzinfo is None: dt = pytz.utc.localize(dt)
        pht = dt.astimezone(PHT)
        return pht.strftime("%b %d, %I:%M %p PHT"), dt.strftime("%H:%M UTC")
    except: return str(dt_str)[:19], ""

def format_price(p): return f"{float(p):.2f}"
def send_telegram_msg(msg, chat_id=None):
    cid = chat_id or TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": cid, "text": msg, "parse_mode": "Markdown"}, timeout=10)
        if r.status_code!=200:
            requests.post(url, json={"chat_id": cid, "text": msg}, timeout=10)
    except Exception as e: print(e)

def is_bullish_pinbar(c):
    o,h,l,cl = c['open'],c['high'],c['low'],c['close']
    body = abs(cl-o); rng = h-l
    if rng==0: return False
    low_w = min(o,cl)-l; up_w = h-max(o,cl)
    return low_w >= 2.0*max(body,rng*0.05) and up_w <= body*1.5+rng*0.05 and body <= rng*0.4

def is_bearish_pinbar(c):
    o,h,l,cl = c['open'],c['high'],c['low'],c['close']
    body = abs(cl-o); rng = h-l
    if rng==0: return False
    low_w = min(o,cl)-l; up_w = h-max(o,cl)
    return up_w >= 2.0*max(body,rng*0.05) and low_w <= body*1.5+rng*0.05 and body <= rng*0.4

def calculate_ema(closes, period):
    if len(closes)<period: return None
    k=2/(period+1); e=sum(closes[:period])/period
    for v in closes[period:]: e=v*k+e*(1-k)
    return e

def fetch_m5_live():
    url="https://api.twelvedata.com/time_series"
    params={"symbol":"XAU/USD","interval":"5min","outputsize":100,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY}
    try:
        res=requests.get(url,params=params,timeout=10).json()
        if "values" not in res: return None
        vals=res["values"]
        try:
            dt=datetime.datetime.strptime(vals[0]["datetime"], "%Y-%m-%d %H:%M:%S")
            if datetime.datetime.utcnow() < dt+datetime.timedelta(minutes=5): vals=vals[1:]
        except: pass
        return vals
    except: return None

def fetch_h1_trend():
    # Live H1 trend for higher WR
    url="https://api.twelvedata.com/time_series"
    params={"symbol":"XAU/USD","interval":"1h","outputsize":100,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY}
    try:
        res=requests.get(url,params=params,timeout=10).json()
        if "values" not in res: return None
        df=pd.DataFrame(res["values"])
        df['close']=df['close'].astype(float)
        df=df.sort_values('datetime')
        closes=list(df['close'])
        ema20=calculate_ema(closes,20); ema50=calculate_ema(closes,50)
        if not ema20 or not ema50: return None
        if ema20>ema50: return "BULL"
        if ema20<ema50: return "BEAR"
        return None
    except: return None

def fetch_historical_m5_clean(outputsize=2000):
    url="https://api.twelvedata.com/time_series"
    params={"symbol":"XAU/USD","interval":"5min","outputsize":outputsize,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY}
    try:
        res=requests.get(url,params=params,timeout=15).json()
        if "values" not in res: return None
        df=pd.DataFrame(res["values"])
        df['datetime']=pd.to_datetime(df['datetime'])
        df=df.sort_values('datetime').reset_index(drop=True)
        for col in ['open','high','low','close']: df[col]=df[col].astype(float)
        df['weekday']=df['datetime'].dt.weekday
        df=df[df['weekday']<5]; df=df[df['high']>df['low']]
        return df.to_dict('records')
    except: return None

def analyze_variant(window_newest_first, h1_trend=None):
    if len(window_newest_first)<60: return None
    dt=pd.to_datetime(window_newest_first[0]['datetime'])
    if dt.hour<7 or dt.hour>19: return None # Killzone

    oldest=list(reversed(window_newest_first))
    closes=[c['close'] for c in oldest]
    ema20=calculate_ema(closes,20); ema50=calculate_ema(closes,50)
    if not ema20 or not ema50: return None

    c0=window_newest_first[0]; c1=window_newest_first[1]
    body=abs(c0['close']-c0['open']); prev_body=abs(c1['close']-c1['open'])

    # FILTER 1: Hammer strict pa rin
    bullish=is_bullish_pinbar(c0); bearish=is_bearish_pinbar(c0)
    if not bullish and not bearish: return None
    pin_name="Hammer" if bullish else "Shooting Star"

    # FILTER 2: Displacement pa rin
    if body < prev_body*1.2: return None

    # FILTER 3: H1 Trend (para tumaas WR) - BUY only if H1 BULL
    if h1_trend=="BEAR" and bullish: return None # kontra H1, wag
    if h1_trend=="BULL" and bearish: return None

    # FILTER 4: Liquidity Sweep - dapat nasweep yung last 20 lows for BUY
    last_20_lows=[c['low'] for c in window_newest_first[1:21]]
    last_20_highs=[c['high'] for c in window_newest_first[1:21]]
    swept_low = c0['low'] < min(last_20_lows) if last_20_lows else False
    swept_high = c0['high'] > max(last_20_highs) if last_20_highs else False

    # FILTER 5: FVG check - may imbalance
    # Bullish FVG: c0 low > c2 high
    try:
        c2=window_newest_first[2]
        bullish_fvg = c0['low'] > c2['high'] and (c0['low']-c2['high'])>0.2 # 20 cents gap
        bearish_fvg = c0['high'] < c2['low'] and (c2['low']-c0['high'])>0.2
    except:
        bullish_fvg=bearish_fvg=False

    # For 62%+ WR: Require SWEEP + (FVG or HTF)
    # Kung BUY: dapat may sweep low + (FVG or H1 BULL)
    if bullish:
        if not swept_low: return None
        if not (bullish_fvg or h1_trend=="BULL"):
            # kung walang FVG at walang H1 trend, need mas malaking sweep
            if c0['low'] > min(last_20_lows)-0.1: return None
        signal_type="BUY"
    else:
        if not swept_high: return None
        if not (bearish_fvg or h1_trend=="BEAR"):
            if c0['high'] < max(last_20_highs)+0.1: return None
        signal_type="SELL"

    # EMA check pa rin
    if signal_type=="BUY" and not (c0['close']>ema20>ema50): return None
    if signal_type=="SELL" and not (c0['close']<ema20<ema50): return None

    entry=round(c0['close'],2)
    sl=round(entry-1.8 if signal_type=="BUY" else entry+1.8,2)
    tp=round(entry+3.6 if signal_type=="BUY" else entry-3.6,2)

    reason=f"Sweep+FVG+H1 {pin_name}"
    if bullish_fvg or bearish_fvg: reason+= "+FVG"
    if h1_trend: reason+= f"+H1_{h1_trend}"

    return {"pair":"XAUUSD","type":signal_type,"entry":entry,"sl":sl,"tp":tp,"time":window_newest_first[0]['datetime'],"pinbar":pin_name,"reason":reason,"h1":h1_trend,"swept":swept_low if signal_type=="BUY" else swept_high}

def run_simulation(records):
    total=wins=losses=0; net=0.0
    i=60; n=len(records)
    # For backtest HTF proxy: use EMA100/200 on M5 as H1
    while i<n-36:
        window=list(reversed(records[i-60:i]))
        # HTF proxy for backtest
        oldest=list(reversed(window))
        closes=[c['close'] for c in oldest]
        ema100=calculate_ema(closes,100); ema200=calculate_ema(closes,200)
        h1_proxy="BULL" if ema100 and ema200 and ema100>ema200 else ("BEAR" if ema100 and ema200 and ema100<ema200 else None)

        sig=analyze_variant(window, h1_trend=h1_proxy)
        if not sig: i+=1; continue
        total+=1
        sl=sig['sl']; tp=sig['tp']; typ=sig['type']
        result=None
        for fc in records[i:i+36]:
            if typ=="BUY":
                if fc['low']<=sl: result="loss"; break
                if fc['high']>=tp: result="win"; break
            else:
                if fc['high']>=sl: result="loss"; break
                if fc['low']<=tp: result="win"; break
        if result=="win": wins+=1; net+=2.0
        elif result=="loss": losses+=1; net-=1.0
        else: # timeout
            # count as loss for strict WR
            losses+=1; net-=1.0
        i+=1
    wr=round(wins/(wins+losses)*100,1) if (wins+losses)>0 else 0
    exp=round(net/total,2) if total>0 else 0
    return total,wins,losses,wr,net,exp

def run_backtest_task(chat_id):
    send_telegram_msg("⏳ *Running XAUUSD V4 High WR 1:2 Backtest...*\n_Sweep + FVG + H1 Filter_", chat_id)
    try:
        records=fetch_historical_m5_clean(2000)
        if not records: send_telegram_msg("Data failed", chat_id); return
        split=int(len(records)*0.66)
        in_s=records[:split]; out_s=records[split:]
        t,w,l,wr,net,exp=run_simulation(in_s)
        t2,w2,l2,wr2,net2,exp2=run_simulation(out_s)
        report=f"📊 *XAUUSD V4 HIGH WR 1:2 (Sweep+FVG+H1)*\n\n🔹 *In-Sample ({len(in_s)}):*\n Trades `{t}` | WR `{wr}%` | Net `{net}R` | Exp `{exp}R` | W/L `{w}/{l}`\n\n🔹 *Out-Sample ({len(out_s)}):*\n Trades `{t2}` | WR `{wr2}%` | Net `{net2}R` | Exp `{exp2}R` | W/L `{w2}/{l2}`\n\n⚠️ _Target: 60%+ WR with 1:2 RR_\n_Filters: Hammer + Sweep Low + FVG + H1 Trend_"
        send_telegram_msg(report, chat_id)
    except Exception as e:
        send_telegram_msg(f"Error {e}", chat_id)

def manual_scan_task(chat_id):
    send_telegram_msg("🔍 *Scanning XAUUSD V4 High WR...*\n_Sweep + FVG + H1_", chat_id)
    data=fetch_m5_live()
    h1=fetch_h1_trend()
    if not data: send_telegram_msg("No data", chat_id); return
    clean=[]
    for d in data:
        try: clean.append({"open":float(d["open"]),"high":float(d["high"]),"low":float(d["low"]),"close":float(d["close"]),"datetime":d["datetime"]})
        except: pass
    if len(clean)>=60:
        sig=analyze_variant(clean, h1_trend=h1)
        if sig:
            pht,utc=format_time_pht(sig['time'])
            msg=f"⚡ *XAUUSD V4 GOLD 1:2* 🔨\n\n• Pair: {sig['pair']} | {sig['type']}\n• Entry: `{format_price(sig['entry'])}`\n• SL: `{format_price(sig['sl'])}` | TP: `{format_price(sig['tp'])}`\n• Time: `{pht}` ({utc})\n• Pinbar: `{sig['pinbar']}`\n• H1: `{sig['h1']}`\n• Reason: `{sig['reason']}`\n• RR: `1:2` | Target WR `60%+`"
            send_telegram_msg(msg, chat_id)
            return
    send_telegram_msg(f"ℹ️ No V4 setup now. H1: `{h1}`\n_Need Hammer + Sweep + FVG_", chat_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running: scheduler.start()
    yield
    if scheduler.running: scheduler.shutdown(wait=False)

app=FastAPI(title="XAUUSD V4 High WR 1:2", lifespan=lifespan)

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
                h1=fetch_h1_trend()
                msg=f"📊 *XAUUSD V4 HIGH WR 1:2*\n\n• Mode: `V4_SWEEP_FVG_H1`\n• RR: `1:2 SL18 TP36`\n• H1 Trend: `{h1}`\n• Target WR: `60%+`\n• Filters: `Hammer + Sweep + FVG + H1`\n• Time: `{pht_now().strftime('%Y-%m-%d %I:%M %p PHT')}`"
                send_telegram_msg(msg, chat_id)
            elif text=="/scan": background_tasks.add_task(manual_scan_task, chat_id)
            elif text=="/backtest": background_tasks.add_task(run_backtest_task, chat_id)
            elif text in ["/help","/start"]:
                send_telegram_msg("🤖 *V4 Commands*\n• /status • /scan • /backtest\n*Goal 60%+ WR 1:2*", chat_id)
    except Exception as e: print(e)
    return {"status":"ok"}

@app.get("/status")
def status(): return {"status":"ok","mode":"V4_HIGH_WR_1_2"}
