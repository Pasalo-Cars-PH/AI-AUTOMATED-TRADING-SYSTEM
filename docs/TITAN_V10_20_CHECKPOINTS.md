# TITAN V10 — 20 Checkpoint Framework (isolated candidate)

## Safety and scope
- This package is isolated under `app/titan_v10`; it is not imported by V9.0 runtime.
- No broker, order, Telegram, Render, or external-data side effects.
- It returns `PAPER_CANDIDATE` at most. It cannot authorize or submit an order.
- Missing, stale, invalid, or unclosed-candle features never count as PASS.
- Checkpoint 13 (Dynamic Management) is explicitly post-entry and excluded from entry scoring.
- Hard gates: Kill Zones, News + DXY, Balance + RR, and Timeframe Alignment.
- Directional features must identify BUY or SELL; opposing direction becomes FAIL.
- Scores are normalized against the full configured entry weight, not just available features.

## Checkpoint inputs
The evaluator accepts a mapping keyed by feature name. Each feature is a mapping:
```python
{"status": "PASS" | "FAIL" | "UNAVAILABLE", "reason": "...", "direction": "BUY" | "SELL"}
```
Directional features require direction. `balance_rr` additionally requires numeric `rr`.
No calculation is fabricated in this module: provider/indicator adapters must supply computed,
timestamp-aligned and closed-candle-validated features. A status PASS is a claim by that adapter,
not independent proof of the underlying calculation.

## Registry and weights
| # | Checkpoint | Weight | Gate |
|---:|---|---:|---|
| 1 | AMD + Volume Profile | 5 | |
| 2 | EMA Hybrid | 6 | |
| 3 | RSI | 3 | |
| 4 | MACD | 3 | |
| 5 | ADX | 3 | |
| 6 | BOS / CHOCH | 6 | |
| 7 | FVG | 5 | |
| 8 | Order Block | 5 | |
| 9 | Spring / Upthrust | 4 | |
| 10 | OTE | 4 | |
| 11 | Kill Zones | 4 | Hard |
| 12 | News + DXY | 5 | Hard |
| 13 | Dynamic Management | 0 | Post-entry |
| 14 | Wyckoff Phase | 4 | |
| 15 | Balance + RR | 5 | Hard |
| 16 | Volume + Imbalance | 5 | |
| 17 | S/R + Supply / Demand | 5 | |
| 18 | Liquidity Sweep | 7 | |
| 19 | Market Structure | 7 | |
| 20 | Timeframe Alignment | 9 | Hard |

Total entry weight: 90. The 75-point threshold is a candidate configuration, not a proven optimum.
Do not optimize weights or threshold against the same validation dataset.

## Run tests
```bash
python -m unittest tests.test_titan_v10_checkpoints -v
```

## Not yet implemented
Actual OHLCV indicator calculations, market-data adapters, news calendar/DXY provider,
Volume Profile/AMD classifier, Wyckoff classification, OTE/order-block/FVG detection,
live scanner integration, Telegram formatting, and historical replay are separate tasks.
Until these are implemented and independently tested, this is a decision-framework foundation,
not a complete 20-strategy trading system.
