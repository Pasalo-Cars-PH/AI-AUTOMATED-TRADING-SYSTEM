"""Closed-candle price-structure primitives; chronological OHLC bars, oldest first."""
import math

def validate_bars(bars,minimum=3):
    if not isinstance(bars,(list,tuple)) or len(bars)<minimum: raise ValueError(f"at least {minimum} bars required")
    out=[]
    for i,b in enumerate(bars):
        try: row={k:float(b[k]) for k in ("open","high","low","close")}
        except (KeyError,TypeError,ValueError): raise ValueError(f"invalid OHLC bar at index {i}")
        if not all(math.isfinite(v) for v in row.values()): raise ValueError(f"non-finite OHLC at index {i}")
        if row["low"]>min(row["open"],row["close"]) or row["high"]<max(row["open"],row["close"]) or row["low"]>row["high"]: raise ValueError(f"inconsistent OHLC at index {i}")
        out.append(row)
    return out

def confirmed_swings(bars,left=2,right=2):
    if left<1 or right<1: raise ValueError("left/right must be positive")
    xs=validate_bars(bars,left+right+1); highs=[]; lows=[]
    for i in range(left,len(xs)-right):
        hi,lo=xs[i]["high"],xs[i]["low"]
        if all(hi>xs[j]["high"] for j in range(i-left,i)) and all(hi>=xs[j]["high"] for j in range(i+1,i+right+1)): highs.append({"index":i,"price":hi})
        if all(lo<xs[j]["low"] for j in range(i-left,i)) and all(lo<=xs[j]["low"] for j in range(i+1,i+right+1)): lows.append({"index":i,"price":lo})
    return {"swing_highs":highs,"swing_lows":lows}

def fair_value_gaps(bars):
    xs=validate_bars(bars,3); out=[]
    for i in range(2,len(xs)):
        a,c=xs[i-2],xs[i]
        if c["low"]>a["high"]: out.append({"index":i,"direction":"BUY","low":a["high"],"high":c["low"]})
        elif c["high"]<a["low"]: out.append({"index":i,"direction":"SELL","low":c["high"],"high":a["low"]})
    return out

def liquidity_sweeps(bars,lookback=20):
    if lookback<2: raise ValueError("lookback must be at least 2")
    xs=validate_bars(bars,lookback+1); out=[]
    for i in range(lookback,len(xs)):
        prior=xs[i-lookback:i]; bar=xs[i]; ph=max(x["high"] for x in prior); pl=min(x["low"] for x in prior)
        if bar["high"]>ph and bar["close"]<ph: out.append({"index":i,"direction":"SELL","level":ph,"wick":bar["high"]})
        if bar["low"]<pl and bar["close"]>pl: out.append({"index":i,"direction":"BUY","level":pl,"wick":bar["low"]})
    return out

def structure_break(bars,left=2,right=2):
    xs=validate_bars(bars,left+right+2); swings=confirmed_swings(xs,left,right); last=xs[-1]["close"]
    highs=[p for p in swings["swing_highs"] if p["index"]<len(xs)-right]
    lows=[p for p in swings["swing_lows"] if p["index"]<len(xs)-right]
    if not highs or not lows: return {"status":"UNAVAILABLE","reason":"No confirmed swing high and low"}
    sh,sl=highs[-1]["price"],lows[-1]["price"]
    if last>sh: return {"status":"PASS","direction":"BUY","event":"BOS","level":sh}
    if last<sl: return {"status":"PASS","direction":"SELL","event":"BOS","level":sl}
    return {"status":"FAIL","direction":None,"event":"NO_BREAK","swing_high":sh,"swing_low":sl}
