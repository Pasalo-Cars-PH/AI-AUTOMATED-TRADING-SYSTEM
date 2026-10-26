from decimal import Decimal as D
from types import SimpleNamespace as N
import pytest
from broker.mt5_adapter import MT5Adapter, MT5Rejected, MT5SpecMismatch

class Mock:
 ORDER_FILLING_IOC=1;ORDER_TYPE_BUY=0;ORDER_TYPE_SELL=1;TRADE_ACTION_DEAL=1;ORDER_TIME_GTC=0
 TRADE_RETCODE_DONE=10009;TRADE_RETCODE_PLACED=10008;TRADE_RETCODE_DONE_PARTIAL=10010;POSITION_TYPE_BUY=0
 def __init__(self):self.sent=[]
 def symbol_info(self,s):return N(name=s,visible=True,trade_contract_size=100,volume_min=.01,volume_step=.01,volume_max=100,digits=2,trade_stops_level=20,trade_tick_size=.01,trade_tick_value=1.,point=.01,currency_profit="USD",currency_margin="USD")
 def symbol_info_tick(self,s):return N(ask=2000.,bid=1999.98)
 def order_send(self,r):self.sent.append(r);return N(retcode=10009,comment="done",order=123,deal=456)
 def symbol_select(self,*a):return True
 def last_error(self):return (0,"ok")
 def positions_get(self,**kw):return []
def test_tick_values_read_from_runtime():
 a=MT5Adapter(module=Mock());s=a.validate_symbol();assert s["tick_size"]==".01" or s["tick_size"]=="0.01";assert s["tick_value"] in ("1.0","1.00")
def test_round_down_and_min_lot_risk_rejection():
 a=MT5Adapter(module=Mock());assert a.size(10000,D(".25"),2000,1990)[0]==D(".02")
 with pytest.raises(MT5Rejected):a.size(100,D(".25"),2000,1990)
def test_order_has_sl_tp_ioc_and_idempotency():
 m=Mock();a=MT5Adapter(module=m);x=a.place_order("BUY",D(".01"),D("1999.50"),D("2001"),"same");y=a.place_order("BUY",D(".01"),D("1999.50"),D("2001"),"same")
 assert x==y and len(m.sent)==1 and m.sent[0]["type_filling"]==1 and m.sent[0]["sl"]==1999.5
def test_spec_mismatch_fails_closed():
 m=Mock();old=m.symbol_info
 def bad(s):
  x=old(s);x.trade_contract_size=10;return x
 m.symbol_info=bad
 with pytest.raises(MT5SpecMismatch):MT5Adapter(module=m).validate_symbol()
def test_stops_level():
 a=MT5Adapter(module=Mock())
 with pytest.raises(ValueError):a.place_order("BUY",D(".01"),D("1999.9"),D("2001"),"too-close")
