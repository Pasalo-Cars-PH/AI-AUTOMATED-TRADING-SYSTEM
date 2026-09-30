import pandas as pd
import yfinance as yf

# Provider Audit Normalization
SYMBOL_MAP = {
    "BTC-USD": {"normalized": "BTCUSD", "provider": "yfinance", "source": "BTC-USD"},
    "GC=F": {"normalized": "XAUUSD", "provider": "yfinance", "source": "GC=F"},
    "EURUSD=X": {"normalized": "EURUSD", "provider": "yfinance", "source": "EURUSD=X"}
}

def get_symbol_metadata(symbol):
    return SYMBOL_MAP.get(symbol, {"normalized": symbol, "provider": "yfinance", "source": symbol})
