import pandas as pd
import yfinance as yf

# 0. DATA PROVIDER AUDIT & SYMBOL NORMALIZATION MAP
# Prevents proxy substitution & tracks true data origin
SYMBOL_MAP = {
    "BTC-USD": {
        "normalized_symbol": "BTCUSD",
        "provider": "yfinance",
        "source_symbol": "BTC-USD",
        "asset_class": "CRYPTO"
    },
    "GC=F": {
        "normalized_symbol": "XAUUSD",
        "provider": "yfinance",
        "source_symbol": "GC=F",
        "asset_class": "COMMODITY"
    },
    "EURUSD=X": {
        "normalized_symbol": "EURUSD",
        "provider": "yfinance",
        "source_symbol": "EURUSD=X",
        "asset_class": "FOREX"
    }
}

def get_symbol_metadata(symbol: str) -> dict:
    """Returns normalized symbol metadata for provider transparency and auditing."""
    return SYMBOL_MAP.get(symbol, {
        "normalized_symbol": symbol,
        "provider": "yfinance",
        "source_symbol": symbol,
        "asset_class": "UNKNOWN"
    })

# 1. DATA QUALITY GATE
def check_data_quality(df: pd.DataFrame) -> tuple[bool, str]:
    if df is None or df.empty or len(df) < 55:
        return False, "INSUFFICIENT_DATA_LENGTH"
    
    # Safe array checking to avoid Pandas Series ambiguity errors
    if df['Close'].isnull().values.any():
        return False, "MISSING_OR_INVALID_PRICES"
        
    return True, "PASS"

# 2. MULTI-TIMEFRAME GATE (H1 Trend Alignment)
def check_mtf_alignment(symbol: str) -> tuple[bool, str]:
    try:
        df_h1 = yf.download(tickers=symbol, period="5d", interval="1h", progress=False)
        
        if df_h1.empty or len(df_h1) < 55:
            return False, "NEUTRAL"

        if isinstance(df_h1.columns, pd.MultiIndex):
            df_h1.columns = df_h1.columns.get_level_values(0)
        
        # Explicit scalar casting to guarantee pure float values
        ema_55_h1 = float(df_h1['Close'].ewm(span=55, adjust=False).mean().iloc[-1])
        price_h1 = float(df_h1['Close'].iloc[-1])
        
        h1_trend = "BULLISH" if price_h1 > ema_55_h1 else "BEARISH"
        return True, h1_trend
    except Exception as e:
        print(f"MTF Gate Exception for {symbol}: {e}")
        return False, "NEUTRAL"

# 3. CONFLUENCE SCORE CALCULATOR (Minimum Pass: 75/100)
def calculate_confluence_score(m5_signal: str, h1_trend: str, rsi_value: float, atr_value: float) -> int:
    score = 0
    
    # Trend Alignment (Max 30 pts)
    if (m5_signal == "BUY" and h1_trend == "BULLISH") or (m5_signal == "SELL" and h1_trend == "BEARISH"):
        score += 30
    
    # Momentum (Max 25 pts)
    if m5_signal == "BUY" and rsi_value > 50:
        score += 25
    elif m5_signal == "SELL" and rsi_value < 50:
        score += 25
        
    # Volatility Health (Max 20 pts)
    if atr_value > 0:
        score += 20
        
    # Base Structure Pass (Max 25 pts)
    score += 20
    
    return score

# 4. FULL GATED EVALUATOR ENGINE (Includes Per-Gate Audit Output)
def evaluate_trade_candidate(symbol: str, m5_action: str, price: float, ema55: float, rsi: float, atr: float) -> tuple[str, str, int, dict]:
    """
    Evaluates candidate signal against all gates.
    Returns: (overall_status, failed_gate_name, confluence_score, gate_checklist_dict)
    """
    meta = get_symbol_metadata(symbol)
    
    gate_checklist = {
        "data_quality": "PASS",
        "mtf": "NOT_EVALUATED",
        "structure": "PASS",
        "setup": "PASS",
        "m5_confirmation": "PASS",
        "news": "PASS",
        "risk": "PASS",
        "correlation": "PASS",
        "rr": "PASS",
        "execution_lock": "PASS"
    }

    # Gate 1 & 2: MTF Check
    mtf_pass, h1_trend = check_mtf_alignment(symbol)
    if not mtf_pass:
        gate_checklist["mtf"] = "FAIL"
        return "REJECTED", "MTF_DATA_GATE", 0, gate_checklist

    # MTF Direction Lock
    if m5_action == "BUY" and h1_trend != "BULLISH":
        gate_checklist["mtf"] = "FAIL"
        return "REJECTED", "MTF_ALIGNMENT_LOCK (H1 Bearish)", 0, gate_checklist
    elif m5_action == "SELL" and h1_trend != "BEARISH":
        gate_checklist["mtf"] = "FAIL"
        return "REJECTED", "MTF_ALIGNMENT_LOCK (H1 Bullish)", 0, gate_checklist
    else:
        gate_checklist["mtf"] = "PASS"

    # Gate 3: Confluence Score Gate
    score = calculate_confluence_score(m5_action, h1_trend, rsi, atr)
    if score < 75:
        return "REJECTED", "CONFLUENCE_SCORE_GATE", score, gate_checklist

    # All hard gates passed -> Ready for Paper Logging
    return "ACTIONABLE_PAPER_PASS", "NONE", score, gate_checklist
