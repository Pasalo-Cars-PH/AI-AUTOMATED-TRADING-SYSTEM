import os
import requests
import pandas as pd
from datetime import datetime
import pytz

class TelegramAlerts:
    def __init__(self, token: str = None, chat_id: str = None):
        self.token = token or os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHANNEL_ID")
        self.enabled = bool(self.token and self.chat_id)
        self.pht = pytz.timezone('Asia/Manila')

    def _format_time(self, dt):
        """Gawing PHT yung candle time para tama sa chart mo"""
        try:
            if dt is None:
                return "N/A"
            # kung string
            if isinstance(dt, str):
                dt = pd.to_datetime(dt)
            # kung pandas timestamp
            if hasattr(dt, 'tzinfo') and dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            elif hasattr(dt, 'tzinfo') == False:
                dt = pytz.utc.localize(pd.to_datetime(dt))
            
            # Convert to PHT
            pht_time = dt.astimezone(self.pht)
            return pht_time.strftime("%b %d, %I:%M %p PHT")  # Oct 02, 10:25 PM PHT
        except Exception as e:
            try:
                return str(dt)[:19]
            except:
                return "N/A"

    def _format_price(self, symbol, price):
        """Tamang decimals: EURUSD 5 decimals, XAU 2 decimals"""
        try:
            if price is None:
                return "N/A"
            if "XAU" in symbol or "GOLD" in symbol:
                return f"{float(price):.2f}"
            elif "JPY" in symbol:
                return f"{float(price):.3f}"
            else: # EURUSD, GBPUSD
                return f"{float(price):.5f}"
        except:
            return str(price)

    def send(self, text: str):
        if not self.enabled:
            print(f"[TELEGRAM DISABLED] {text}")
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            # Markdown safe - tanggalin mga problem characters
            payload = {
                "chat_id": self.chat_id, 
                "text": text, 
                "parse_mode": "Markdown"
            }
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code != 200:
                # fallback without markdown kung may error
                payload["parse_mode"] = None
                requests.post(url, json=payload, timeout=15)
        except Exception as e:
            print(f"Telegram send failed: {e}")

    def scanning_start(self):
        self.send("🔍 *Scanning M5 setups on Live Market Data...*")

    def no_setups(self):
        self.send("ℹ️ *No active Killzone M5 setups detected right now.*\n_Ayos lang, naghihintay ng Hammer/Shooting Star._")

    def signal_detected(self, symbol, signal):
        """
        signal dict galing sa strategy:
        {
          'datetime': candle datetime (UTC),
          'side': 'long'/'short' or 'buy'/'sell',
          'entry_price': float,
          'sl': float,
          'tp': float,
          'reason': str,
          'pinbar': 'Hammer' / 'Shooting Star'
        }
        """
        try:
            dt = signal.get('datetime')
            candle_time_pht = self._format_time(dt)
            # UTC time din para clear
            utc_str = ""
            try:
                utc_dt = pd.to_datetime(dt)
                if utc_dt.tzinfo is None:
                    utc_dt = pytz.utc.localize(utc_dt)
                utc_str = utc_dt.strftime("%H:%M UTC")
            except:
                pass

            side = signal.get('side', '').upper()
            if side == 'LONG': side = 'BUY'
            if side == 'SHORT': side = 'SELL'

            entry = self._format_price(symbol, signal.get('entry_price'))
            sl = self._format_price(symbol, signal.get('sl'))
            tp = self._format_price(symbol, signal.get('tp'))
            pinbar = signal.get('pinbar', signal.get('pinbar_type', 'N/A'))
            reason = signal.get('reason', 'SMC Sweep + FVG')

            # Emoji depende sa side
            emoji = "🟢" if side == "BUY" else "🔴"
            pin_emoji = "🔨" if "Hammer" in str(pinbar) else ("⭐" if "Shooting" in str(pinbar) else "📌")

            msg = (
                f"⚡ *M5 SMC SIGNAL DETECTED* {emoji}\n\n"
                f"• *Pair:* {symbol} | *Action:* {side}\n"
                f"• *Entry:* {entry}\n"
                f"• *SL:* {sl} | *TP:* {tp}\n"
                f"• *Candle Time:* {candle_time_pht} ({utc_str})\n"
                f"• {pin_emoji} *Pinbar:* {pinbar}\n"
                f"• *Reason:* {reason}\n"
                f"_Scan: {datetime.now(self.pht).strftime('%b %d %I:%M %p')}_"
            )
            self.send(msg)
        except Exception as e:
            print(f"signal format error: {e}")
            # fallback simple
            self.send(f"⚡ M5 SIGNAL {symbol} {signal.get('side','')} Entry {signal.get('entry_price')}")

    # Old methods para compatible pa rin sa main.py mo
    def entry(self, symbol, side, entry, sl, tp, reason):
        # wrapper para sa old code
        sig = {
            'datetime': pd.Timestamp.utcnow(),
            'side': side,
            'entry_price': entry,
            'sl': sl,
            'tp': tp,
            'reason': reason,
            'pinbar': 'N/A'
        }
        self.signal_detected(symbol, sig)

    def exit(self, symbol, side, exit_price, r, reason):
        self.send(f"📉 *EXIT* {symbol} {side} @ {exit_price:.2f} R={r:.2f}\n{reason}")

    def error(self, msg):
        self.send(f"⚠️ *ERROR* {msg}")

    def daily_summary(self, equity, dd, trades_today):
        self.send(f"📊 *DAILY* Equity {equity:.2f} DD {dd*100:.2f}% Trades today {trades_today}")

    def data_fetch_failed(self, symbols):
        """Kapag wala talagang data"""
        sym_str = ", ".join(symbols) if isinstance(symbols, list) else str(symbols)
        self.send(f"⚠️ *Data Fetch Failed or Insufficient:* {sym_str}\n_Check TWELVE_DATA_API_KEY sa Render._")

    def status_ok(self, mode, paper, data_provider):
        now_pht = datetime.now(self.pht).strftime("%Y-%m-%d %I:%M:%S %p PHT")
        msg = (
            f"📊 *ENGINE OPERATIONAL STATUS*\n\n"
            f"• *System Mode:* {mode}\n"
            f"• *Paper Session:* {paper}\n"
            f"• *Data Provider:* {data_provider}\n"
            f"• *Current Time:* {now_pht}\n"
            f"• *Pinbar Filter:* ON (Hammer/Shooting Star required)"
        )
        self.send(msg)
