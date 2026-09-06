"""
Quick standalone check of current ema_fast/ema_trend/close using the SAME
compute() function the live bot calls in indicators/engine.py.

Uses Binance public OHLCV (no API key needed) as the data source purely to
get a representative current bar — the bot itself trades off Delta Exchange
data via CandleFeed, so treat this as a sanity check, not the exact tick the
bot is evaluating.

Run:
    cd /root/Sanibot
    python3 check_live_indicators.py
"""
import sys
sys.path.insert(0, "/root/Sanibot")

import asyncio
import pandas as pd
import ccxt.async_support as ccxt_async

from indicators.engine import compute


async def main():
    exchange = ccxt_async.binance()
    try:
        ohlcv = await exchange.fetch_ohlcv("BTC/USDT", timeframe="30m", limit=250)
    finally:
        await exchange.close()

    df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])

    snap = compute(df)

    print(f"Close:            {snap.close:,.2f}")
    print(f"ema_fast (50):    {snap.ema_fast:,.2f}")
    print(f"ema_trend (200):  {snap.ema_trend:,.2f}")
    print(f"trend_regime:     {snap.trend_regime}")
    print(f"filters_ok:       {snap.filters_ok}")
    print()
    print(f"Long direction OK:  {snap.close > snap.ema_fast and snap.close > snap.ema_trend}")
    print(f"Short direction OK: {snap.close < snap.ema_fast and snap.close < snap.ema_trend}")


if __name__ == "__main__":
    asyncio.run(main())
