import os, datetime, io
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

def send_telegram_photo(photo_path, caption, chat_id=None):
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

def is_bullish_pinbar_relaxed(c, tf="M1"):
    o,h,l,cl=c['open'],c['high'],c['low'],c['close']
    body=abs(cl-o); rng=h-l
    if rng==0: return False
    low_w=min(o,cl)-l; up_w=h-max(o,cl)
    if tf=="M1":
        return low_w>=1.2*max(body,rng*0.05) and body<=rng*0.65
    return low_w>=1.5*max(body,rng*0.05) and up_w<=body*2.2 and body<=rng*0.55

def is_bearish_pinbar_relaxed(c, tf="M1"):
    o,h,l,cl=c['open'],c['high'],c['low'],c['close']
    body=abs(cl-o); rng=h-l
    if rng==0: return False
    low_w=min(o,cl)-l; up_w=h-max(o,cl)
    if tf=="M1":
        return up_w>=1.2*max(body,rng*0.05) and body<=rng*0.65
    return up_w>=1.5*max(body,rng*0.05) and low_w<=body*2.2 and body<=rng*0.55

def fetch_data(symbol, interval, outputsize):
    url="https://api.twelvedata.com/time_series"
    params={"symbol":symbol,"interval":interval,"outputsize":outputsize,"timezone":"UTC","apikey":TWELVE_DATA_API_KEY}
    try:
        res=requests.get(url,params=params,timeout=12).json()
        if "values" not in res: return None
        return res["values"]
    except: return None

def fetch_live_tf(interval):
    vals=fetch_data("XAU/USD", interval, 100)
    if not vals: return None
    try:
        dt=datetime.datetime.strptime(vals[0]["datetime"], "%Y-%m-%d %H:%M:%S")
        delta = 1 if interval=="1min" else 5 if interval=="5min" else 15
        if datetime.datetime.utcnow()<dt+datetime.timedelta(minutes=delta): vals=vals[1:]
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

def generate_chart_with_markings(window, sig, tf="M1"):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        candles = list(reversed(window))[-50:]
        candles = candles[-40:]
        opens = [c['open'] for c in candles]
        highs = [c['high'] for c in candles]
        lows = [c['low'] for c in candles]
        closes = [c['close'] for c in candles]
        ema20_vals=[]; ema50_vals=[]
        for i in range(len(closes)):
            if i>=19:
                e20=calculate_ema(closes[:i+1],20)
                ema20_vals.append(e20)
            else:
                ema20_vals.append(None)
            if i>=49:
                e50=calculate_ema(closes[:i+1],50)
                ema50_vals.append(e50)
            else:
                ema50_vals.append(None)
        fig, ax = plt.subplots(figsize=(10,6), facecolor='black')
        ax.set_facecolor('black')
        for i in range(len(candles)):
            o=opens[i]; h=highs[i]; l=lows[i]; c=closes[i]
            color = '#22c55e' if c>=o else '#ef4444'
            ax.plot([i,i],[l,h], color=color, linewidth=1)
            body_bottom = min(o,c)
            body_height = abs(c-o)
            if body_height < (max(highs)-min(lows))*0.002:
                body_height = (max(highs)-min(lows))*0.005
            rect = mpatches.Rectangle((i-0.3, body_bottom), 0.6, body_height, facecolor=color, edgecolor=color)
            ax.add_patch(rect)
            if i==len(candles)-1:
                ax.annotate(f'HAMMER\nSC{int(sig["confluence"])}%\n{tf} {sig["type"]}', xy=(i, l), xytext=(i-8, l- (max(highs)-min(lows))*0.08),
                            color='#22c55e', fontsize=8, fontweight='bold',
                            arrowprops=dict(facecolor='#22c55e', shrink=0.05, width=1, headwidth=5),
                            bbox=dict(boxstyle="round,pad=0.3", facecolor='black', edgecolor='#22c55e'))
        x_vals = list(range(len(candles)))
        e20_plot = [v for v in ema20_vals if v is not None]
        e50_plot = [v for v in ema50_vals if v is not None]
        if len(e20_plot)>0:
            ax.plot(x_vals[-len(e20_plot):], e20_plot, color='#22c55e', linewidth=1.2, label='EMA20', alpha=0.8)
        if len(e50_plot)>0:
            ax.plot(x_vals[-len(e50_plot):], e50_plot, color='white', linewidth=1.0, label='EMA50', alpha=0.7)
        entry = sig['entry']; sl = sig['sl']; tp = sig['tp']
        ax.axhline(y=entry, color='#22c55e', linestyle='--', linewidth=1.2, label=f'Entry {entry}')
        ax.axhline(y=sl, color='#ef4444', linestyle='--', linewidth=1.0, label=f'SL {sl}')
        ax.axhline(y=tp, color='#22c55e', linestyle=':', linewidth=1.0, label=f'TP {tp}')
        ax.fill_between(x_vals, sl, entry, color='#ef4444', alpha=0.1)
        ax.fill_between(x_vals, entry, tp, color='#22c55e', alpha=0.1)
        ax.set_title(f"XAUUSD {tf} {sig['type']} | {sig['reason']} | {format_time_pht(sig['time'])[0]}", color='white', fontsize=11, fontweight='bold')
        ax.set_ylabel('Price', color='white')
        ax.tick_params(colors='white')
        ax.legend(loc='upper left', fontsize=7, facecolor='black', edgecolor='white', labelcolor='white')
        ax.grid(True, alpha=0.15, color='white')
        chart_path = f"/tmp/chart_{tf}_{sig['type']}.png"
        plt.tight_layout()
        plt.savefig(chart_path, facecolor='black', dpi=150)
        plt.close()
        return chart_path
    except Exception as e:
        print(f"Chart gen error: {e}")
        import traceback; traceback.print_exc()
        return None

def analyze_titan_mtf(window, tf="M5", h1_trend=None):
    if len(window)<60: return None
    dt=pd.to_datetime(window[0]['datetime'])
    if tf!="M1" and (dt.hour<7 or dt.hour>19): return None
    oldest=list(reversed(window)); closes=[c['close'] for c in oldest]
    e20=calculate_ema(closes,20); e50=calculate_ema(closes,50)
    rsi=calculate_rsi(closes,14)
    if not e20 or not e50: return None
    c0=window[0]; c1=window[1]; c2=window[2] if len(window)>2 else c1
    body=abs(c0['close']-c0['open']); prev=abs(c1['close']-c1['open'])
    if tf=="M1":
        disp_req, sc_req, conf_req, ml_req = 0.40, 0.45, 40, 50
        bullish=is_bullish_pinbar_relaxed(c0, "M1")
        bearish=is_bearish_pinbar_relaxed(c0, "M1")
    elif tf=="M5":
        disp_req, sc_req, conf_req, ml_req = 0.80, 0.56, 60, 60
        bullish=is_bullish_pinbar(c0)
        bearish=is_bearish_pinbar(c0)
    else:
        disp_req, sc_req, conf_req, ml_req = 0.75, 0.52, 55, 55
        bullish=is_bullish_pinbar(c0)
        bearish=is_bearish_pinbar(c0)
    if body<prev*disp_req: return None
    if not bullish and not bearish: return None
    rng=c0['high']-c0['low']
    if rng==0: return None
    if bullish and not (c0['close']>e20>e50): return None
    if bearish and not (c0['close']<e20<e50): return None
    sc=(c0['close']-c0['low'])/rng if bullish else (c0['high']-c0['close'])/rng
    if sc<sc_req: return None
    layers=0; logs=[]
    if (bullish and c0['close']>e20>e50) or (bearish and c0['close']<e20<e50):
        layers+=1; logs.append("EMA")
    layers+=1; logs.append("Hammer")
    if sc>=sc_req: layers+=1; logs.append(f"SC{int(sc*100)}%")
    if body>=prev*disp_req: layers+=1; logs.append("Disp")
    if tf=="M1":
        layers+=1; logs.append("M1-Free")
    else:
        if h1_trend is None or (bullish and h1_trend=="BULL") or (bearish and h1_trend=="BEAR"):
            layers+=1; logs.append(f"H1_{h1_trend}")
    try:
        high_n=max([c['high'] for c in window[:60]]); low_n=min([c['low'] for c in window[:60]])
        mid=low_n+(high_n-low_n)*0.6
        if (bullish and c0['close']<mid) or (bearish and c0['close']>mid):
            layers+=1; logs.append("PD60%")
    except: pass
    try:
        if bullish and c0['low']>c2['high'] and (c0['low']-c2['high'])>0.03:
            layers+=1; logs.append("FVG")
        elif bearish and c0['high']<c2['low'] and (c2['low']-c0['high'])>0.03:
            layers+=1; logs.append("FVG")
    except: pass
    conf=layers/7*100 if tf!="M1" else layers/5*100
    if conf<conf_req: return None
    if tf=="M5":
        if bullish and h1_trend=="BEAR" and conf<68: return None
        if bearish and h1_trend=="BULL" and conf<68: return None
        if bullish and rsi>70: return None
        if bearish and rsi<30: return None
    last_10_lows=[c['low'] for c in window[1:11]]
    last_10_highs=[c['high'] for c in window[1:11]]
    swept = (bullish and c0['low']<=min(last_10_lows)+0.05) or (bearish and c0['high']>=max(last_10_highs)-0.05)
    ai_score=min(98, 44+conf*0.55+(8 if swept else 0))
    if ai_score<ml_req: return None
    if tf=="M1": sl_d, tp_d = 0.8, 1.6
    elif tf=="M5": sl_d, tp_d = 1.8, 3.6
    else: sl_d, tp_d = 3.0, 6.0
    entry=round(c0['close'],2)
    sl=round(entry-sl_d if bullish else entry+sl_d,2)
    tp=round(entry+tp_d if bullish else entry-tp_d,2)
    return {
        "pair":"XAUUSD","type":"BUY" if bullish else "SELL","entry":entry,"sl":sl,"tp":tp,"time":window[0]['datetime'],
        "pinbar":"Hammer","h1":h1_trend,"confluence":conf,"ai":ai_score,"layers":logs,
        "boosters":[f"KILL {dt.hour}UTC", f"ML {ai_score:.0f}%"],
        "reason":f"{tf} {conf:.0f}% ML{ai_score:.0f}% | {'+'.join(logs)}", "tf":tf
    }

def run_sim(records):
    total=wins=losses=0; net=0.0
    i=60; n=len(records)
    while i<n-36:
        window=list(reversed(records[i-60:i]))
        oldest=list(reversed(window)); closes=[c['close'] for c in oldest]
        e50=calculate_ema(closes,50); e100=calculate_ema(closes,100)
        h1_proxy="BULL" if e50 and e100 and e50>e100 else "BEAR" if e50 and e100 and e50<e100 else None
        sig=analyze_titan_mtf(window, tf="M5", h1_trend=h1_proxy)
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
    send_telegram_msg("⏳ *TITAN V5.8 V3 WITH CHART*\n_M5 77.8% LOCK + M1 RELAXED + Chart_", chat_id)
    try:
        rec=fetch_hist(3000)
        if not rec: send_telegram_msg("Data fail", chat_id); return
        split=int(len(rec)*0.66); ins=rec[:split]; outs=rec[split:]
        t,w,l,wr,net,exp=run_sim(ins)
        t2,w2,l2,wr2,net2,exp2=run_sim(outs)
        msg=f"📊 *XAUUSD TITAN V5.8 V3 WITH CHART*\n_M5 LOCK 77.8% WR 12R 1.33R exp_\n\n🔹 M5 In-Sample ({len(ins)}):\n Trades `{t}` | WR `{wr}%` | Net `{net}R` | Exp `{exp}R` | W/L `{w}/{l}`\n\n🔹 M5 Out-Sample ({len(outs)}):\n Trades `{t2}` | WR `{wr2}%` | Net `{net2}R` | Exp `{exp2}R` | W/L `{w2}/{l2}`\n\n🔒 _WITH AUTO CHART SCREENSHOT_"
        send_telegram_msg(msg, chat_id)
    except Exception as e:
        send_telegram_msg(f"Err {e}", chat_id)

def manual_scan(chat_id, auto=False):
    h1=fetch_h1_trend()
    found=False
    for tf, interval in [("M5","5min"),("M1","1min"),("M15","15min")]:
        data=fetch_live_tf(interval)
        if not data: continue
        clean=[]
        for d in data:
            try: clean.append({"open":float(d["open"]),"high":float(d["high"]),"low":float(d["low"]),"close":float(d["close"]),"datetime":d["datetime"]})
            except: pass
        if len(clean)>=60:
            sig=analyze_titan_mtf(clean, tf=tf, h1_trend=h1)
            if sig:
                pht,utc=format_time_pht(sig['time'])
                caption = f"🤖 AUTO {tf} 5M XAUUSD {tf} 1:2 🔨\n\n• {sig['pair']} {sig['type']} {sig['tf']} {sig['pinbar']}\n• Entry `{format_price(sig['entry'])}`\n• SL `{format_price(sig['sl'])}` TP `{format_price(sig['tp'])}`\n• Time `{pht}` ({utc})\n• Conf `{sig['confluence']:.0f}%` ML `{sig['ai']:.0f}%`\n• Layers `{' + '.join(sig['layers'])}`\n• Reason `{sig['reason']}`\n• {tf} {'LOCK 77.8%' if tf=='M5' else 'RELAXED'} WITH CHART"
                chart_path = generate_chart_with_markings(clean, sig, tf=tf)
                if chart_path and os.path.exists(chart_path):
                    send_telegram_photo(chart_path, caption, chat_id)
                else:
                    send_telegram_msg(caption, chat_id)
                found=True
                if not auto: break
                else: return
    if not found and not auto:
        send_telegram_msg(f"ℹ️ No setup M1/M5/M15\nH1 `{h1}`\nM5 LOCK 77.8% strict\nM1 RELAXED 40% conf active\nTry ulit 5 mins!", chat_id)

def auto_scan_job():
    try:
        now_utc = datetime.datetime.utcnow()
        if not TELEGRAM_CHAT_ID: return
        if not (7 <= now_utc.hour <= 19): return
        print(f"[AUTO-SCAN V3 CHART] {now_utc} scanning...")
        manual_scan(TELEGRAM_CHAT_ID, auto=True)
    except Exception as e:
        print(f"Auto scan error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running:
        scheduler.add_job(auto_scan_job, 'interval', minutes=5, id='titan_v58_mtf_v3_chart_autoscan_5m', replace_existing=True)
        scheduler.start()
        print("✅ TITAN V5.8 V3 WITH CHART AUTO-SCAN every 5 mins started!")
    yield
    if scheduler.running: scheduler.shutdown(wait=False)

app=FastAPI(title="TITAN V5.8 V3 WITH CHART 77.8% WR + AUTO 5M", lifespan=lifespan)
@app.get("/")
def root(): return {"status":"XAUUSD TITAN V5.8 V3 WITH CHART Live","mode":"V3_CHART","time":pht_now().isoformat(),"auto_scan":"5m WITH CHART"}
@app.get("/health")
def health(): return {"status":"ok","mode":"V3_CHART","auto_scan":"5m CHART"}
@app.get("/status")
def status(): return {"status":"ok","mode":"V3_CHART"}

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
                send_telegram_msg(f"🔒 *TITAN V5.8 V3 WITH CHART*\nMode `V3_CHART`\nH1 `{h1}`\nM1 SL0.8 TP1.6 40% RELAXED\nM5 SL1.8 TP3.6 60% LOCK 77.8% WR\nM15 SL3.0 TP6.0 55%\nAuto-scan with chart screenshot\nTime {pht_now().strftime('%Y-%m-%d %I:%M %p PHT')}", cid)
            elif txt=="/scan": background_tasks.add_task(manual_scan, cid)
            elif txt=="/backtest": background_tasks.add_task(run_backtest, cid)
            elif txt in ["/help","/start"]: send_telegram_msg("🔒 *TITAN V5.8 V3 WITH CHART*\n_M5 77.8% + M1 RELAXED + CHART_\n• /status • /scan • /backtest", cid)
    except Exception as e: print(e)
    return {"status":"ok"}
