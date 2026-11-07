import json,logging,time
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
import MetaTrader5 as mt5
from .config import SETTINGS,ALLOWED_SYMBOLS
from .engine import analyze
from .executor import connect_demo,place_pending,manage_positions
logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
PHT=ZoneInfo("Asia/Manila"); PST=ZoneInfo("America/Los_Angeles")
def stamp():
    n=datetime.now(timezone.utc)
    return f"{n.astimezone(PHT):%Y-%m-%d %H:%M:%S %Z} | {n.astimezone(PST):%Y-%m-%d %H:%M:%S %Z}"
def main():
    a=connect_demo()
    logging.info("CONNECTED DEMO ONLY | login=%s server=%s equity=%s",a.login,a.server,a.equity)
    logging.info("LIVE EXECUTION NOT IMPLEMENTED; existing MASTER_ENABLE/KILL_SWITCH untouched")
    while True:
        try:
            for symbol in ALLOWED_SYMBOLS:
                s=analyze(symbol)
                logging.info("%s | %s | bid=%.3f ask=%.3f | TF=%s | score=%s/100 | %s | entry=%s SL=%s TP1=%s TP2=%s",stamp(),symbol,s["bid"],s["ask"],s["directions"],s["score"],s["order_type"],s["entry"],s["sl"],s["tp1"],s["tp2"])
                logging.info("ORDER RESULT %s: %s",symbol,json.dumps(place_pending(s)))
            manage_positions()
        except KeyboardInterrupt: break
        except Exception: logging.exception("Cycle failed; fail closed")
        time.sleep(SETTINGS.poll_seconds)
    mt5.shutdown()
if __name__=="__main__": main()
