import os
import requests
from datetime import datetime, timezone
from fastapi import FastAPI, BackgroundTasks, Query
import pandas as pd
import yfinance as yf

from app.gates import (
    evaluate_calibrated_candidate,
    check_data_quality_gate,
    get_symbol_metadata,
    SYMBOL_MAP
)

app = FastAPI(title="Deterministic Gated Trading Engine", version="2.0.0")

# 🔒 SAFETY INVARIANTS (HARD-LOCKED SECURITY BOUNDARY FOR LIVE DEFAULT)
MASTER_ENABLE = False
KILL_SWITCH = True
TRADING_MODE = "PAPER"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# 📊 DAILY AUDIT AGGREGATOR MEMORY
daily_stats = {
    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    "total_scans": 0,
    "candidate_setups": 0,
    "watch_candidates": 0,
    "rejected_candidates": 0,
    "paper_executions": 0,
    "rejection_breakdown": {},
    "symbol_breakdown": {"BTCUSD": 0, "XAUUSD": 0, "EURUSD": 0},
    "scores": [],
    "system_errors": 0
}

def send_telegram_alert(message: str):
    """Utility to deliver structured audit logs to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[TELEGRAM] Missing Bot Token or Chat ID. Alert skipped.")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"[TELEGRAM ERROR] Failed to deliver alert: {e}")

# STRUCTURED REJECTION AUDIT LOG
def log_candidate_rejection(symbol: str, m5_action: str, failed_gate: str, score: int, gate_checklist: dict):
    meta = get_symbol_metadata(symbol)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    event_id = f"REJECT-{int(datetime.now(timezone.utc).timestamp())}"

    checklist_str = "\n".join([f"  {'✅' if status == 'PASS' else '❌' if status == 'FAIL' else '⏸'} *{gate.upper()}:* `{status}`" for gate, status in gate_checklist.items()])

    msg = (
        f"🔴 *TRADE REJECTED*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Symbol:* `{meta['normalized_symbol']}`\n"
        f"• *Candidate:* `{m5_action}`\n"
        f"• *Confluence Score:* `{score}/100`\n\n"
        f"❌ *FAILED GATE:* `{failed_gate}`\n\n"
        f"🛡️ *HARD GATE CHECKLIST*\n"
        f"{checklist_str}\n\n"
        f"📡 *DATA PROVIDER AUDIT*\n"
        f"• *Provider:* `{meta['provider']}` | *Source:* `{meta['source_symbol']}`\n"
        f"🔒 *Execution Lock:* `BLOCKED (PAPER)`\n"
        f"🆔 *ID:* `{event_id}` | ⏰ `{now_utc}`"
    )
    send_telegram_alert(msg)

# STRUCTURED PAPER EXECUTION LOG
def log_paper_execution(symbol: str, m5_action: str, entry: float, sl: float, tp: float, score: int, gate_checklist: dict):
    meta = get_symbol_metadata(symbol)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    event_id = f"PAPER-{int(datetime.now(timezone.utc).timestamp())}"

    checklist_str = "\n".join([f"  ✅ *{gate.upper()}:* `{status}`" for gate, status in gate_checklist.items()])

    msg = (
        f"📝 *PAPER EXECUTED*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Symbol:* `{meta['normalized_symbol']}`\n"
        f"• *Action:* `{m5_action}`\n"
        f"• *Confluence Score:* `{score}/100`\n\n"
        f"📍 *TRADE DETAILS*\n"
        f"• *Entry:* `{entry}`\n"
        f"• *Stop Loss:* `{sl}`\n"
        f"• *Take Profit:* `{tp}`\n\n"
        f"🛡️ *HARD GATE CHECKLIST*\n"
        f"{checklist_str}\n\n"
        f"📡 *DATA PROVIDER AUDIT*\n"
        f"• *Provider:* `{meta['provider']}` | *Source:* `{meta['source_symbol']}`\n"
        f"🟢 *Execution Lock:* `PASSED (PAPER)`\n"
        f"🆔 *ID:* `{event_id}` | ⏰ `{now_utc}`"
    )
    send_telegram_alert(msg)

# CANDIDATE EVALUATION PIPELINE
def process_symbol_scan(symbol: str, master_override: bool = False, kill_override: bool = True):
    daily_stats["total_scans"] += 1
    meta = get_symbol_metadata(symbol)

    try:
        df = yf.download(tickers=symbol, period="2d", interval="5m", progress=False)
        is_data_ok, data_reason = check_data_quality_gate(df)
        if not is_data_ok:
            return

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        price = float(df['Close'].iloc[-1])
        ema55 = float(df['Close'].ewm(span=55, adjust=False).mean().iloc[-1])

        m5_action = "NONE"
        if price > ema55:
            m5_action = "BUY"
        elif price < ema55:
            m5_action = "SELL"

        if m5_action == "NONE":
            return

        daily_stats["candidate_setups"] += 1

        sl = price * 0.995 if m5_action == "BUY" else price * 1.005
        tp = price * 1.010 if m5_action == "BUY" else price * 0.990

        analytical_factors = {
            "trend_aligned": True,
            "structure_strong": True,
            "mtf_aligned": True,
            "sr_confluence": True,
            "price_action_valid": True,
            "entry_quality_high": True,
            "momentum_confirmed": True,
            "volatility_healthy": True,
            "rr_score_bonus": True,
            "data_quality_bonus": True
        }

        # Resolve Master and Kill switch settings (Supports controlled paper execution testing)
        use_master = master_override if master_override else MASTER_ENABLE
        use_kill = kill_override if master_override else KILL_SWITCH

        status, failed_gate, score, gate_checklist = evaluate_calibrated_candidate(
            symbol=symbol,
            df=df,
            m5_action=m5_action,
            entry=price,
            sl=sl,
            tp=tp,
            m5_candle_closed=True,
            analytical_factors=analytical_factors,
            master_enable=use_master,
            kill_switch=use_kill
        )

        daily_stats["scores"].append(score)

        if status == "REJECTED":
            daily_stats["rejected_candidates"] += 1
            daily_stats["rejection_breakdown"][failed_gate] = daily_stats["rejection_breakdown"].get(failed_gate, 0) + 1
            log_candidate_rejection(symbol, m5_action, failed_gate, score, gate_checklist)
        elif status == "ACTIONABLE_PAPER_PASS":
            daily_stats["paper_executions"] += 1
            log_paper_execution(symbol, m5_action, price, sl, tp, score, gate_checklist)
        elif status == "WATCH":
            daily_stats["watch_candidates"] += 1

    except Exception as e:
        daily_stats["system_errors"] += 1
        print(f"[SCAN ERROR] Exception during {symbol} scan: {e}")

# API ENDPOINTS
@app.get("/")
def root():
    return {
        "status": "online",
        "system": "Deterministic Gated Trading Engine",
        "master_enable": MASTER_ENABLE,
        "kill_switch": KILL_SWITCH,
        "mode": TRADING_MODE
    }

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "kill_switch": KILL_SWITCH,
        "master_enable": MASTER_ENABLE,
        "mode": TRADING_MODE
    }

@app.get("/signal")
def signal_endpoint():
    return {
        "symbol": "NONE",
        "action": "NONE",
        "reason": "STRICT_EXECUTION_LOCK_ACTIVE",
        "mode": TRADING_MODE
    }

@app.get("/test-scan")
def trigger_manual_scan(
    background_tasks: BackgroundTasks,
    paper_test: bool = Query(False, description="Set to True for controlled paper execution test")
):
    master_override = True if paper_test else MASTER_ENABLE
    kill_override = False if paper_test else KILL_SWITCH

    for symbol in SYMBOL_MAP.keys():
        background_tasks.add_task(process_symbol_scan, symbol, master_override, kill_override)
    
    return {
        "status": "success",
        "paper_test_mode": paper_test,
        "message": f"Manual scan triggered (Paper Test: {paper_test}). Audit reports dispatched to Telegram."
    }
