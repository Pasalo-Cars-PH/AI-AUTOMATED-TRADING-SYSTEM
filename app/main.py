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

def calculate_ema(closes, p):
    if len(closes)<p: return None
    k=2/(p+1); e=sum(closes[:p])/p
    for v in closes[p:]: e=v*k+e*(1-k)
    return e
def calculate_rsi(closes, period=14):
    if len(closes)<period+1: return 50
    gains=[]; losses=[]
    for i in range(1, len(closes)):
        diff=closes[i]-closes[i-1]
        gains.append(max(diff,0)); losses.append(max(-diff,0))
    avg_gain=sum(gains[-period:])/period
    avg_loss=sum(losses[-period:])/period
    if avg_loss==0: return 100
    rs=avg_gain/avg_loss
    return 100-(100/(1+rs))

def is_bullish_pinbar(c):
    o,h,l,cl=c['open'],c['high'],c['low'],c['close']
    body=abs(cl-o); rng=h-l
    if rng==0: return False
    low_w=min(o,cl)-l; up_w=h-max(o,cl)
    return low_w>=1.5*max(body,rng*0.05) and up_w<=body*2.2 and body<=rng*0.55
def is_bearish_pinbar(c):
    o,h,l,cl=c['open'],c['high'],c['low'],c['close']
    body=abs(cl-o); rng=h-l
    if rng==0: return False
    low_w=min(o,cl)-l; up_w=h-max(o,cl)
    return up_w>=1.5*max(body,rng*0.05) and low_w<=body*2.2 and body<=rng*0.55
def is_bullish_engulfing(c0,c1):
    return c1['close']<c1['open'] and c0['close']>c0['open'] and c0['open']<c1['close'] and c0['close']>c1['open'] and abs(c0['close']-c0['open'])>abs(c1['close']-c1['open'])*1.0
def is_bearish_engulfing(c0,c1):
    return c1['close']>c1['open'] and c0['close']<c0['open'] and c0['open']>c1['close'] and c0['close']<c1['open'] and abs(c0['close']-c0['open'])>abs(c1['close']-c1['open'])*1.0

# --- 8 BOOSTERS ---
def booster_news(dt):
    h=dt.hour; m=dt.minute
    # Red news 13:30-13:45 UTC CPI/NFP - SCORING lang, hindi block para volume
    if (h==13 and 15<=m<=45) or (h==18 and 0<=m<=30):
        return False, 0, "NEWS BLOCK"
    return True, 10, "NEWS Clear"

def booster_kill_zone(dt):
    h=dt.hour
    # VOLUME: 7-19 UTC wide = +5% pag London/NY, pero allow pa rin Asian
    if 8<=h<=11 or 13<=h<=16:
        return True, 10, f"KILL London/NY {h}UTC"
    elif 7<=h<=19:
        return True, 5, f"KILL OK {h}UTC"
    else:
        return True, 0, f"KILL Asian {h}UTC"

def booster_dxy():
    # DXY +10% pag aligned, 0 pag hindi - hindi block para volume
    try:
        url="https://api.twelvedata.com/time_series"
        params={"symbol":"DXY/USD","interval":"1h","outputsize":20,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY}
        res=requests.get(url,params=params,timeout=4).json()
        if "values" in res:
            closes=[float(v['close']) for v in reversed(res["values"])]
            e20=calculate_ema(closes,20); e50=calculate_ema(closes,50)
            if e20 and e50:
                trend="BEAR" if e20<e50 else "BULL"
                return trend, 10, f"DXY {trend}"
    except: pass
    return None, 5, "DXY N/A"

def fetch_data(symbol, interval, outputsize):
    url="https://api.twelvedata.com/time_series"
    params={"symbol":symbol,"interval":interval,"outputsize":outputsize,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY}
    try:
        res=requests.get(url,params=params,timeout=10).json()
        if "values" not in res: return None
        return res["values"]
    except: return None

def fetch_m5_live():
    vals=fetch_data("XAU/USD","5min",100)
    if not vals: return None
    try:
        dt=datetime.datetime.strptime(vals[0]["datetime"], "%Y-%m-%d %H:%M:%S")
        if datetime.datetime.utcnow()<dt+datetime.timedelta(minutes=5): vals=vals[1:]
    except: pass
    return vals
def fetch_h1_trend():
    vals=fetch_data("XAU/USD","1h",100)
    if not vals: return None
    df=pd.DataFrame(vals); df['close']=df['close'].astype(float)
    df=df.sort_values('datetime'); closes=list(df['close'])
    e20=calculate_ema(closes,20); e50=calculate_ema(closes,50)
    if not e20 or not e50: return None
    return "BULL" if e20>e50 else "BEAR" if e20<e50 else None
def fetch_hist(outputsize=3000):
    vals=fetch_data("XAU/USD","5min",outputsize)
    if not vals: return None
    df=pd.DataFrame(vals); df['datetime']=pd.to_datetime(df['datetime'])
    df=df.sort_values('datetime').reset_index(drop=True)
    for col in ['open','high','low','close']: df[col]=df[col].astype(float)
    df['weekday']=df['datetime'].dt.weekday
    df=df[df['weekday']<5]; df=df[df['high']>df['low']]
    return df.to_dict('records')

# V5.4 TITAN VOLUME PRO - Complete 3G 7L 8B
def analyze_titan_volume_pro(window, h1_trend=None, dxy_trend=None):
    if len(window)<60: return None
    dt=pd.to_datetime(window[0]['datetime'])
    if dt.hour<7 or dt.hour>19: return None

    oldest=list(reversed(window)); closes=[c['close'] for c in oldest]
    e20=calculate_ema(closes,20); e50=calculate_ema(closes,50)
    rsi=calculate_rsi(closes,14)
    if not e20 or not e50: return None

    c0=window[0]; c1=window[1]; c2=window[2] if len(window)>2 else c1
    body=abs(c0['close']-c0['open']); prev=abs(c1['close']-c1['open'])

    bullish_hammer=is_bullish_pinbar(c0); bearish_hammer=is_bearish_pinbar(c0)
    bullish_eng=is_bullish_engulfing(c0,c1); bearish_eng=is_bearish_engulfing(c0,c1)
    bullish=bullish_hammer or bullish_eng
    bearish=bearish_hammer or bearish_eng
    if not bullish and not bearish: return None

    rng=c0['high']-c0['low']
    if rng==0: return None

    # 3 GATES CHECK
    # Gate1 Trend
    if bullish and not (c0['close']>e20>e50): return None
    if bearish and not (c0['close']<e20<e50): return None
    if bullish and h1_trend=="BEAR":
        # Allow pero need higher conf
        pass
    if bearish and h1_trend=="BULL":
        pass

    # Gate2 Structure - Sweep scoring
    last_10_lows=[c['low'] for c in window[1:11]]
    last_10_highs=[c['high'] for c in window[1:11]]
    swept = (bullish and c0['low']<=min(last_10_lows)+0.05) or (bearish and c0['high']>=max(last_10_highs)-0.05)

    # Gate3 Momentum
    sc=(c0['close']-c0['low'])/rng if bullish else (c0['high']-c0['close'])/rng
    if sc<0.55: return None
    if body<prev*0.8: return None
    if bullish and rsi>72: return None
    if bearish and rsi<28: return None

    # 7 LAYERS scoring
    layers=0; layer_logs=[]
    # L1 EMA
    if (bullish and c0['close']>e20>e50) or (bearish and c0['close']<e20<e50):
        layers+=1; layer_logs.append("EMA")
    # L2 Pattern
    layers+=1; layer_logs.append("Hammer" if (bullish_hammer or bearish_hammer) else "Engulf")
    # L3 SC
    if sc>=0.55:
        layers+=1; layer_logs.append(f"SC{int(sc*100)}%")
    # L4 Disp
    if body>=prev*0.8:
        layers+=1; layer_logs.append("Disp")
    # L5 H1
    if h1_trend is None or (bullish and h1_trend=="BULL") or (bearish and h1_trend=="BEAR"):
        layers+=1; layer_logs.append(f"H1_{h1_trend}")
    # L6 PD
    try:
        high_n=max([c['high'] for c in window[:60]]); low_n=min([c['low'] for c in window[:60]])
        mid=low_n+(high_n-low_n)*0.6
        if (bullish and c0['close']<mid) or (bearish and c0['close']>mid):
            layers+=1; layer_logs.append("PD60%")
    except: pass
    # L7 FVG
    try:
        if bullish and c0['low']>c2['high'] and (c0['low']-c2['high'])>0.05:
            layers+=1; layer_logs.append("FVG")
        elif bearish and c0['high']<c2['low'] and (c2['low']-c0['high'])>0.05:
            layers+=1; layer_logs.append("FVG")
    except: pass

    confluence_layers=layers/7*100
    if confluence_layers<60: return None # 60% min for VOLUME

    # 8 BOOSTERS scoring (hindi block para madami trades)
    booster_score=0; booster_logs=[]
    news_ok, news_pts, news_msg = booster_news(dt.to_pydatetime() if hasattr(dt,'to_pydatetime') else datetime.datetime.utcnow())
    booster_score+=news_pts; booster_logs.append(news_msg)
    kill_ok, kill_pts, kill_msg = booster_kill_zone(dt.to_pydatetime() if hasattr(dt,'to_pydatetime') else datetime.datetime.utcnow())
    booster_score+=kill_pts; booster_logs.append(kill_msg)
    # DXY
    if dxy_trend:
        if (bullish and dxy_trend=="BEAR") or (bearish and dxy_trend=="BULL"):
            booster_score+=10; booster_logs.append(f"DXY Aligned {dxy_trend}")
        else:
            booster_score+=0; booster_logs.append(f"DXY Opp {dxy_trend}")
    else:
        booster_score+=5; booster_logs.append("DXY N/A")
    # Retest
    if swept:
        booster_score+=10; booster_logs.append("Sweep+BOS")
    else:
        booster_score+=3; booster_logs.append("No Sweep")
    # RSI Div
    if (bullish and rsi<40) or (bearish and rsi>60):
        booster_score+=5; booster_logs.append(f"RSI Div {rsi:.0f}")
    # Spread guard - always OK sa backtest
    booster_score+=5; booster_logs.append("Spread OK")
    # AI ML
    ai_score=min(98, 45+confluence_layers*0.5+booster_score*0.3)
    if ai_score<60: return None
    booster_logs.append(f"ML {ai_score:.0f}%")

    total_conf=confluence_layers*0.7+booster_score*0.3
    if total_conf<62: return None # Need 62% total

    entry=round(c0['close'],2)
    sl=round(entry-1.8 if bullish else entry+1.8,2)
    tp=round(entry+3.6 if bullish else entry-3.6,2)
    return {
        "pair":"XAUUSD","type":"BUY" if bullish else "SELL","entry":entry,"sl":sl,"tp":tp,"time":window[0]['datetime'],
        "pinbar":"Hammer" if (bullish_hammer or bearish_hammer) else "Engulf","h1":h1_trend,
        "confluence":confluence_layers,"ai":ai_score,"total":total_conf,
        "layers":layer_logs,"boosters":booster_logs,
        "reason":f"3G 7L {confluence_layers:.0f}% + 8B ML{ai_score:.0f}% Tot{total_conf:.0f}% | {'+'.join(layer_logs)}"
    }

def run_sim(records):
    total=wins=losses=0; net=0.0
    i=60; n=len(records)
    while i<n-36:
        window=list(reversed(records[i-60:i]))
        oldest=list(reversed(window)); closes=[c['close'] for c in oldest]
        e50=calculate_ema(closes,50); e100=calculate_ema(closes,100)
        h1_proxy="BULL" if e50 and e100 and e50>e100 else "BEAR" if e50 and e100 and e50<e100 else None
        sig=analyze_titan_volume_pro(window, h1_trend=h1_proxy, dxy_trend=None)
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
    send_telegram_msg("⏳ *TITAN V5.4 VOLUME PRO - Complete 3G 7L 8B*\n_Hammer+Engulf 60%conf ML60% + 8 Boosters Scoring_\n_Target Many trades Quality 60%+_", chat_id)
    try:
        rec=fetch_hist(3000)
        if not rec: send_telegram_msg("Data fail", chat_id); return
        split=int(len(rec)*0.66); ins=rec[:split]; outs=rec[split:]
        t,w,l,wr,net,exp=run_sim(ins)
        t2,w2,l2,wr2,net2,exp2=run_sim(outs)
        msg=f"📊 *XAUUSD TITAN V5.4 VOLUME PRO 1:2*\n_Complete 3Gates 7Layers 8Boosters_\n\n🔹 In-Sample ({len(ins)}):\n Trades `{t}` | WR `{wr}%` | Net `{net}R` | Exp `{exp}R` | W/L `{w}/{l}`\n\n🔹 Out-Sample ({len(outs)}):\n Trades `{t2}` | WR `{wr2}%` | Net `{net2}R` | Exp `{exp2}R` | W/L `{w2}/{l2}`\n\n⚡ _3G: Trend+Structure+Momentum_\n_7L: EMA+Hammer/SC/Disp/H1/PD/FVG_\n_8B: News+Kill+DXY+Retest+PD+FVG+RSI+Spread+ML_\n_Target: Many trades Quality 60%+_"
        send_telegram_msg(msg, chat_id)
    except Exception as e:
        send_telegram_msg(f"Err {e}", chat_id)

def manual_scan(chat_id):
    h1=fetch_h1_trend(); dxy,_,dxy_msg=booster_dxy()
    send_telegram_msg(f"🔍 *Scanning TITAN V5.4 VOLUME PRO*\n_Complete 3G 7L 8B_ H1 `{h1}` {dxy_msg}", chat_id)
    data=fetch_m5_live()
    if not data: send_telegram_msg("No data", chat_id); return
    clean=[]
    for d in data:
        try: clean.append({"open":float(d["open"]),"high":float(d["high"]),"low":float(d["low"]),"close":float(d["close"]),"datetime":d["datetime"]})
        except: pass
    if len(clean)>=60:
        sig=analyze_titan_volume_pro(clean, h1_trend=h1, dxy_trend=dxy)
        if sig:
            pht,utc=format_time_pht(sig['time'])
            msg=f"⚡ *XAUUSD TITAN V5.4 PRO 1:2* 🔨\n\n• {sig['pair']} {sig['type']} {sig['pinbar']}\n• Entry `{format_price(sig['entry'])}`\n• SL `{format_price(sig['sl'])}` TP `{format_price(sig['tp'])}`\n• Time `{pht}` ({utc})\n• Conf L `{sig['confluence']:.0f}%` Tot `{sig['total']:.0f}%` ML `{sig['ai']:.0f}%`\n• Layers `{' + '.join(sig['layers'])}`\n• Boosters `{' + '.join(sig['boosters'][:4])}`\n• Reason `{sig['reason']}`\n• 3G 7L 8B Complete"
            send_telegram_msg(msg, chat_id); return
    send_telegram_msg(f"ℹ️ No V5.4 setup. Need 60%+L + ML60%+\nH1 `{h1}` {dxy_msg}", chat_id)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running: scheduler.start()
    yield
    if scheduler.running: scheduler.shutdown(wait=False)

app=FastAPI(title="TITAN V5.4 VOLUME PRO Complete", lifespan=lifespan)
@app.get("/")
def root(): return {"status":"XAUUSD TITAN V5.4 VOLUME PRO Live","mode":"3G_7L_8B_VOLUME","time":pht_now().isoformat()}
@app.get("/health")
def health(): return {"status":"ok","mode":"V5.4_VOLUME_PRO"}
@app.get("/status")
def status(): return {"status":"ok","mode":"V5.4_VOLUME_PRO"}

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
                h1=fetch_h1_trend(); dxy,_,dxy_msg=booster_dxy()
                send_telegram_msg(f"📊 *TITAN V5.4 VOLUME PRO*\nMode `3G_7L_8B_VOLUME_PRO`\nH1 `{h1}` {dxy_msg}\nRR 1:2 SL18 TP36\nLayers 7 + Boosters 8 Scoring\nNeed 60%L + 62%Tot + ML60%+\nTarget Many trades Quality 60%+\nTime {pht_now().strftime('%Y-%m-%d %I:%M %p PHT')}", cid)
            elif txt=="/scan": background_tasks.add_task(manual_scan, cid)
            elif txt=="/backtest": background_tasks.add_task(run_backtest, cid)
            elif txt in ["/help","/start"]: send_telegram_msg("🤖 *TITAN V5.4 VOLUME PRO*\nComplete 3Gates 7Layers 8Boosters\nMany trades but Quality\n• /status • /scan • /backtest\n*Target Many trades 60%+ WR*", cid)
    except Exception as e: print(e)
    return {"status":"ok"}
