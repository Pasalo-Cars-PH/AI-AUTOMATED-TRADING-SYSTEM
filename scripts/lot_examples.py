from decimal import Decimal as D, ROUND_DOWN
def calc(equity,risk_pct,stop_distance,tick_size,tick_value):
 budget=D(str(equity))*D(str(risk_pct))/D(100);perlot=D(str(stop_distance))/D(str(tick_size))*D(str(tick_value));raw=budget/perlot
 vol=(raw/D(".01")).to_integral_value(rounding=ROUND_DOWN)*D(".01")
 return budget,perlot,raw,vol,vol>=D(".01")
if __name__=="__main__":
 # tick_size=.01 and tick_value=1.00 are illustrative only; runtime MT5 values are authoritative.
 for name,equity,stop in [("case_1",10000,10),("case_2",1000,10),("reject_min_lot",100,10)]:
  b,p,r,v,ok=calc(equity,.25,stop,.01,1)
  print(f"{name}: budget={b} per_lot_stop_risk={p} raw={r} rounded_down={v} status={'PASS' if ok else 'REJECT_MIN_LOT_EXCEEDS_RISK_BUDGET'}")
