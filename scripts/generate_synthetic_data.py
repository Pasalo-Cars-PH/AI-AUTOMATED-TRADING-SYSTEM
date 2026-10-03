import pandas as pd
import numpy as np
import datetime

def generate_spot_ohlc(symbol: str, days=30):
    start = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    periods_m1 = days * 24 * 60
    
    dates_m1 = [start + datetime.timedelta(minutes=i) for i in range(periods_m1)]
    
    # Synthetic Random Walk Price Action
    base_price = 2650.0 if symbol == "XAUUSD" else (1.0850 if symbol == "EURUSD" else 1.2650)
    volatility = 0.5 if symbol == "XAUUSD" else 0.0002
    
    returns = np.random.normal(0, volatility, periods_m1)
    price_path = base_price + np.cumsum(returns)

    df_m1 = pd.DataFrame({
        "datetime_utc": dates_m1,
        "open": price_path,
        "high": price_path + abs(np.random.normal(0, volatility, periods_m1)),
        "low": price_path - abs(np.random.normal(0, volatility, periods_m1)),
        "close": price_path + np.random.normal(0, volatility / 2, periods_m1)
    })

    # Resample to Multi-Timeframes
    df_m1.set_index("datetime_utc", inplace=True)
    
    df_m5 = df_m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
    df_m15 = df_m1.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
    df_h1 = df_m1.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna().reset_index()
    df_m1 = df_m1.reset_index()

    return df_h1, df_m15, df_m5, df_m1

if __name__ == "__main__":
    for pair in ["XAUUSD", "EURUSD", "GBPUSD"]:
        h1, m15, m5, m1 = generate_spot_ohlc(pair, days=15)
        os.makedirs("data_sample", exist_ok=True)
        h1.to_csv(f"data_sample/{pair}_H1.csv", index=False)
        m15.to_csv(f"data_sample/{pair}_M15.csv", index=False)
        m5.to_csv(f"data_sample/{pair}_M5.csv", index=False)
        m1.to_csv(f"data_sample/{pair}_M1.csv", index=False)
    print("✅ Synthetic multi-timeframe dataset generated in /data_sample!")
