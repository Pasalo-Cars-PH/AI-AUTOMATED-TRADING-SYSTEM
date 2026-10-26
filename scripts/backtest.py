"""Run the repository's actual SMC backtest; it currently sends a Telegram report and returns None."""
import argparse
from app import main as app
def main():
 p=argparse.ArgumentParser();p.add_argument("--symbol",default="XAU/USD");p.add_argument("--pages",type=int,default=10);a=p.parse_args()
 # Exact current signature from app/main.py: run_backtest_smc(chat_id, pages=10, symbol="XAU/USD")
 # It reports ALL, IN-SAMPLE, OUT-OF-SAMPLE via Telegram; it does not return a trade ledger.
 app.run_backtest_smc(chat_id=app.TELEGRAM_CHAT_ID,pages=a.pages,symbol=a.symbol)
 print("NOTE: existing run_backtest_smc sends summary via Telegram and returns None; trade-ledger CSV/metrics cannot be generated without a source change.")
if __name__=="__main__":main()
