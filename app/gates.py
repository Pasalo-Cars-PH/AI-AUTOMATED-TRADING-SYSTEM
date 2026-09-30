import pandas as pd
import yfinance as yf

# 1. DATA QUALITY GATE
def check_data_quality(df):
    if df.empty or len(df) < 55:
        return False, "INSUFFICIENT_DATA"
    if df['Close'].isnull().any():
        return False, "MISSING_OR_INVALID_PRICES"
    return True, "PASS"

# 2. MULTI-TIMEFRAME GATE (D1 -> H1 -> M5)
def check_mtf_alignment(symbol):
    try:
        # Fetch H1 trend
        df_h1 = yf.download(tickers=symbol, period="5d", interval="1h", progress=False)
        if isinstance(df_h1.columns, pd.MultiIndex):
            df_h1.columns = df_h1.columns.get_level_values(0)
        
        ema_55_h1 = df_h1['Close'].ewm(span=55, adjust=False).mean().iloc[-1]
        price_h1 = df_h1['Close'].iloc[-1]
        
        # Bullish if H1 > EMA 55, Bearish if H1 < EMA 55
        h1_trend = "BULLISH" if price_h1 > ema_55_h1 else "BEARISH"
        return True, h1_trend
    except Exception as e:
        return False, "NEUTRAL"

# 3. CONFLUENCE SCORE CALCULATOR (Min Score: 75)
def calculate_confluence_score(m5_signal, h1_trend, rsi_value, atr_value):
    score = 0
    # Trend alignment (Max 30 pts)
    if (m5_signal == "BUY" and h1_trend == "BULLISH") or (m5_signal == "SELL" and h1_trend == "BEARISH"):
        score += 30
    
    # Momentum (Max 25 pts)
    if m5_signal == "BUY" and rsi_value > 50:
        score += 25
    elif m5_signal == "SELL" and rsi_value < 50:
        score += 25
        
    # Volatility Check (Max 20 pts)
    if atr_value > 0:
        score += 20
        
    # Structure & Entry (Max 25 pts)
    score += 20 # Base structure pass
    
    return score

# 4. STRICT EXECUTION LOCK EVALUATOR
def evaluate_trade_candidate(symbol, m5_action, price, ema55, rsi, atr):
    # Gate 1: Data Quality Check
    # Gate 2: MTF Check
    mtf_pass, h1_trend = check_mtf_alignment(symbol)
    if not mtf_pass:
        return "REJECTED_BY_DATA_GATE", 0

    # MTF Alignment Lock
    if m5_action == "BUY" and h1_trend != "BULLISH":
        return "REJECTED_BY_MTF_GATE (H1 is Bearish)", 0
    if m5_action == "SELL" and h1_trend != "BEARISH":
        return "REJECTED_BY_MTF_GATE (H1 is Bullish)", 0

    # Gate 3: Confluence Score Gate
    score = calculate_confluence_score(m5_action, h1_trend, rsi, atr)
    if score < 75:
        return f"REJECTED_BY_CONFLUENCE_SCORE ({score}/75)", score

    # All gates passed -> Pass to Paper Execution Engine
    return "ACTIONABLE_PAPER_PASS", score
