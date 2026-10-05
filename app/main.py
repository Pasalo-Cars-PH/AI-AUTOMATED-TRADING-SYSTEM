import os, datetime
from contextlib import asynccontextmanager
import requests, pandas as pd
from fastapi import FastAPI, Request, BackgroundTasks
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

# SAFETY LOCK - ABSOLUTE PAPER ONLY - NO LIVE EXECUTION
MASTER_LIVE_ENABLE = False  # MUST REMAIN FALSE - PAPER ONLY - NO BROKER EXECUTION PATH

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
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - SAFETY LOCK PAPER ONLY", chat_id)
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

# M5 LOCK - REPORTED 77.8% WR - BACKTEST SAMPLE ONLY - NOT INTRINSIC PROPERTY
# Thresholds: 0.80 disp / 0.56 SC / 60% conf / 60% MODEL_SCORE / 1.5x wick / 55% body
# NOTE: 77.8% WR is REPORTED result from 9-trade sample, NOT guaranteed by code
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

# M1 FLEX V5.9.1 - Controlled Relaxation - AUDIT FIXED
# Wick 1.1x / Body ≤70% / Disp ≥0.35 / SC ≥42% / Conf ≥45% (effective 4/7=57.1%) / MODEL_SCORE ≥48%
def is_bullish_pinbar_relaxed(c, tf="M1"):
    o,h,l,cl=c['open'],c['high'],c['low'],c['close']
    body=abs(cl-o); rng=h-l
    if rng==0: return False
    low_w=min(o,cl)-l
    if tf=="M1":
        return low_w>=1.1*max(body,rng*0.05) and body<=rng*0.70
    return low_w>=1.5*max(body,rng*0.05) and body<=rng*0.55

def is_bearish_pinbar_relaxed(c, tf="M1"):
    o,h,l,cl=c['open'],c['high'],c['low'],c['close']
    body=abs(cl-o); rng=h-l
    if rng==0: return False
    up_w=h-max(o,cl)
    if tf=="M1":
        return up_w>=1.1*max(body,rng*0.05) and body<=rng*0.70
    return up_w>=1.5*max(body,rng*0.05) and body<=rng*0.55

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

def fetch_hist_tf(interval, outputsize=3000):
    vals=fetch_data("XAU/USD", interval, outputsize)
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
                ax.annotate(f'V5.9.1 {tf} {sig["type"]}\nConf {sig["confluence"]:.0f}% MODEL {sig["model_score"]:.0f}%\n4/7 layers min', xy=(i, l), xytext=(i-12, l- (max(highs)-min(lows))*0.14),
                            color='#22c55e', fontsize=6, fontweight='bold',
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
        ax.set_title(f"XAUUSD {tf} {sig['type']} V5.9.1 PAPER ONLY | {sig['reason']} | {format_time_pht(sig['time'])[0]} 4/7 layers", color='white', fontsize=8, fontweight='bold')
        ax.set_ylabel('Price', color='white')
        ax.tick_params(colors='white')
        ax.legend(loc='upper left', fontsize=6, facecolor='black', edgecolor='white', labelcolor='white')
        ax.grid(True, alpha=0.15, color='white')
        chart_path = f"/tmp/chart_{tf}_{sig['type']}_V591.png"
        plt.tight_layout()
        plt.savefig(chart_path, facecolor='black', dpi=150)
        plt.close()
        return chart_path
    except Exception as e:
        print(f"Chart gen error: {e}")
        return None

# V5.9.1 - AUDIT FIXED - PD60 explicit math, MODEL_SCORE renamed, 4/7 layers documented
def analyze_titan_mtf(window, tf="M5", h1_trend=None):
    if len(window)<60: return None
    dt=pd.to_datetime(window[0]['datetime'])
    # Kill Zone 07:00-19:00 UTC ON for ALL TF per V5.9 gate
    if dt.hour<7 or dt.hour>19: return None

    oldest=list(reversed(window)); closes=[c['close'] for c in oldest]
    e20=calculate_ema(closes,20); e50=calculate_ema(closes,50)
    rsi=calculate_rsi(closes,14)
    if not e20 or not e50: return None

    c0=window[0]; c1=window[1]; c2=window[2] if len(window)>2 else c1
    body=abs(c0['close']-c0['open']); prev=abs(c1['close']-c1['open'])

    if tf=="M1":
        # V5.9.1 M1 FLEX: Base Disp 0.35 + FVG OR StrongDisp 0.55/reclaim
        # Conf >=45% means effective 4/7 = 57.1% minimum layers
        disp_req, sc_req, conf_req, model_req = 0.35, 0.42, 45, 48
        bullish=is_bullish_pinbar_relaxed(c0, "M1")
        bearish=is_bearish_pinbar_relaxed(c0, "M1")
        rsi_high, rsi_low = 78, 22
    elif tf=="M5":
        # M5 LOCK untouched - REPORTED 77.8% WR from 9-trade sample, NOT intrinsic
        disp_req, sc_req, conf_req, model_req = 0.80, 0.56, 60, 60
        bullish=is_bullish_pinbar(c0)
        bearish=is_bearish_pinbar(c0)
        rsi_high, rsi_low = 70, 30
    else: # M15 fallback - conf 55% effective 57.1% (4/7), set to 57 for explicit
        disp_req, sc_req, conf_req, model_req = 0.75, 0.52, 57, 55
        bullish=is_bullish_pinbar(c0)
        bearish=is_bearish_pinbar(c0)
        rsi_high, rsi_low = 70, 30

    if body<prev*disp_req: return None
    if not bullish and not bearish: return None
    rng=c0['high']-c0['low']
    if rng==0: return None
    if bullish and not (c0['close']>e20>e50): return None
    if bearish and not (c0['close']<e20<e50): return None
    sc=(c0['close']-c0['low'])/rng if bullish else (c0['high']-c0['close'])/rng
    if sc<sc_req: return None

    # --- PD60 EXPLICIT MATH FIX per audit ---
    # Old: mid = low + 0.6*range, BUY close<mid (60% range), SELL close>mid (40% range) - asymmetric
    # New explicit: 
    # BUY discount = lower 60%: close <= low + range*0.6
    # SELL premium = upper 60%: close >= low + range*0.4 (top 60% starts at 40% from bottom)
    # This gives symmetric 60% zones, overlap 40-60% valid for both but directional filter separates
    pd60_ok=False
    fvg_ok=False
    strong_disp_ok=False
    try:
        high_n=max([c['high'] for c in window[:60]]); low_n=min([c['low'] for c in window[:60]])
        rng_n=high_n-low_n
        buy_threshold = low_n + rng_n*0.6  # lower 60% is discount
        sell_threshold = low_n + rng_n*0.4  # upper 60% starts at 40% = premium
        if bullish and c0['close']<=buy_threshold:
            pd60_ok=True
        elif bearish and c0['close']>=sell_threshold:
            pd60_ok=True
    except: pass
    try:
        # FVG directional - BUY bullish gap, SELL bearish gap
        if bullish and c0['low']>c2['high'] and (c0['low']-c2['high'])>0.03:
            fvg_ok=True
        elif bearish and c0['high']<c2['low'] and (c2['low']-c0['high'])>0.03:
            fvg_ok=True
    except: pass
    try:
        # Strong displacement/reclaim - directional - body >=0.55x prev + direction check
        if bullish:
            if body>=prev*0.55 and c0['close']>c0['open']:
                strong_disp_ok=True
            elif c0['close']>c1['high']:
                strong_disp_ok=True
        else: # bearish
            if body>=prev*0.55 and c0['close']<c0['open']:
                strong_disp_ok=True
            elif c0['close']<c1['low']:
                strong_disp_ok=True
    except: pass

    layers=0; logs=[]
    if (bullish and c0['close']>e20>e50) or (bearish and c0['close']<e20<e50):
        layers+=1; logs.append("EMA")
    layers+=1; logs.append("Hammer")
    if sc>=sc_req: layers+=1; logs.append(f"SC{int(sc*100)}%")
    if body>=prev*disp_req: layers+=1; logs.append("Disp")

    if tf=="M1":
        if not pd60_ok:
            return None
        layers+=1; logs.append("PD60%")
        if not (fvg_ok or strong_disp_ok):
            return None
        if fvg_ok:
            layers+=1; logs.append("FVG")
        else:
            layers+=1; logs.append("StrDisp")
        layers+=1; logs.append("M1-FLEX")
    else:
        if pd60_ok:
            layers+=1; logs.append("PD60%")
        if fvg_ok:
            layers+=1; logs.append("FVG")
        if h1_trend is None or (bullish and h1_trend=="BULL") or (bearish and h1_trend=="BEAR"):
            layers+=1; logs.append(f"H1_{h1_trend}")

    # Conf: 7 layers total, 3/7=42.9%, 4/7=57.1%, so >=45% effective = 4/7 min
    conf=layers/7*100
    if conf<conf_req: return None

    if tf=="M5":
        if bullish and h1_trend=="BEAR" and conf<68: return None
        if bearish and h1_trend=="BULL" and conf<68: return None
        if bullish and rsi>rsi_high: return None
        if bearish and rsi<rsi_low: return None
    elif tf=="M1":
        if bullish and rsi>rsi_high: return None
        if bearish and rsi<rsi_low: return None
    else:
        if bullish and rsi>rsi_high: return None
        if bearish and rsi<rsi_low: return None

    last_10_lows=[c['low'] for c in window[1:11]]
    last_10_highs=[c['high'] for c in window[1:11]]
    swept = (bullish and c0['low']<=min(last_10_lows)+0.05) or (bearish and c0['high']>=max(last_10_highs)-0.05)

    # MODEL_SCORE deterministic formula - NOT real ML - coupled to conf
    # Example: conf=57.1 no sweep => 44+57.1*0.55=75.4 => auto passes 48%
    model_score=min(98, 44+conf*0.55+(8 if swept else 0))
    if model_score<model_req: return None

    if tf=="M1": sl_d, tp_d = 0.8, 1.6
    elif tf=="M5": sl_d, tp_d = 1.8, 3.6
    else: sl_d, tp_d = 3.0, 6.0

    entry=round(c0['close'],2)
    sl=round(entry-sl_d if bullish else entry+sl_d,2)
    tp=round(entry+tp_d if bullish else entry-tp_d,2)
    return {
        "pair":"XAUUSD","type":"BUY" if bullish else "SELL","entry":entry,"sl":sl,"tp":tp,"time":window[0]['datetime'],
        "pinbar":"Hammer","h1":h1_trend,"confluence":conf,"model_score":model_score,"ai":model_score,"layers":logs,
        "boosters":[f"KILL {dt.hour}UTC", f"MODEL {model_score:.0f}%"],
        "reason":f"{tf} {conf:.0f}% MODEL{model_score:.0f}% | {'+'.join(logs)} 4/7min", "tf":tf
    }

def run_sim_tf(records, tf="M5"):
    total=wins=losses=0; net=0.0
    i=60; n=len(records)
    while i<n-36:
        window=list(reversed(records[i-60:i]))
        oldest=list(reversed(window)); closes=[c['close'] for c in oldest]
        e50=calculate_ema(closes,50); e100=calculate_ema(closes,100)
        h1_proxy="BULL" if e50 and e100 and e50>e100 else "BEAR" if e50 and e100 and e50<e100 else None
        sig=analyze_titan_mtf(window, tf=tf, h1_trend=h1_proxy)
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
    pf=round((wins*2)/(losses*1),2) if losses>0 else round(wins*2,2) if wins>0 else 0
    return total,wins,losses,wr,net,exp,pf

def run_backtest(chat_id):
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - PAPER ONLY", chat_id)
        return
    send_telegram_msg("⏳ *TITAN V5.9.1 M1 FLEX PAPER BACKTEST - ALL TF*\n_M5 LOCK REPORTED 77.8% (9-trade sample)_ + _M1 FLEX 45% (4/7 layers)_\n_PAPER ONLY - MODEL_SCORE deterministic_", chat_id)
    try:
        # M5 history for M5 backtest
        rec_m5=fetch_hist_tf("5min", 3000)
        # M1 history for M1 backtest - use 1min data
        rec_m1=fetch_hist_tf("1min", 3000)
        # M15 history
        rec_m15=fetch_hist_tf("15min", 3000)
        
        results={}
        if rec_m5:
            t,w,l,wr,net,exp,pf=run_sim_tf(rec_m5, tf="M5")
            results['M5']= (t,w,l,wr,net,exp,pf, len(rec_m5))
        if rec_m1:
            t,w,l,wr,net,exp,pf=run_sim_tf(rec_m1, tf="M1")
            results['M1']= (t,w,l,wr,net,exp,pf, len(rec_m1))
        if rec_m15:
            t,w,l,wr,net,exp,pf=run_sim_tf(rec_m15, tf="M15")
            results['M15']= (t,w,l,wr,net,exp,pf, len(rec_m15))

        # Combined
        total_trades=sum([v[0] for v in results.values()])
        total_wins=sum([v[1] for v in results.values()])
        total_losses=sum([v[2] for v in results.values()])
        total_net=sum([v[4] for v in results.values()])
        combined_wr=round(total_wins/(total_wins+total_losses)*100,1) if total_wins+total_losses>0 else 0
        combined_exp=round(total_net/total_trades,2) if total_trades>0 else 0
        combined_pf=round((total_wins*2)/(total_losses*1),2) if total_losses>0 else 0

        msg=f"📊 *XAUUSD TITAN V5.9.1 M1 FLEX PAPER - ALL TF VALIDATION*\n_REPORTED M5 77.8% is 9-trade sample - NOT intrinsic_\n\n"
        for tf in ["M5","M1","M15"]:
            if tf in results:
                t,w,l,wr,net,exp,pf, n = results[tf]
                msg+=f"🔹 *{tf} {'LOCK REPORTED 77.8%' if tf=='M5' else 'FLEX 45% 4/7 layers' if tf=='M1' else 'FALLBACK 57%'}* ({n} bars):\n Trades `{t}` | W `{w}` L `{l}` | WR `{wr}%` | PF `{pf}` | Exp `{exp}R` | Net `{net}R`\n\n"
        msg+=f"🔹 *COMBINED PAPER*:\n Trades `{total_trades}` | W `{total_wins}` L `{total_losses}` | WR `{combined_wr}%` | PF `{combined_pf}` | Exp `{combined_exp}R` | Net `{total_net}R`\n\n"
        msg+=f"🔒 _M1 FLEX: Wick1.1x Body70% Disp0.35 SC42% Conf45% (eff 4/7=57.1%) MODEL48% PD60 req (low+0.6*rng BUY / low+0.4*rng SELL) FVG OR StrDisp 0.55+/reclaim RSI78/22 KillZone 07-19 UTC H1 OFF_\n"
        msg+=f"_M5 LOCK: REPORTED 77.8% WR - 9-trade sample - NOT intrinsic - thresholds 0.80/0.56/60%/60%/1.5x/55% untouched_\n"
        msg+=f"_MODEL_SCORE deterministic: 44+conf*0.55+(8 if swept) - NOT real ML - coupled to conf_\n"
        msg+=f"_PAPER VALIDATION ONLY - NEED 100-200 SAMPLE PER TF - APPLES TO APPLES_"

        send_telegram_msg(msg, chat_id)
    except Exception as e:
        import traceback; traceback.print_exc()
        send_telegram_msg(f"Err {e}", chat_id)

def manual_scan(chat_id, auto=False):
    if MASTER_LIVE_ENABLE:
        send_telegram_msg("🚫 LIVE BLOCKED - SAFETY LOCK ACTIVE - PAPER ONLY", chat_id)
        return
    h1=fetch_h1_trend()
    found=False
    # DATA QUALITY gate + M5 priority real
    for tf, interval in [("M5","5min"),("M1","1min"),("M15","15min")]:
        data=fetch_live_tf(interval)
        if not data: continue
        clean=[]
        for d in data:
            try:
                # DATA QUALITY: valid OHLC, high>low
                o=float(d["open"]); h=float(d["high"]); lo=float(d["low"]); c=float(d["close"])
                if h>lo and o>0 and c>0:
                    clean.append({"open":o,"high":h,"low":lo,"close":c,"datetime":d["datetime"]})
            except: pass
        if len(clean)<60: continue
        sig=analyze_titan_mtf(clean, tf=tf, h1_trend=h1)
        if sig:
            pht,utc=format_time_pht(sig['time'])
            caption = f"{'🤖 AUTO' if auto else '⚡ MANUAL'} {tf} 5M XAUUSD {tf} 1:2 V5.9.1 PAPER 🔨\n\n• {sig['pair']} {sig['type']} {sig['tf']} {sig['pinbar']}\n• Entry `{format_price(sig['entry'])}`\n• SL `{format_price(sig['sl'])}` TP `{format_price(sig['tp'])}` RR 1:2\n• Time `{pht}` ({utc})\n• Conf `{sig['confluence']:.0f}%` (4/7=57.1% min eff) MODEL `{sig['model_score']:.0f}%`\n• Layers `{' + '.join(sig['layers'])}`\n• Reason `{sig['reason']}`\n• {tf} {'LOCK REPORTED 77.8% (9-trade sample)' if tf=='M5' else 'FLEX 45% eff 4/7 V5.9.1'} PAPER ONLY"
            chart_path = generate_chart_with_markings(clean, sig, tf=tf)
            if chart_path and os.path.exists(chart_path):
                send_telegram_photo(chart_path, caption, chat_id)
            else:
                send_telegram_msg(caption, chat_id)
            found=True
            break
    if not found and not auto:
        send_telegram_msg(f"ℹ️ No setup M1/M5/M15 V5.9.1 PAPER\nH1 `{h1}`\nM5 LOCK REPORTED 77.8% (9-trade sample NOT intrinsic) 60% 4/7 eff\nM1 FLEX 45% eff 4/7=57.1% MODEL48% PD60 req (low+0.6 BUY / low+0.4 SELL) FVG OR StrDisp0.55+/reclaim SC42% Wick1.1x Body70% Disp0.35 RSI78/22 KillZone 07-19 UTC ON\nTry ulit 5 mins! PAPER ONLY", chat_id)

def auto_scan_job():
    try:
        if MASTER_LIVE_ENABLE:
            print("🚫 LIVE BLOCKED - SAFETY LOCK")
            return
        now_utc = datetime.datetime.utcnow()
        if not TELEGRAM_CHAT_ID: return
        if not (7 <= now_utc.hour <= 19): return
        print(f"[AUTO-SCAN V5.9.1 PAPER] {now_utc} scanning M5->M1->M15 PAPER ONLY...")
        manual_scan(TELEGRAM_CHAT_ID, auto=True)
    except Exception as e:
        print(f"Auto scan error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running:
        scheduler.add_job(auto_scan_job, 'interval', minutes=5, id='titan_v591_m1_flex_paper_autoscan_5m', replace_existing=True)
        scheduler.start()
        print("✅ TITAN V5.9.1 M1 FLEX PAPER AUTO-SCAN 07-19 UTC started! SAFETY LOCK ON - AUDIT FIXED")
    yield
    if scheduler.running: scheduler.shutdown(wait=False)

app=FastAPI(title="TITAN V5.9.1 M1 FLEX PAPER ONLY + M5 LOCK REPORTED 77.8% + AUDIT FIXED", lifespan=lifespan)
@app.get("/")
def root(): return {"status":"XAUUSD TITAN V5.9.1 M1 FLEX PAPER ONLY Live AUDIT FIXED","mode":"V591_M1_FLEX_PAPER_45_4OF7_SAFETY_LOCK","time":pht_now().isoformat(),"auto_scan":"5m M5 LOCK REPORTED + M1 FLEX 4/7 + M15 PAPER ONLY","live_enabled":MASTER_LIVE_ENABLE, "note":"77.8% WR is REPORTED 9-trade sample NOT intrinsic"}
@app.get("/health")
def health(): return {"status":"ok","mode":"V591_M1_FLEX_PAPER_AUDIT_FIXED","auto_scan":"5m PAPER V5.9.1 ALL TF","live_enabled":MASTER_LIVE_ENABLE}
@app.get("/status")
def status(): return {"status":"ok","mode":"V591_M1_FLEX_PAPER_AUDIT_FIXED","live_enabled":MASTER_LIVE_ENABLE}

@app.api_route("/telegram-webhook", methods=["GET","POST"])
@app.api_route("/telegram/webhook", methods=["GET","POST"])
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        update=await request.json()
        if "message" in update and "text" in update["message"]:
            cid=str(update["message"]["chat"]["id"])
            txt=update["message"]["text"].strip().split("@")[0]
            if TELEGRAM_CHAT_ID and cid!=str(TELEGRAM_CHAT_ID): return {"status":"ok"}
            if MASTER_LIVE_ENABLE:
                send_telegram_msg("🚫 SAFETY LOCK ACTIVE - PAPER ONLY - NO LIVE EXECUTION", cid)
                return {"status":"blocked"}
            if txt=="/status":
                h1=fetch_h1_trend()
                send_telegram_msg(f"🔒 *TITAN V5.9.1 M1 FLEX PAPER ONLY AUDIT FIXED*\nMode `V591_AUDIT_FIXED`\nH1 `{h1}`\nM1 FLEX 45% eff 4/7=57.1% MODEL48% PD60 req explicit (BUY <=low+0.6*rng / SELL >=low+0.4*rng) FVG OR StrDisp0.55+/reclaim Wick1.1x Body70% Disp0.35 SC42% RSI78/22 KillZone 07-19 UTC ON H1 OFF RR1:2 SL0.8 TP1.6\nM5 LOCK REPORTED 77.8% (9-trade sample NOT intrinsic) 60% eff 4/7 0.80 disp 0.56 SC 1.5x wick 55% body MODEL60% untouched\nM15 57% eff 4/7 fallback\nSafety Lock MASTER_LIVE_ENABLE=False PAPER ONLY\nMODEL_SCORE deterministic: 44+conf*0.55+(8 if swept) NOT real ML\nTime {pht_now().strftime('%Y-%m-%d %I:%M %p PHT')}", cid)
            elif txt=="/scan": background_tasks.add_task(manual_scan, cid)
            elif txt=="/backtest": background_tasks.add_task(run_backtest, cid)
            elif txt in ["/help","/start"]: send_telegram_msg("🔒 *TITAN V5.9.1 M1 FLEX PAPER ONLY AUDIT FIXED*\n_M5 LOCK REPORTED 77.8% (9-trade sample) untouched_\n_M1 FLEX 45% eff 4/7 MODEL48% PD60 explicit FVG OR StrDisp_\n_PAPER VALIDATION ALL TF - NEED 100-200 SAMPLE_\n• /status • /scan • /backtest", cid)
    except Exception as e: print(e)
    return {"status":"ok"}
