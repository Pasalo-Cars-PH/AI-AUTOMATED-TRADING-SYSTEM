IMPLEMENT THE NEXT ARCHITECTURE PHASE: HARDEN THE AI TRADING BOT INTO A DETERMINISTIC GATED EXECUTION SYSTEM.

OBJECTIVE:
Prevent any AI-generated trade signal from reaching execution unless every mandatory gate passes. DO NOT rewrite working modules unnecessarily. DO NOT introduce mock market data. DO NOT introduce broker proxies. DO NOT bypass existing provider architecture.

IMPLEMENT:
1. DataQualityGate
   - Validate timestamp
   - Validate OHLC
   - Detect stale candles
   - Detect missing candles
   - Detect duplicate candles
   - Detect invalid prices
   - Return PASS / FAIL

2. MultiTimeframeGate
   Required: D1 → H4 → H1 → M30 → M15 → M5
   M1 remains execution refinement only. M1 must NEVER create an independent trade signal.

3. StructureGate
   Validate:
   - HH/HL/LH/LL
   - BOS
   - CHoCH
   - liquidity sweep
   - key H1/H4 levels
   - setup invalidation level

4. SetupGate
   Require:
   - predefined trigger
   - M15 setup/pullback/retest
   - valid price-action confirmation
   - no touch/wick-only entries

5. M5ConfirmationGate
   M5 must be CLOSED. Require valid confirmation beyond the defined setup boundary. Reject the first M5 candle immediately following high-impact news.

6. NewsGate
   If high-impact event is detected: NO TRADE until:
   - initial volatility spike has stabilized
   - coherent M5 structure exists
   - M15 setup becomes valid again
   - spread/execution conditions normalize

7. ConfluenceScoreGate
   Use existing scoring model:
   Trend 15 | Structure 15 | Momentum 10 | PriceAction 10 | Volatility 8 | SupportResistance 10 | MTF 12 | Entry 10 | RiskReward 5 | DataQuality 5
   Minimum ACTIONABLE score = 75.

8. RiskGate
   Default risk = 0.5%. Hard maximum risk = 1%. Maximum total open risk = 3%. Maximum daily loss = 2%. Maximum consecutive losses = 4. Maximum open positions = 6. Maximum correlated risk = 1.5%.

9. StopLossEngine
   SL must use the farther of:
   - structure invalidation
   - 1.5 × ATR14

10. RiskRewardGate
    Minimum R:R = 1:1.5. Reject trade if below minimum.

11. CorrelationGate
    Detect:
    - USD basket exposure
    - crypto basket exposure
    - XAUUSD macro exposure
    Prevent excessive correlated exposure.

12. StrictExecutionLock
    Execution is permitted ONLY if:
    DATA_VALID AND MTF_VALID AND STRUCTURE_VALID AND SETUP_VALID AND M5_CONFIRMED AND NEWS_CLEAR AND SCORE >= 75 AND RR_VALID AND RISK_VALID AND CORRELATION_VALID AND MASTER_ENABLE == true AND KILL_SWITCH == false
    Otherwise: NO_TRADE.

13. Audit Trail
    Every rejected trade must record:
    - timestamp, symbol, candidate direction, score, failed gate, reason, market regime, spread, ATR, relevant timeframe state

14. Telegram
    Telegram must clearly distinguish:
    NO TRADE | WATCH SETUP | ACTIONABLE | PAPER EXECUTED | REJECTED BY RISK | REJECTED BY NEWS | REJECTED BY EXECUTION LOCK

15. PAPER MODE FIRST
    Do NOT enable live execution. Keep:
    MASTER_ENABLE=false
    KILL_SWITCH=true
    TRADING_MODE=PAPER until all tests pass.

ACCEPTANCE CRITERIA:
A trade can never execute by AI recommendation alone. Every execution must have a complete gate decision record. Every rejection must identify the exact failed gate. Run unit tests, integration tests, and negative tests specifically attempting to bypass the StrictExecutionLock.

Return:
1. Files changed
2. Architecture changes
3. Gate decision flow
4. Tests executed
5. Test results
6. Any remaining defects
7. Git commit SHA
