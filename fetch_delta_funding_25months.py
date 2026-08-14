#!/usr/bin/env python3
"""
Fetch 25 months of funding rates from Delta Exchange India
BTCUSDT perpetual - 8-hour funding intervals
"""

import requests
import pandas as pd
import time
from datetime import datetime, timedelta

BASE_URL = "https://api.delta.exchange/v2/history/funding_rates"
SYMBOL = "BTCUSDT"
CHUNK_DAYS = 15
RATE_LIMIT_SLEEP = 0.2

def fetch_funding_chunk(start_ts: int, end_ts: int) -> list:
    params = {
        "symbol": SYMBOL,
        "start": start_ts,
        "end": end_ts
    }
    resp = requests.get(BASE_URL, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("result", [])

def fetch_25_months_funding():
    end_dt = datetime.utcnow().replace(second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=25 * 30.44)

    print("Fetching {} funding rates from {} to {}".format(SYMBOL, start_dt, end_dt))
    print("Days: {}".format((end_dt - start_dt).days))

    all_rates = []
    current_end = int(end_dt.timestamp())
    chunk_count = 0

    while current_end > int(start_dt.timestamp()):
        chunk_start = max(current_end - CHUNK_DAYS * 86400, int(start_dt.timestamp()))

        print("  Chunk {}: {} to {}".format(chunk_count + 1,
            datetime.utcfromtimestamp(chunk_start), datetime.utcfromtimestamp(current_end)))

        try:
            rates = fetch_funding_chunk(chunk_start, current_end)
            if rates:
                all_rates.extend(rates)
                print("    Got {} rates".format(len(rates)))
            else:
                print("    Empty response")

            chunk_count += 1
            current_end = chunk_start - 1
            time.sleep(RATE_LIMIT_SLEEP)

        except Exception as e:
            print("    Error: {}".format(e))
            time.sleep(2)
            continue

    if not all_rates:
        print("No funding data fetched!")
        return None

    df = pd.DataFrame(all_rates)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    df = df.rename(columns={"funding_rate": "funding_rate", "mark_price": "mark_price"})
    df = df[["timestamp", "funding_rate", "mark_price"]]
    df = df.sort_values("timestamp").drop_duplicates(subset="timestamp").reset_index(drop=True)

    filename = "delta_{}_funding_25months.csv".format(SYMBOL)
    df.to_csv(filename, index=False)
    print("\nSaved {} funding rates to {}".format(len(df), filename))
    print("Date range: {} to {}".format(df['timestamp'].iloc[0], df['timestamp'].iloc[-1]))
    print("Rate range: {:.6%} to {:.6%}".format(df['funding_rate'].min(), df['funding_rate'].max()))

    return df

if __name__ == "__main__":
    fetch_25_months_funding()