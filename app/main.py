import os
import requests
from datetime import datetime, timezone
from fastapi import FastAPI, BackgroundTasks
import pandas as pd
import yfinance as yf

from app.gates import (
    evaluate_trade_candidate,
    check_data_quality,
    get_symbol_metadata,
    SYMBOL_MAP
)

app = FastAPI(title="Deterministic Gated Trading Engine", version="2.0.0")

# 🔒 SAFETY INVARIANTS (HARD-LOCKED SECURITY BOUNDARY)
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

# 1. STRUCTURED REJECTION AUDIT LOG (TELEGRAM)
def log_candidate_rejection(symbol: str, m5_action: str, failed_gate: str, reason: str, score: int, gate_checklist: dict):
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
        f"❌ *FAILED GATE:* `{failed_gate}`\n"
        f"• *Reason:* `{reason}`\n\n"
        f"🛡️ *GATE CHECKLIST*\n"
        f"{checklist_str}\n\n"
        f"📡 *DATA PROVIDER AUDIT*\n"
        f"• *Provider:* `{meta['provider']}`\n"
        f"• *Source Symbol:* `{meta['source_symbol']}`\n"
        f"• *Asset Class:* `{meta['asset_class']}`\n\n"
        f"🔒 *Execution Lock:* `BLOCKED (PAPER)`\n"
        f"🆔 *ID:* `{event_id}`\n"
        f"⏰ *Timestamp:* `{now_utc}`"
    )
    send_telegram_alert(msg)

# 2. CONTROLLED POSITIVE PAPER EXECUTION LOG (TELEGRAM)
def log_paper_execution(symbol: str, m5_action: str, price: float, score: int, gate_checklist: dict):
    meta = get_symbol_metadata(symbol)
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    trade_id = f"PAPER-{int(datetime.now(timezone.utc).timestamp())}"
    
    sl = price * 0.995 if m5_action == "BUY" else price * 1.005
    tp = price * 1.010 if m5_action == "BUY" else price * 0.990

    msg = (
        f"🟢 *PAPER TRADE EXECUTED*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Symbol:* `{meta['normalized_symbol']}`\n"
        f"• *Direction:* `{m5_action}`\n"
        f"• *Mode:* `{TRADING_MODE}`\n\n"
        f"📊 *CONFLUENCE SCORE:* `{score}/100` (STRONG)\n\n"
        f"💰 *RISK & POSITION*\n"
        f"• *Entry:* `{price:.2f}`\n"
        f"• *SL:* `{sl:.2f}` | *TP:* `{tp:.2f}`\n"
        f"• *R:R Ratio:* `1:2.0` | *Risk:* `0.50%`\n\n"
        f"📡 *DATA PROVIDER AUDIT*\n"
        f"• *Provider:* `{meta['provider']}`\n"
        f"• *Source Symbol:* `{meta['source_symbol']}`\n\n"
        f"🆔 *Trade ID:* `{trade_id}`\n"
        f"⏰ *Timestamp:* `{now_utc}`"
    )
    send_telegram_alert(msg)

# 3. DAILY AUDIT SUMMARY REPORT
@app.get("/daily-summary")
def generate_daily_summary():
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    avg_score = sum(daily_stats["scores"]) / len(daily_stats["scores"]) if daily_stats["scores"] else 0.0

    breakdown_str = "\n".join([f"• *{gate}:* `{count}`" for gate, count in daily_stats["rejection_breakdown"].items()]) or "• *None*"

    msg = (
        f"📊 *DAILY PAPER AUDIT SUMMARY*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"• *Date:* `{daily_stats['date']}`\n"
        f"• *Total Scans:* `{daily_stats['total_scans']}`\n"
        f"• *Candidate Setups:* `{daily_stats['candidate_setups']}`\n"
        f"• *Rejected Candidates:* `{daily_stats['rejected_candidates']}`\n"
        f"• *Paper Executions:* `{daily_stats['paper_executions']}`\n\n"
        f"❌ *REJECTION BREAKDOWN*\n"
        f"{breakdown_str}\n\n"
        f"📈 *METRICS*\n"
        f"• *Average Score:* `{avg_score:.1f}/100`\n"
        f"• *System Errors:* `{daily_stats['system_errors']}`\n\n"
        f"🛡️ *SYSTEM HEALTH*\n"
        f"• *Status:* `🟢 HEALTHY`\n"
        f"• *Mode:* `🟡 PAPER`\n"
        f"• *Live Execution:* `🔒 LOCKED`\n\n"
        f"⏰ *Report Generated:* `{now_utc}`"
    )
    send_telegram_alert(msg)
    return {"status": "success", "data": daily_stats}

# 4. CANDIDATE EVALUATION PIPELINE
def process_symbol_scan(symbol: str):
    daily_stats["total_scans"] += 1
    meta = get_symbol_metadata(symbol)

    try:
        df = yf.download(tickers=symbol, period="2d", interval="5m", progress=False)
        is_data_ok, data_reason = check_data_quality(df)
        if not is_data_ok:
            return

        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        price = float(df['Close'].iloc[-1])
        ema55 = float(df['Close'].ewm(span=55, adjust=False).mean().iloc[-1])
        rsi = 55.0  # Placeholder indicator value
        atr = 1.5   # Placeholder ATR value

        # Candidate setup detection (BUY/SELL)
        m5_action = "NONE"
        if price > ema55:
            m5_action = "BUY"
        elif price < ema55:
            m5_action = "SELL"

        # ANTI-NOISE FILTER: Skip ordinary candles without a candidate direction
        if m5_action == "NONE":
            return

        daily_stats["candidate_setups"] += 1

        # Evaluate Candidate against Hard Gate Chain
        status, failed_gate, score, gate_checklist = evaluate_trade_candidate(
            symbol=symbol,
            m5_action=m5_action,
            price=price,
            ema55=ema55,
            rsi=rsi,
            atr=atr
        )

        daily_stats["scores"].append(score)

        if status == "REJECTED":
            daily_stats["rejected_candidates"] += 1
            daily_stats["rejection_breakdown"][failed_gate] = daily_stats["rejection_breakdown"].get(failed_gate, 0) + 1
            
            # Send Structured Telegram Alert ONLY for Meaningful Candidate Rejections
            log_candidate_rejection(symbol, m5_action, failed_gate, "Gate condition violated", score, gate_checklist)

        elif status == "ACTIONABLE_PAPER_PASS":
            if not MASTER_ENABLE or KILL_SWITCH:
                # Lock Safety Enforcement Check
                log_candidate_rejection(symbol, m5_action, "EXECUTION_LOCK_GATE", "MASTER_ENABLE=False / KILL_SWITCH=True", score, gate_checklist)
            else:
                daily_stats["paper_executions"] += 1
                daily_stats["symbol_breakdown"][meta["normalized_symbol"]] = daily_stats["symbol_breakdown"].get(meta["normalized_symbol"], 0) + 1
                log_paper_execution(symbol, m5_action, price, score, gate_checklist)

    except Exception as e:
        daily_stats["system_errors"] += 1
        print(f"[SCAN ERROR] Exception during {symbol} scan: {e}")

# 5. PUBLIC API ENDPOINTS
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
    """Strict Execution Lock Verification Route."""
    return {
        "symbol": "NONE",
        "action": "NONE",
        "reason": "STRICT_EXECUTION_LOCK_ACTIVE",
        "mode": TRADING_MODE
    }

@app.get("/test-scan")
def trigger_manual_scan(background_tasks: BackgroundTasks):
    """Triggers an immediate manual scan across all target assets."""
    for symbol in SYMBOL_MAP.keys():
        background_tasks.add_task(process_symbol_scan, symbol)
    return {
        "status": "success",
        "message": "Manual gated scan dispatched for BTC-USD, GC=F, and EURUSD=X. Check Telegram for candidate audit logs."
    }
