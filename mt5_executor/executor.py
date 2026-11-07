from __future__ import annotations
import json,math
import MetaTrader5 as mt5
from .config import SETTINGS,ALLOWED_SYMBOLS
def connect_demo():
    SETTINGS.validate()
    if not mt5.initialize(): raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    a=mt5.account_info(); t=mt5.terminal_info()
    if a is None or t is None: raise RuntimeError("MT5 account/terminal info unavailable")
    if int(a.trade_mode)!=int(mt5.ACCOUNT_TRADE_MODE_DEMO): raise RuntimeError("SAFETY BLOCK: account is NOT DEMO")
    if int(a.margin_mode)!=int(mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING): raise RuntimeError("SAFETY BLOCK: Vantage account must be HEDGING mode")
    if not t.connected or not t.trade_allowed or not a.trade_allowed: raise RuntimeError("Terminal/account disconnected or trading disabled")
    return a
def volume_for_risk(symbol,entry,sl,equity):
    info=mt5.symbol_info(symbol)
    loss=mt5.order_calc_profit(mt5.ORDER_TYPE_BUY if entry>sl else mt5.ORDER_TYPE_SELL,symbol,1.0,entry,sl)
    if info is None or loss is None or abs(loss)<=0: raise RuntimeError(f"Cannot calculate risk: {mt5.last_error()}")
    budget=equity*SETTINGS.risk_pct/100; raw=min(SETTINGS.max_forex_lot,budget/abs(loss)); vol=round(math.floor(raw/info.volume_step)*info.volume_step,8)
    if vol<info.volume_min: raise RuntimeError(f"Risk-safe volume below broker minimum {info.volume_min}; skip")
    return vol,abs(loss)*vol,budget
def validate_pending(s):
    t=mt5.symbol_info_tick(s["symbol"]); i=mt5.symbol_info(s["symbol"])
    if t is None or i is None: return False,"No quote/metadata"
    e,sl,tp=s["entry"],s["sl"],s["tp2"]
    if s["order_type"]=="BUY_STOP" and not e>t.ask: return False,"BUY_STOP must be above ask"
    if s["order_type"]=="SELL_STOP" and not e<t.bid: return False,"SELL_STOP must be below bid"
    if s["side"]=="BUY" and not sl<e<tp: return False,"Invalid BUY geometry"
    if s["side"]=="SELL" and not tp<e<sl: return False,"Invalid SELL geometry"
    md=i.trade_stops_level*i.point
    if md and (abs(e-sl)<md or abs(e-tp)<md): return False,"Broker stop distance violation"
    return True,"OK"
def place_pending(s):
    a=mt5.account_info()
    if a is None or int(a.trade_mode)!=int(mt5.ACCOUNT_TRADE_MODE_DEMO) or int(a.margin_mode)!=int(mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING): raise RuntimeError("DEMO + HEDGING account re-check failed")
    if not SETTINGS.allow_orders: return {"status":"DRY_RUN_LOCKED","reason":"MT5_ALLOW_ORDERS=false"}
    if s["symbol"] not in ALLOWED_SYMBOLS or s["side"] not in ("BUY","SELL") or not s["aligned"] or s["score"]<80: return {"status":"REJECTED","reason":"Allowlist/alignment/score gate"}
    ok,why=validate_pending(s)
    if not ok: return {"status":"REJECTED","reason":why}
    vol,risk,budget=volume_for_risk(s["symbol"],s["entry"],s["sl"],a.equity)
    i=mt5.symbol_info(s["symbol"]); typ=mt5.ORDER_TYPE_BUY_STOP if s["order_type"]=="BUY_STOP" else mt5.ORDER_TYPE_SELL_STOP
    req={"action":mt5.TRADE_ACTION_PENDING,"symbol":s["symbol"],"volume":vol,"type":typ,"price":round(s["entry"],s["digits"]),"sl":round(s["sl"],s["digits"]),"tp":round(s["tp2"],s["digits"]),"deviation":SETTINGS.deviation_points,"magic":SETTINGS.magic,"comment":f"TITAN_DEMO_{s['score']}","type_time":mt5.ORDER_TIME_GTC,"type_filling":mt5.ORDER_FILLING_RETURN}
    chk=mt5.order_check(req)
    if chk is None or chk.retcode not in (0,mt5.TRADE_RETCODE_DONE): return {"status":"ORDER_CHECK_FAILED","retcode":getattr(chk,"retcode",None),"comment":getattr(chk,"comment",str(mt5.last_error()))}
    res=mt5.order_send(req)
    if res is None or res.retcode not in (mt5.TRADE_RETCODE_PLACED,mt5.TRADE_RETCODE_DONE): return {"status":"SEND_FAILED","retcode":getattr(res,"retcode",None),"comment":getattr(res,"comment",str(mt5.last_error()))}
    return {"status":"PLACED_DEMO","ticket":res.order,"volume":vol,"estimated_risk":round(risk,2),"risk_budget":round(budget,2),"entry":req["price"],"sl":req["sl"],"tp":req["tp"]}
def manage_positions():
    a=mt5.account_info()
    if a is None or int(a.trade_mode)!=int(mt5.ACCOUNT_TRADE_MODE_DEMO) or int(a.margin_mode)!=int(mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING): raise RuntimeError("Position manager requires DEMO HEDGING account")
    positions=mt5.positions_get()
    if positions is None: return
    try: state=json.load(open(SETTINGS.state_file,encoding="utf-8"))
    except Exception: state={}
    dirty=False
    for p in positions:
        if p.magic!=SETTINGS.magic or p.symbol not in ALLOWED_SYMBOLS: continue
        info=mt5.symbol_info(p.symbol); tick=mt5.symbol_info_tick(p.symbol)
        if info is None or tick is None: continue
        pip=info.point*10 if info.digits in (3,5) else info.point
        cur=tick.bid if p.type==mt5.POSITION_TYPE_BUY else tick.ask
        pp=(cur-p.price_open)/pip if p.type==mt5.POSITION_TYPE_BUY else (p.price_open-cur)/pip
        key=str(p.ticket); st=state.setdefault(key,{"tp1_done":False,"initial_risk":abs(p.price_open-p.sl) if p.sl else pip*20})
        if pp>=20:
            be=round(p.price_open,info.digits); better=(p.sl==0 or be>p.sl) if p.type==mt5.POSITION_TYPE_BUY else (p.sl==0 or be<p.sl)
            if better:
                r=mt5.order_send({"action":mt5.TRADE_ACTION_SLTP,"position":p.ticket,"symbol":p.symbol,"sl":be,"tp":p.tp,"magic":SETTINGS.magic})
                if r and r.retcode==mt5.TRADE_RETCODE_DONE: dirty=True
        if not st["tp1_done"] and p.tp:
            # TP1 at 2R; broker TP is 3R, so TP1 is two-thirds of entry-to-TP distance.
            tp1=p.price_open+(p.tp-p.price_open)*(2/3)
            hit=cur>=tp1 if p.type==mt5.POSITION_TYPE_BUY else cur<=tp1
            if hit:
                cv=math.floor((p.volume/2)/info.volume_step)*info.volume_step
                if cv>=info.volume_min and p.volume-cv>=info.volume_min:
                    typ=mt5.ORDER_TYPE_SELL if p.type==mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY; px=tick.bid if p.type==mt5.POSITION_TYPE_BUY else tick.ask
                    r=mt5.order_send({"action":mt5.TRADE_ACTION_DEAL,"position":p.ticket,"symbol":p.symbol,"volume":cv,"type":typ,"price":px,"deviation":SETTINGS.deviation_points,"magic":SETTINGS.magic,"comment":"TITAN_DEMO_TP1_50"})
                    if r and r.retcode==mt5.TRADE_RETCODE_DONE: st["tp1_done"]=True; dirty=True
        if st["tp1_done"]:
            # Trail by original risk distance; never loosen the stop.
            dist=float(st.get("initial_risk",pip*20)); trail=round(cur-dist if p.type==mt5.POSITION_TYPE_BUY else cur+dist,info.digits)
            better=(trail>p.sl) if p.type==mt5.POSITION_TYPE_BUY else (p.sl==0 or trail<p.sl)
            if better and ((p.type==mt5.POSITION_TYPE_BUY and trail<cur) or (p.type==mt5.POSITION_TYPE_SELL and trail>cur)):
                r=mt5.order_send({"action":mt5.TRADE_ACTION_SLTP,"position":p.ticket,"symbol":p.symbol,"sl":trail,"tp":p.tp,"magic":SETTINGS.magic})
                if r and r.retcode==mt5.TRADE_RETCODE_DONE: dirty=True
    if dirty or state:
        with open(SETTINGS.state_file,"w",encoding="utf-8") as f: json.dump(state,f,indent=2)
