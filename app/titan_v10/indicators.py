"""Deterministic OHLCV indicators for the isolated TITAN V10 candidate."""
from __future__ import annotations
import math

def _series(values, name):
    out=[float(x) for x in values]
    if not out or any(not math.isfinite(x) for x in out): raise ValueError(f"{name} must be non-empty finite numbers")
    return out

def ema(values, period):
    xs=_series(values,"values")
    if period<1 or len(xs)<period: raise ValueError("insufficient values for EMA")
    alpha=2.0/(period+1.0); value=sum(xs[:period])/period
    for x in xs[period:]: value=alpha*x+(1-alpha)*value
    return value

def rsi(values, period=14):
    xs=_series(values,"values")
    if period<1 or len(xs)<=period: raise ValueError("insufficient values for RSI")
    changes=[xs[i]-xs[i-1] for i in range(1,len(xs))]
    gains=[max(x,0.0) for x in changes]; losses=[max(-x,0.0) for x in changes]
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(gains)):
        ag=(ag*(period-1)+gains[i])/period; al=(al*(period-1)+losses[i])/period
    if al==0: return 100.0 if ag>0 else 50.0
    return 100.0-100.0/(1.0+ag/al)

def macd(values, fast=12, slow=26, signal=9):
    xs=_series(values,"values")
    if not (0<fast<slow and signal>0) or len(xs)<slow+signal: raise ValueError("insufficient values or invalid MACD periods")
    def path(data,p):
        out=[None]*(p-1); v=sum(data[:p])/p; out.append(v); k=2.0/(p+1)
        for x in data[p:]: v=k*x+(1-k)*v; out.append(v)
        return out
    f,s=path(xs,fast),path(xs,slow); line=[a-b for a,b in zip(f,s) if a is not None and b is not None]
    sig=ema(line,signal)
    return {"macd":line[-1],"signal":sig,"histogram":line[-1]-sig}

def true_ranges(highs,lows,closes):
    h,l,c=_series(highs,"highs"),_series(lows,"lows"),_series(closes,"closes")
    if not (len(h)==len(l)==len(c)) or len(c)<2: raise ValueError("OHLC lengths must match and contain at least two bars")
    if any(lo>hi for lo,hi in zip(l,h)): raise ValueError("low cannot exceed high")
    return [max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])) for i in range(1,len(c))]

def adx(highs,lows,closes,period=14):
    h,l,c=_series(highs,"highs"),_series(lows,"lows"),_series(closes,"closes")
    if not (len(h)==len(l)==len(c)) or period<2 or len(c)<2*period+1: raise ValueError("insufficient or mismatched OHLC for ADX")
    pdm=[]; mdm=[]; tr=[]
    for i in range(1,len(c)):
        up=h[i]-h[i-1]; down=l[i-1]-l[i]
        pdm.append(up if up>down and up>0 else 0.0); mdm.append(down if down>up and down>0 else 0.0)
        tr.append(max(h[i]-l[i],abs(h[i]-c[i-1]),abs(l[i]-c[i-1])))
    def smooth(vs):
        v=sum(vs[:period]); out=[None]*(period-1)+[v]
        for x in vs[period:]: v=v-v/period+x; out.append(v)
        return out
    ats,ps,ms=smooth(tr),smooth(pdm),smooth(mdm); dx=[]; pdi=mdi=0.0
    for a,p,m in zip(ats,ps,ms):
        if a is None: continue
        pdi=100*p/a if a else 0.0; mdi=100*m/a if a else 0.0; den=pdi+mdi
        dx.append(100*abs(pdi-mdi)/den if den else 0.0)
    if len(dx)<period: raise ValueError("insufficient ADX seed")
    value=sum(dx[:period])/period
    for x in dx[period:]: value=(value*(period-1)+x)/period
    return {"adx":value,"plus_di":pdi,"minus_di":mdi}
