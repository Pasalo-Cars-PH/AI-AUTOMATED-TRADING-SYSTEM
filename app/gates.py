import pandas as pd
import yfinance as yf

# DATA PROVIDER AUDIT MAP
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
    return SYMBOL_MAP.get(symbol, {
        "normalized_symbol": symbol,
        "provider": "yfinance",
        "source_symbol": symbol,
        "asset_class": "UNKNOWN"
    })

# HARD SAFETY GATES
def check_data_quality_gate(df: pd.DataFrame) -> tuple[bool, str]:
    if df is None or df.empty or len(df) < 55:
        return False, "INSUFFICIENT_DATA_LENGTH"
    if df['Close'].isnull().values.any():
        return False, "STALE_OR_INVALID_DATA"
    return True, "PASS"

def check_data_quality(df: pd.DataFrame) -> tuple[bool, str]:
    return check_data_quality_gate(df)

def check_rr_gate(entry: float, sl: float, tp: float, min_rr: float = 1.5) -> tuple[bool, float, str]:
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    if risk == 0:
        return False, 0.0, "INVALID_ZERO_RISK"
    rr_ratio = reward / risk
    if rr_ratio < min_rr:
        return False, round(rr_ratio, 2), f"INSUFFICIENT_RR ({rr_ratio:.2f} < {min_rr})"
    return True, round(rr_ratio, 2), "PASS"

# ANALYTICAL QUALITY SCORING ENGINE
def calculate_calibrated_confluence_score(factors: dict) -> int:
    score = 0
    score += 15 if factors.get("trend_aligned") else 0
    score += 15 if factors.get("structure_strong") else 0
    score += 12 if factors.get("mtf_aligned") else 0
    score += 10 if factors.get("sr_confluence") else 0
    score += 10 if factors.get("price_action_valid") else 0
    score += 10 if factors.get("entry_quality_high") else 0
    score += 10 if factors.get("momentum_confirmed") else 0
    score += 8 if factors.get("volatility_healthy") else 0
    score += 5 if factors.get("rr_score_bonus") else 0
    score += 5 if factors.get("data_quality_bonus") else 0
    return score

# MAIN GATED DECISION ENGINE WITH HARD LIVE SECURITY BOUNDARY
def evaluate_calibrated_candidate(
    symbol: str,
    df: pd.DataFrame,
    m5_action: str,
    entry: float,
    sl: float,
    tp: float,
    m5_candle_closed: bool,
    analytical_factors: dict,
    news_blocked: bool = False,
    risk_exceeded: bool = False,
    master_enable: bool = False,
    kill_switch: bool = True,
    trading_mode: str = "PAPER",
    is_paper_override: bool = False
) -> tuple[str, str, int, dict]:
    """
    Evaluates candidate signal against hard safety gates and weighted scoring.
    SECURITY INVARIANT: paper_override CANNOT unlock LIVE execution under any circumstance.
    """
    # STRICT LIVE GUARDRAIL
    if trading_mode == "LIVE" and is_paper_override:
        return "REJECTED", "SECURITY_VIOLATION_PAPER_OVERRIDE_FORBIDDEN_IN_LIVE_MODE", 0, {
            "execution_lock": "FAIL_SECURITY_OVERRIDE"
        }

    effective_master = master_enable
    effective_kill = kill_switch

    # Paper-only request-scoped authorization
    if is_paper_override and trading_mode == "PAPER":
        effective_master = True
        effective_kill = False

    hard_gates = {
        "data_quality": "PASS",
        "news_gate": "PASS",
        "risk_gate": "PASS",
        "rr_gate": "PASS",
        "m5_closed_gate": "PASS" if m5_candle_closed else "UNCLOSED",
        "execution_lock": "PASS" if (effective_master and not effective_kill) else "LOCKED"
    }

    # 1. EVALUATE HARD SAFETY GATES
    is_data_ok, data_reason = check_data_quality_gate(df)
    if not is_data_ok:
        hard_gates["data_quality"] = "FAIL"
        return "REJECTED", f"DATA_GATE ({data_reason})", 0, hard_gates

    if news_blocked:
        hard_gates["news_gate"] = "FAIL"
        return "REJECTED", "NEWS_EVENT_COOLDOWN", 0, hard_gates

    if risk_exceeded:
        hard_gates["risk_gate"] = "FAIL"
        return "REJECTED", "RISK_LIMIT_EXCEEDED", 0, hard_gates

    is_rr_ok, rr_value, rr_reason = check_rr_gate(entry, sl, tp, min_rr=1.5)
    if not is_rr_ok:
        hard_gates["rr_gate"] = "FAIL"
        return "REJECTED", f"RR_GATE ({rr_reason})", 0, hard_gates

    # 2. EVALUATE CONFLUENCE SCORE
    score = calculate_calibrated_confluence_score(analytical_factors)
    if score < 75:
        return "REJECTED", f"CONFLUENCE_SCORE_BELOW_THRESHOLD ({score}/100 < 75)", score, hard_gates

    # 3. EVALUATE M5 CONFIRMATION
    if not m5_candle_closed:
        return "WATCH", "M5_CANDLE_UNCLOSED", score, hard_gates

    # 4. SAFETY LOCK CHECK FOR EXECUTION
    if not effective_master or effective_kill:
        return "REJECTED", "EXECUTION_LOCK_ACTIVE (MASTER_ENABLE=False / KILL_SWITCH=True)", score, hard_gates

    return "ACTIONABLE_PAPER_PASS", "NONE", score, hard_gates

evaluate_trade_candidate = evaluate_calibrated_candidate
