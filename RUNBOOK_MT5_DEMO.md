# TITAN PRO Vantage MT5 DEMO Executor
## Scope and safety
- Additive Windows-side executor. It does not replace V9.0 paper engine, Render service, Twelve Data settings, or existing ledger.
- GBPJPY and USDJPY only. No crypto symbols or meme coins.
- Requires official MetaTrader5 Python package and running MT5 desktop terminal on Windows.
- Connected account must report ACCOUNT_TRADE_MODE_DEMO. Checked at startup, before order placement, and before position management.
- Live execution is not implemented. MT5_MODE other than DEMO is rejected. Do not change MASTER_ENABLE, KILL_SWITCH, LIVE_ENABLED, or TRADING_MODE in Render.
- Default dry-run is MT5_ALLOW_ORDERS=false.
## Install — TO RUN BY USER
1. Install Vantage MT5 for Windows and log in to a DEMO account. Confirm hedging mode and enable Algo Trading.
2. Pull this branch on Windows and open PowerShell at repository root.
3. Run:
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements_mt5.txt
4. Copy mt5_executor/.env.mt5.example to .env or set variables in PowerShell. Keep MT5_ALLOW_ORDERS=false initially.
5. Show GBPJPY and USDJPY in Market Watch. Exact symbol names are required; suffixes are not guessed.
6. Run tests: python -m pytest -q tests/test_mt5_rules.py
7. Dry-run: python -m mt5_executor.run. Confirm DEMO server, both symbols, H4/H1/M15/M5 directions, score, and PHT/PST timestamps. Stop with Ctrl+C.
8. Only after demo validation, set MT5_ALLOW_ORDERS=true locally to permit DEMO pending orders. Never log in to a live account.
## Rules
- Closed candles only; all four timeframes must agree BUY or SELL.
- Each of 20 checkpoints scores 0 or 5. Unimplemented concepts (ADX, FVG, OB, Wyckoff event, OTE, kill-zone validation, news/DXY, liquidity sweep) score zero; no assumed passes. Initial build can therefore frequently WAIT.
- Only BUY_STOP above ask or SELL_STOP below bid are generated, beyond previous 20 closed M5 candles. No market or limit orders.
- SL uses 1.5 x M5 ATR; TP2 is 3R. TP1 is 2R. Position manager attempts 50% close at TP1 and moves SL to BE at +20 pips, then trails.
- Volume uses MT5 order_calc_profit, account equity and 1% risk cap, with 0.02 maximum. If broker minimum volume exceeds risk budget, skip.
## Limitations requiring demo verification
- Exact symbol naming, tick values, stop distances, filling modes, and volume constraints vary by broker.
- TP1 partial-close and trailing logic are first-pass demo implementation; verify against Vantage hedging account and broker minimum volume before reliance.
- Half-close is skipped if volume step/minimum prevents a valid remaining position.
- Checkpoint concepts without a verified implementation/feed fail closed. This is not a claim that all 20 strategies are fully implemented.
- State file is local. Do not run multiple executor instances with same magic number.
## Acceptance checklist
- [ ] Real account refused.
- [ ] Disconnected terminal or disabled trading refused.
- [ ] Dry-run creates no orders.
- [ ] Score below 80 and non-unanimous TF direction create no orders.
- [ ] BUY_STOP above ask; SELL_STOP below bid.
- [ ] order_check passes before order_send.
- [ ] Risk <=1% and volume <=0.02.
- [ ] BE, 50% TP1 and trailing verified on demo.
- [ ] Existing Render safety flags unchanged.
## Stop
Press Ctrl+C. If unresponsive, disable Algo Trading and close Python. Cancel TITAN demo pending orders manually in MT5. This local executor has no remote kill switch.
