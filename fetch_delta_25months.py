#!/usr/bin/env python3
"""
Fetch 25 months of 30m candles from Delta Exchange India
BTCUSDT perpetual - walks backward in chunks (max ~1500 candles per call)
"""

import requests
import pandas as pd
import time
from datetime import datetime, timedelta

BASE_URL = "https://api.delta.exchange/v2/history/candles"
SYMBOL = "BTCUSDT"
RESOLUTION = "30m"
CHUNK_DAYS = 15  # ~720 candles per chunk, safe under limits
RATE_LIMIT_SLEEP = 0.2  # 5 req/sec max

def fetch_chunk(start_ts: int, end_ts: int) -> list:
    """Fetch one chunk of candles"""
    params = {
        "symbol": SYMBOL,
        "resolution": RESOLUTION,
        "start": start_ts,
        "end": end_ts
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("result", [])

def fetch_25_months():
    """Fetch from 25 months ago to now"""
    end_dt = datetime.utcnow().replace(second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=25 * 30.44)  # ~25 months

    print("Fetching {} {} from {} to {}".format(SYMBOL, RESOLUTION, start_dt, end_dt))
    print("Days: {}, approx {} candles".format((end_dt - start_dt).days, (end_dt - start_dt).days * 48))

    all_candles = []
    current_end = int(end_dt.timestamp())
    chunk_count = 0

    while current_end > int(start_dt.timestamp()):
        chunk_start = max(current_end - CHUNK_DAYS * 86400, int(start_dt.timestamp()))

        print("  Chunk {}: {} to {}".format(chunk_count + 1,
            datetime.utcfromtimestamp(chunk_start), datetime.utcfromtimestamp(current_end)))

        try:
            candles = fetch_chunk(chunk_start, current_end)
            if candles:
                all_candles.extend(candles)
                print("    Got {} candles".format(len(candles)))
            else:
                print("    Empty response")

            chunk_count += 1
            current_end = chunk_start - 1
            time.sleep(RATE_LIMIT_SLEEP)

        except Exception as e:
            print("    Error: {}".format(e))
            time.sleep(2)
            continue

    if not all_candles:
        print("No data fetched!")
        return None

    # Convert to DataFrame
    df = pd.DataFrame(all_candles)
    df["timestamp"] = pd.to_datetime(df["time"], unit="s")
    df = df.rename(columns={
        "open": "open", "high": "high", "low": "low",
        "close": "close", "volume": "volume"
    })
    df = df[["timestamp", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("timestamp").drop_duplicates(subset="timestamp").reset_index(drop=True)

    # Save
    filename = "delta_{}_{}_25months.csv".format(SYMBOL, RESOLUTION)
    df.to_csv(filename, index=False)
    print("\nSaved {} candles to {}".format(len(df), filename))
    print("Date range: {} to {}".format(df['timestamp'].iloc[0], df['timestamp'].iloc[-1]))

    return df

if __name__ == "__main__":
    fetch_25_months()