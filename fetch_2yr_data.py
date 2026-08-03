#!/usr/bin/env python3
"""
fetch_2yr_data.py — 2-Year Data Acquisition for Realistic Backtesting
=======================================================================
Fetches 2 years (August 2024 to August 2026) of:
1. Binance BTCUSDT 30m OHLCV data (source for signals)
2. Delta Exchange BTCUSD perpetual funding rates (for funding costs)

Output files:
- binance_2yr_30m.csv: OHLCV with columns [timestamp, open, high, low, close, volume]
- delta_2yr_funding.csv: Funding rates with columns [timestamp, funding_rate]
"""

from __future__ import annotations

import argparse
import sys
import time
import hmac
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import pandas as pd

try:
    import ccxt
except ImportError:
    sys.exit(
        "ccxt is required. Install with: pip install ccxt --break-system-packages"
    )

# Import bot config for symbol/timeframe consistency
try:
    from config import BINANCE_SYMBOL, CANDLE_TIMEFRAME, DELTA_API_KEY, DELTA_API_SECRET
except Exception:
    BINANCE_SYMBOL, CANDLE_TIMEFRAME = "BTC/USDT", "30m"
    DELTA_API_KEY = ""
    DELTA_API_SECRET = ""

# ──────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────
_TF_MS = {
    "1m": 60_000, "3m": 180_000, "5m": 300_000, "15m": 900_000,
    "30m": 1_800_000, "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000,
    "1d": 86_400_000,
}

# 2-year range: August 2024 to August 2026
DEFAULT_START = "2024-08-01"
DEFAULT_END = "2026-08-02"

DELTA_API_BASE = "https://api.delta.exchange"

# Fallback funding rate if Delta API fails (0.01% per 8h)
FALLBACK_FUNDING_RATE = 0.0001


def _period_ms(tf: str) -> int:
    if tf not in _TF_MS:
        sys.exit(f"Unknown timeframe {tf!r}")
    return _TF_MS[tf]


def _delta_hmac_signature(secret: str, timestamp: str, method: str, path: str, query: str, body: str = "") -> str:
    """
    Generate HMAC-SHA256 signature for Delta Exchange API.
    signature = hmac_sha256(secret, timestamp + method + path + query + body)
    """
    # Per Delta API docs: path should include query string with leading ?
    # Query params should be sorted alphabetically
    message = timestamp + method.upper() + path + query + body
    signature = hmac.new(
        secret.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


def _delta_auth_headers(method: str, path: str, query: str = "", body: str = "") -> dict:
    """
    Generate authentication headers for Delta Exchange API.
    Requires: api-key, timestamp, signature
    """
    timestamp = str(int(time.time()))
    signature = _delta_hmac_signature(DELTA_API_SECRET, timestamp, method, path, query, body)

    return {
        "api-key": DELTA_API_KEY,
        "timestamp": timestamp,
        "signature": signature,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ═══════════════════════════════════════════════════════════════════════
# BINANCE OHLCV FETCHER
# ═══════════════════════════════════════════════════════════════════════
def fetch_binance_ohlcv(
    symbol: str,
    timeframe: str,
    start_dt: datetime,
    end_dt: datetime,
) -> pd.DataFrame:
    """
    Fetch OHLCV from Binance REST API using ccxt.
    Walks forward from start to end in <=1000-bar batches.
    """
    exchange = ccxt.binance({"enableRateLimit": True})
    exchange.load_markets()
    period = _period_ms(timeframe)

    all_ohlcv = []
    cursor = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    print(f"Fetching {symbol} {timeframe} from {start_dt} to {end_dt}...")
    while cursor < end_ms and len(all_ohlcv) < 1000000:  # Safety cap
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=cursor, limit=1000)
        if not batch:
            break

        # Filter to requested range
        batch = [b for b in batch if b[0] <= end_ms]
        if not batch:
            break

        all_ohlcv.extend(batch)
        cursor = int(batch[-1][0]) + period

        # Progress
        last_ts = datetime.fromtimestamp(batch[-1][0] / 1000, tz=timezone.utc)
        print(f"  Fetched {len(all_ohlcv)} bars... (up to {last_ts})")

        if len(batch) < 1000:
            break
        time.sleep(exchange.rateLimit / 1000)

    if not all_ohlcv:
        return pd.DataFrame()

    df = pd.DataFrame(all_ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = df.astype({
        "timestamp": "int64",
        "open": float, "high": float, "low": float,
        "close": float, "volume": float
    })
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    return df


# ═══════════════════════════════════════════════════════════════════════
# DELTA EXCHANGE FUNDING RATE FETCHER (with HMAC auth)
# ═══════════════════════════════════════════════════════════════════════
def fetch_delta_funding_rates(
    symbol: str = "FUNDING:BTCUSD",
    start_dt: datetime = None,
    end_dt: datetime = None,
) -> pd.DataFrame:
    """
    Fetch historical funding rates from Delta Exchange using HMAC authentication.

    Delta API: GET /v2/history/candles
    Params: symbol=FUNDING:BTCUSD, resolution=8h, start, end

    Auth: HMAC-SHA256 with provided credentials
    """
    import requests

    if start_dt is None:
        start_dt = datetime(2024, 8, 1, tzinfo=timezone.utc)
    if end_dt is None:
        end_dt = datetime(2026, 8, 2, tzinfo=timezone.utc)

    all_funding = []
    cursor = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())

    print(f"Fetching Delta {symbol} funding rates from {start_dt} to {end_dt}...")

    session = requests.Session()

    # Check if credentials are available
    if not DELTA_API_KEY or not DELTA_API_SECRET or DELTA_API_KEY == "YOUR_API_KEY":
        print("  WARNING: Delta API credentials not configured, using fallback rate...")
        return generate_fallback_funding_rates(start_dt, end_dt)

    while cursor < end_ts:
        params = {
            "symbol": symbol,
            "resolution": "8h",  # Funding occurs every 8 hours (00, 08, 16 UTC)
            "start": cursor,
            "end": min(cursor + 30 * 24 * 3600, end_ts),  # 30-day chunks
        }

        # Sort params alphabetically for consistent signature
        sorted_params = sorted(params.items())
        query_string = urlencode(sorted_params)
        path = f"/v2/history/candles?{query_string}"

        try:
            headers = _delta_auth_headers("GET", path)
            url = f"{DELTA_API_BASE}{path}"
            resp = session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  Error fetching funding data: {e}")
            print("  Falling back to constant funding rate...")
            return generate_fallback_funding_rates(start_dt, end_dt)

        candles = data.get("result", [])
        if not candles:
            break

        for c in candles:
            # Delta funding candle response: time, open, high, low, close, volume
            # For funding symbol, close = funding rate
            ts = c["time"]  # Unix timestamp in seconds
            funding_rate = float(c["close"])  # Funding rate as decimal (e.g., 0.0001 = 0.01%)
            all_funding.append({
                "timestamp": ts * 1000,  # Convert to ms
                "funding_rate": funding_rate,
            })

        cursor = int(candles[-1]["time"]) + 8 * 3600
        last_ts = datetime.fromtimestamp(candles[-1]["time"], tz=timezone.utc)
        print(f"  Fetched {len(all_funding)} funding rates... (up to {last_ts})")

        if len(candles) < 500:
            break
        time.sleep(0.5)

    if not all_funding:
        print("  No funding data from API, using fallback rate...")
        return generate_fallback_funding_rates(start_dt, end_dt)

    df = pd.DataFrame(all_funding)
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("int64")
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp").reset_index(drop=True)
    return df


def generate_fallback_funding_rates(
    start_dt: datetime,
    end_dt: datetime,
    base_rate: float = FALLBACK_FUNDING_RATE,
) -> pd.DataFrame:
    """
    Generate constant fallback funding rates when Delta API is unavailable.
    Per spec: use constant 0.0001 (0.01%/8h), log warning.
    """
    print(f"  WARNING: Using fallback constant funding rate: {base_rate*100:.4f}% per 8h")

    timestamps = []
    rates = []

    current = start_dt
    while current < end_dt:
        # Funding at 00:00, 08:00, 16:00 UTC
        for hour in [0, 8, 16]:
            ts = current.replace(hour=hour, minute=0, second=0, microsecond=0)
            if ts < start_dt or ts > end_dt:
                continue

            timestamps.append(int(ts.timestamp() * 1000))
            rates.append(base_rate)

        current += timedelta(days=1)

    return pd.DataFrame({
        "timestamp": timestamps,
        "funding_rate": rates,
    })


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
def parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def main():
    ap = argparse.ArgumentParser(description="Fetch 2-year historical data for backtesting")
    ap.add_argument("--symbol", default=BINANCE_SYMBOL,
                    help=f"Binance symbol (default: {BINANCE_SYMBOL})")
    ap.add_argument("--timeframe", default=CANDLE_TIMEFRAME,
                    help=f"Candle timeframe (default: {CANDLE_TIMEFRAME})")
    ap.add_argument("--start", default=DEFAULT_START,
                    help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})")
    ap.add_argument("--end", default=DEFAULT_END,
                    help=f"End date YYYY-MM-DD (default: {DEFAULT_END})")
    ap.add_argument("--out-binance", default="binance_2yr_30m.csv",
                    help="Output CSV for OHLCV data (default: binance_2yr_30m.csv)")
    ap.add_argument("--out-delta", default="delta_2yr_funding.csv",
                    help="Output CSV for funding rates (default: delta_2yr_funding.csv)")
    ap.add_argument("--delta-symbol", default="FUNDING:BTCUSD",
                    help="Delta Exchange funding symbol (default: FUNDING:BTCUSD)")

    args = ap.parse_args()

    start_dt = parse_date(args.start)
    end_dt = parse_date(args.end)

    print("=" * 70)
    print("2-YEAR DATA ACQUISITION FOR REALISTIC BACKTESTING")
    print("=" * 70)
    print(f"Period: {start_dt.date()} to {end_dt.date()}")
    print(f"Binance Symbol: {args.symbol} | Timeframe: {args.timeframe}")
    print(f"Delta Symbol: {args.delta_symbol}")
    print()

    # ── Fetch Binance OHLCV ──
    print("[1/2] Fetching Binance OHLCV...")
    ohlcv_df = fetch_binance_ohlcv(
        args.symbol, args.timeframe, start_dt, end_dt
    )

    if ohlcv_df.empty:
        print("ERROR: No OHLCV data fetched!")
        return 1

    ohlcv_df.to_csv(args.out_binance, index=False)
    print(f"  [OK] Saved {len(ohlcv_df)} bars to {args.out_binance}")
    print(f"  Range: {datetime.fromtimestamp(ohlcv_df.iloc[0].timestamp/1000, tz=timezone.utc)} " +
          f"-> {datetime.fromtimestamp(ohlcv_df.iloc[-1].timestamp/1000, tz=timezone.utc)}")

    # ── Fetch Delta Funding Rates ──
    print("\n[2/2] Fetching Delta Exchange Funding Rates...")
    funding_df = fetch_delta_funding_rates(
        args.delta_symbol, start_dt, end_dt
    )

    funding_df.to_csv(args.out_delta, index=False)
    print(f"  [OK] Saved {len(funding_df)} funding rates to {args.out_delta}")
    if len(funding_df):
        print(f"  Range: {datetime.fromtimestamp(funding_df.iloc[0].timestamp/1000, tz=timezone.utc)} " +
              f"-> {datetime.fromtimestamp(funding_df.iloc[-1].timestamp/1000, tz=timezone.utc)}")
        print(f"  Avg funding rate: {funding_df['funding_rate'].mean()*100:.4f}% per 8h")

    print("\n" + "=" * 70)
    print("DATA ACQUISITION COMPLETE")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())