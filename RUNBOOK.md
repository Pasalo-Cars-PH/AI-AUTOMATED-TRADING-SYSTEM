# Vantage MT5 Executor Runbook

## Critical current-code facts
The fetched `app/main.py` SHA is `4d6ffbdcd2c5c377fa7be7937fb9706c9edd6ee3`. It defines `MASTER_LIVE_ENABLE = False`; the existing `run_backtest_smc(chat_id, pages=10, symbol="XAU/USD")` sends a Telegram report and returns no structured trade ledger. It does not contain a broker order path. Therefore the patch below only makes the flag env-configurable; it does not enable or implement live orders. Do not apply it as authorization to trade live.
The executor deliberately fails closed unless `adapter.risk_state_provider` is implemented from MT5 deal history. This is necessary to enforce a real daily-loss cap and consecutive-loss lock; those metrics cannot be inferred from open positions alone.

## Windows setup
**TO RUN BY USER — PowerShell**
```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip pytest python-dotenv MetaTrader5
```
Install/open MT5 from Vantage's official channel, log in manually to VantageMarkets-Demo, select XAUUSD in Market Watch. Copy the files in this branch to your working tree. Copy `.env.windows.example` to `.env`; keep credentials out of Git. Keep `TRADING_MODE=DEMO`, `MASTER_LIVE_ENABLE=false`.

## Tests
**TO RUN BY USER**
```powershell
python -m pytest -q
python scripts\lot_examples.py
```
Expected pytest: all mock tests pass (not run by assistant). PASS is exit code 0. Lot example tick values are illustrative only, not claimed Vantage runtime values. The adapter always reads `trade_tick_size` and `trade_tick_value` at runtime and rejects if either is nonpositive.

## Runtime spec validation
**TO RUN BY USER**
```powershell
python -c "from broker.mt5_adapter import MT5Adapter; a=MT5Adapter(); a.initialize(); print(a.validate_symbol()); a.shutdown()"
```
PASS only if runtime specs match contract 100, min 0.01, step 0.01, max 100, digits 2, stops level 20, USD profit/margin, and positive runtime tick values. If mismatch, stop and confirm account-specific specs.

## Demo order test
**TO RUN BY USER:** only after confirming the terminal/account says VantageMarkets-Demo. Set current valid quote and SL/TP in local `.env`:
```dotenv
TRADING_MODE=DEMO
DEMO_ORDER_CONFIRM=SEND_ONE_DEMO_ORDER
DEMO_SIDE=BUY
DEMO_ENTRY_PRICE=<current quote>
DEMO_STOP_LOSS=<valid SL at least stops level away>
DEMO_TAKE_PROFIT=<valid TP at least stops level away>
RISK_PER_TRADE_PCT=0.25
```
The angle-bracket values above are instructions, not literal values to copy. Then **TO RUN BY USER**:
```powershell
python scripts\demo_order_test.py
```
PASS requires accepted MT5 retcode (normally 10009 DONE), actual position with SL and TP, reconciliation showing it open, close retcode accepted, and final reconciliation showing it closed. A test can lose money even in demo due to spread/slippage; do not retry blindly.

## Telegram commands
Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_CHAT_ID` locally. Start executor with:
**TO RUN BY USER**
```powershell
python -m executor.mt5_executor
```
It starts with kill and pause enabled. Send `/status`, `/kill`, `/pause`; only the exact allowlisted chat ID is processed. `/resume` is denied while kill is active. This implementation intentionally has no Telegram command to clear kill; restart/review and a deliberate local reset is required. Test these commands end-to-end before use.

## Backtest
**TO RUN BY USER**
```powershell
python scripts\backtest.py --symbol "XAU/USD" --pages 10
```
This calls the existing function with its actual signature and sends the report to configured Telegram chat. It does not create a trade ledger because the current function returns None. To export a ledger and compute setups, win rate, average R, expectancy, max drawdown, the underlying app function must be changed to return trade rows from `sim_smc` without changing strategy thresholds. The existing cost is `SYMBOL_COST[symbol]`; `sim_smc` stores cost-adjusted `r` per trade.

## HMAC signal contract
POST raw JSON to `/signal`; headers `X-ATS-Timestamp` (Unix seconds) and `X-ATS-Signature` = lowercase hex HMAC-SHA256(secret, timestamp + "." + exact raw body bytes). Timestamp must be within 60 seconds. Body: `{"signal_id":"unique","side":"BUY","entry":"...","sl":"...","tp":"..."}`. Executor defaults to `127.0.0.1`; use a VPN/TLS reverse proxy and firewall for remote Render-to-Windows delivery. Do not expose port 8765 publicly without TLS and access controls.

## Live checklist — not approved by this pack
- [ ] Implement and test `risk_state_provider` using MT5 deal history, including commissions/swap/fees and broker-day boundary; fail closed on unavailable history.
- [ ] Validate real-account symbol specs independently from demo.
- [ ] Confirm HMAC signatures, stale timestamps, replay rejection, Telegram allowlist, /kill and /pause.
- [ ] Demo order SL/TP confirmed, reconciled, and closed.
- [ ] Review strategy-to-executor price semantics and SL/TP distance.
- [ ] Add actual structured trade ledger and backtest metrics, then test without changing thresholds.
- [ ] Independent review and all tests pass.

First-week settings when separately authorized: `RISK_PER_TRADE_PCT=0.25`, `DAILY_LOSS_CAP_PCT=2`, `MAX_CONSECUTIVE_LOSSES=4`, max one open position, never round up to minimum lot. Reject a trade if 0.01 lot exceeds the risk budget. The executor currently fails closed until the risk-state provider exists. Do not enable live trading based only on this patch.

## Rollback
**TO RUN BY USER**
1. Stop the Windows executor with Ctrl+C.
2. Set `TRADING_MODE=DEMO`, `MASTER_LIVE_ENABLE=false`; leave kill/pause active.
3. Disable Render forwarding or rotate the HMAC secret and restart both sides.
4. Check MT5 manually for open positions; stopping the executor does not close positions.
5. Revert any live-gate commit and redeploy the last known alert-only revision.
