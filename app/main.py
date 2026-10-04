import os, datetime
from contextlib import asynccontextmanager
import requests, pandas as pd
from fastapi import FastAPI, Request, BackgroundTasks
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TWELVE_DATA_API_KEY = os.getenv("TWELVE_DATA_API_KEY", "")

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
    except: pass

def is_bullish_pinbar(c):
    o,h,l,cl=c['open'],c['high'],c['low'],c['close']
    body=abs(cl-o); rng=h-l
    if rng==0: return False
    low_w=min(o,cl)-l; up_w=h-max(o,cl)
    return low_w>=1.8*max(body,rng*0.05) and up_w<=body*1.8 and body<=rng*0.45

def is_bearish_pinbar(c):
    o,h,l,cl=c['open'],c['high'],c['low'],c['close']
    body=abs(cl-o); rng=h-l
    if rng==0: return False
    low_w=min(o,cl)-l; up_w=h-max(o,cl)
    return up_w>=1.8*max(body,rng*0.05) and low_w<=body*1.8 and body<=rng*0.45

def calculate_ema(closes, p):
    if len(closes)<p: return None
    k=2/(p+1); e=sum(closes[:p])/p
    for v in closes[p:]: e=v*k+e*(1-k)
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
            if datetime.datetime.utcnow()<dt+datetime.timedelta(minutes=5): vals=vals[1:]
        except: pass
        return vals
    except: return None

def fetch_h1_trend():
    url="https://api.twelvedata.com/time_series"
    params={"symbol":"XAU/USD","interval":"1h","outputsize":100,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY}
    try:
        res=requests.get(url,params=params,timeout=10).json()
        if "values" not in res: return None
        df=pd.DataFrame(res["values"]); df['close']=df['close'].astype(float)
        df=df.sort_values('datetime'); closes=list(df['close'])
        e20=calculate_ema(closes,20); e50=calculate_ema(closes,50)
        if not e20 or not e50: return None
        return "BULL" if e20>e50 else "BEAR" if e20<e50 else None
    except: return None

def fetch_hist(outputsize=3000):
    url="https://api.twelvedata.com/time_series"
    params={"symbol":"XAU/USD","interval":"5min","outputsize":outputsize,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY}
    try:
        res=requests.get(url,params=params,timeout=15).json()
        if "values" not in res: return None
        df=pd.DataFrame(res["values"]); df['datetime']=pd.to_datetime(df['datetime'])
        df=df.sort_values('datetime').reset_index(drop=True)
        for col in ['open','high','low','close']: df[col]=df[col].astype(float)
        df['weekday']=df['datetime'].dt.weekday
        df=df[df['weekday']<5]; df=df[df['high']>df['low']]
        return df.to_dict('records')
    except: return None

def analyze_v43(window, h1_trend=None):
    if len(window)<60: return None
    dt=pd.to_datetime(window[0]['datetime'])
    if dt.hour<7 or dt.hour>19: return None
    oldest=list(reversed(window)); closes=[c['close'] for c in oldest]
    e20=calculate_ema(closes,20); e50=calculate_ema(closes,50)
    if not e20 or not e50: return None
    c0=window[0]; c1=window[1]
    body=abs(c0['close']-c0['open']); prev=abs(c1['close']-c1['open'])
    if body<prev*1.0: return None

    bullish=is_bullish_pinbar(c0); bearish=is_bearish_pinbar(c0)
    if not bullish and not bearish: return None

    rng=c0['high']-c0['low']
    if rng==0: return None

    # V4.3: Strong Close 60% + Prev Opposite Color (key for 60%+ WR)
    if bullish:
        if (c0['close']-c0['low'])/rng <0.60: return None
        if not (c0['close']>e20>e50): return None
        if c1['close'] >= c1['open']: return None # prev dapat bearish para reversal
        if h1_trend=="BEAR": return None
        sig="BUY"
    else:
        if (c0['high']-c0['close'])/rng <0.60: return None
        if not (c0['close']<e20<e50): return None
        if c1['close'] <= c1['open']: return None # prev dapat bullish
        if h1_trend=="BULL": return None
        sig="SELL"

    entry=round(c0['close'],2)
    sl=round(entry-1.8 if sig=="BUY" else entry+1.8,2)
    tp=round(entry+3.6 if sig=="BUY" else entry-3.6,2)
    return {"pair":"XAUUSD","type":sig,"entry":entry,"sl":sl,"tp":tp,"time":window[0]['datetime'],"pinbar":"Hammer" if bullish else "Shooting Star","h1":h1_trend,"reason":f"Hammer+SC60%+PrevOpp+H1_{h1_trend}"}

def run_sim(records):
    total=wins=losses=0; net=0.0
    i=60; n=len(records)
    while i<n-36:
        window=list(reversed(records[i-60:i]))
        oldest=list(reversed(window)); closes=[c['close'] for c in oldest]
        e50=calculate_ema(closes,50); e100=calculate_ema(closes,100)
        h1_proxy="BULL" if e50 and e100 and e50>e100 else "BEAR" if e50 and e100 and e50<e100 else None
        sig=analyze_v43(window, h1_trend=h1_proxy)
        if not sig: i+=1; continue
        total+=1; sl=sig['sl']; tp=sig['tp']; typ=sig['type']
        res=None
        for fc in records[i:i+36]:
            if typ=="BUY":
                if fc['low']<=sl: res="loss"; break
                if fc['high']>=tp: res="win"; break
            else:
                if fc['high']>=sl: res="loss"; break
                if fc['low']<=tp: res="win"; break
        if res=="win": wins+=1; net+=2.0
        elif res=="loss": losses+=1; net-=1.0
        else: losses+=1; net-=1.0
        i+=1
    wr=round(wins/(wins+losses)*100,1) if wins+losses>0 else 0
    exp=round(net/total,2) if total>0 else 0
    return total,wins,losses,wr,net,exp

def run_backtest(chat_id):
    send_telegram_msg("⏳ *V4.3 Test (Hammer + SC60% + Prev Opposite + H1)*\n_Target 60%+ WR_", chat_id)
    try:
        rec=fetch_hist(3000)
        if not rec: send_telegram_msg("Data fail", chat_id); return
        split=int(len(rec)*0.66); ins=rec[:split]; outs=rec[split:]
        t,w,l,wr,net,exp=run_sim(ins)
        t2,w2,l2,wr2,net2,exp2=run_sim(outs)
        msg=f"📊 *XAUUSD V4.3 FINAL 1:2*\n_Hammer+SC60%+PrevOpp+H1_\n\n🔹 In-Sample ({len(ins)}):\n Trades `{t}` | WR `{wr}%` | Net `{net}R` | Exp `{exp}R` | W/L `{w}/{l}`\n\n🔹 Out-Sample ({len(outs)}):\n Trades `{t2}` | WR `{wr2}%` | Net `{net2}R` | Exp `{exp2}R` | W/L `{w2}/{l2}`\n\n⚠️ _Target 60%+ WR 1:2_"
        send_telegram_msg(msg, chat_id)
    except Exception as e:
        send_telegram_msg(f"Err {e}", chat_id)

def manual_scan(chat_id):
    send_telegram_msg("🔍 *Scanning V4.3 (Hammer SC60% PrevOpp H1)*", chat_id)
    data=fetch_m5_live(); h1=fetch_h1_trend()
    if not data: send_telegram_msg("No data", chat_id); return
    clean=[]
    for d in data:
        try: clean.append({"open":float(d["open"]),"high":float(d["high"]),"low":float(d["low"]),"close":float(d["close"]),"datetime":d["datetime"]})
        except: pass
    if len(clean)>=60:
        sig=analyze_v43(clean, h1_trend=h1)
        if sig:
            pht,utc=format_time_pht(sig['time'])
            msg=f"⚡ *XAUUSD V4.3 1:2* 🔨\n\n• {sig['pair']} {sig['type']}\n• Entry `{format_price(sig['entry'])}`\n• SL `{format_price(sig['sl'])}` TP `{format_price(sig['tp'])}`\n• Time `{pht}` ({utc})\n• H1 `{sig['h1']}`\n• Reason `{sig['reason']}`\n• Target WR `60%+`"
            send_telegram_msg(msg, chat_id); return
    send_telegram_msg(f"ℹ️ No V4.3 setup. H1 `{h1}`", chat_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running: scheduler.start()
    yield
    if scheduler.running: scheduler.shutdown(wait=False)

app=FastAPI(title="V4.3 High WR", lifespan=lifespan)

@app.get("/")
def root(): return {"status":"XAUUSD V4.3 Live","mode":"Hammer_SC60_PrevOpp_H1","time":pht_now().isoformat()}
@app.get("/health")
def health(): return {"status":"ok","mode":"V4.3"}
@app.get("/status")
def status(): return {"status":"ok","mode":"V4.3"}

@app.api_route("/telegram-webhook", methods=["GET","POST"])
@app.api_route("/telegram/webhook", methods=["GET","POST"])
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        update=await request.json()
        if "message" in update and "text" in update["message"]:
            cid=str(update["message"]["chat"]["id"])
            txt=update["message"]["text"].strip().split("@")[0]
            if TELEGRAM_CHAT_ID and cid!=str(TELEGRAM_CHAT_ID): return {"status":"ok"}
            if txt=="/status":
                h1=fetch_h1_trend()
                send_telegram_msg(f"📊 *V4.3*\nMode `HAMMER_SC60_PREVOPP_H1`\nH1 `{h1}`\nRR 1:2 SL18 TP36\nTarget 60%+ WR\nTime {pht_now().strftime('%Y-%m-%d %I:%M %p PHT')}", cid)
            elif txt=="/scan": background_tasks.add_task(manual_scan, cid)
            elif txt=="/backtest": background_tasks.add_task(run_backtest, cid)
            elif txt in ["/help","/start"]: send_telegram_msg("🤖 V4.3 Commands\n• /status • /scan • /backtest\n*Goal 60%+ WR 1:2*", cid)
    except Exception as e: print(e)
    return {"status":"ok"}
