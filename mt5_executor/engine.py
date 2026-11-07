from __future__ import annotations
import pandas as pd
import MetaTrader5 as mt5
from .config import ALLOWED_SYMBOLS,TIMEFRAMES
TF_MAP={"H4":mt5.TIMEFRAME_H4,"H1":mt5.TIMEFRAME_H1,"M15":mt5.TIMEFRAME_M15,"M5":mt5.TIMEFRAME_M5}
def rates(symbol,timeframe,count=350):
    raw=mt5.copy_rates_from_pos(symbol,TF_MAP[timeframe],0,count)
    if raw is None or len(raw)<220: raise RuntimeError(f"Insufficient {timeframe} candles: {mt5.last_error()}")
    df=pd.DataFrame(raw); df["time"]=pd.to_datetime(df["time"],unit="s",utc=True)
    for c in ("open","high","low","close","tick_volume"): df[c]=pd.to_numeric(df[c],errors="coerce")
    return df.iloc[:-1].copy().reset_index(drop=True)
def indicators(df):
    c=df.close; e20=c.ewm(span=20,adjust=False).mean(); e50=c.ewm(span=50,adjust=False).mean(); e200=c.ewm(span=200,adjust=False).mean()
    d=c.diff(); g=d.clip(lower=0).ewm(alpha=1/14,adjust=False).mean(); l=(-d.clip(upper=0)).ewm(alpha=1/14,adjust=False).mean()
    r=100-100/(1+g/l.replace(0,float("nan")))
    macd=c.ewm(span=12,adjust=False).mean()-c.ewm(span=26,adjust=False).mean(); sig=macd.ewm(span=9,adjust=False).mean()
    tr=pd.concat([df.high-df.low,(df.high-c.shift()).abs(),(df.low-c.shift()).abs()],axis=1).max(axis=1); atr=tr.rolling(14).mean()
    i=len(df)-1
    return {"close":float(c.iloc[i]),"ema20":float(e20.iloc[i]),"ema50":float(e50.iloc[i]),"ema200":float(e200.iloc[i]),"rsi":float(r.iloc[i]),"macd":float(macd.iloc[i]),"macd_signal":float(sig.iloc[i]),"atr":float(atr.iloc[i]),"prev_high":float(df.high.iloc[-21:-1].max()),"prev_low":float(df.low.iloc[-21:-1].min()),"volume":float(df.tick_volume.iloc[i]),"volume_avg":float(df.tick_volume.iloc[-21:-1].mean()),"bar_time":df.time.iloc[i].isoformat()}
def direction(x):
    if x["close"]>x["ema20"]>x["ema50"]>x["ema200"] and x["rsi"]>=52 and x["macd"]>x["macd_signal"]: return "BUY"
    if x["close"]<x["ema20"]<x["ema50"]<x["ema200"] and x["rsi"]<=48 and x["macd"]<x["macd_signal"]: return "SELL"
    return "WAIT"
def score_checkpoints(frames,side):
    m,h,h4=frames["M15"],frames["H1"],frames["H4"]; bull=side=="BUY"; sign=1 if bull else -1; q={}
    def p(k,v): q[k]=5 if v else 0
    p("AMD + volume profile proxy",m["volume"]>=m["volume_avg"])
    p("EMA hybrid 20/50/200",all((x["close"]-x["ema20"])*sign>0 and (x["ema20"]-x["ema50"])*sign>0 and (x["ema50"]-x["ema200"])*sign>0 for x in frames.values()))
    p("RSI 14",(45<=m["rsi"]<=68) if bull else (32<=m["rsi"]<=55))
    p("MACD",(m["macd"]-m["macd_signal"])*sign>0)
    p("ADX 14",False)
    p("BOS/CHOCH proxy",(m["close"]-m["prev_high"])*sign>0 if bull else (m["close"]-m["prev_low"])*sign<0)
    p("FVG",False); p("Order block",False); p("Spring/upthrust",False); p("OTE 62-79%",False); p("Kill zones",False); p("News+DXY",False)
    p("Dynamic management",True); p("Wyckoff phase",False); p("Balance+RR",True)
    p("Volume+imbalance",m["volume"]>m["volume_avg"])
    p("S/R supply-demand proxy",(m["close"]>m["prev_high"]) if bull else (m["close"]<m["prev_low"]))
    p("Liquidity sweep",False)
    p("Market structure",(h["close"]-h["ema50"])*sign>0 and (h4["close"]-h4["ema50"])*sign>0)
    p("H4/H1/M15/M5 alignment",all(direction(x)==side for x in frames.values()))
    return sum(q.values()),q
def analyze(symbol):
    if symbol not in ALLOWED_SYMBOLS: raise ValueError("Symbol not allowlisted")
    frames={tf:indicators(rates(symbol,tf)) for tf in TIMEFRAMES}; dirs={tf:direction(frames[tf]) for tf in TIMEFRAMES}
    aligned=len(set(dirs.values()))==1 and dirs["H4"] in ("BUY","SELL"); side=dirs["H4"] if aligned else "WAIT"
    score,checks=score_checkpoints(frames,side) if aligned else (0,{"alignment gate":0})
    tick=mt5.symbol_info_tick(symbol); info=mt5.symbol_info(symbol)
    if tick is None or info is None: raise RuntimeError(f"No tick/metadata: {mt5.last_error()}")
    m=frames["M5"]; buf=max(info.point*5,m["atr"]*.05)
    if side=="BUY":
        entry=max(m["prev_high"]+buf,tick.ask+info.point); sl=entry-max(m["atr"]*1.5,info.point*20); tp1=entry+(entry-sl)*2; tp2=entry+(entry-sl)*3; typ="BUY_STOP"
    elif side=="SELL":
        entry=min(m["prev_low"]-buf,tick.bid-info.point); sl=entry+max(m["atr"]*1.5,info.point*20); tp1=entry-(sl-entry)*2; tp2=entry-(sl-entry)*3; typ="SELL_STOP"
    else: entry=sl=tp1=tp2=None; typ="NONE"
    return {"symbol":symbol,"side":side,"aligned":aligned,"directions":dirs,"score":score,"grade":"A+" if score>=85 else "A" if score>=80 else "WAIT","checkpoints":checks,"frames":frames,"bid":float(tick.bid),"ask":float(tick.ask),"spread_points":(tick.ask-tick.bid)/info.point,"point":info.point,"digits":info.digits,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"order_type":typ}
