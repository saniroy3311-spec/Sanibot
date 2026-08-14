#!/usr/bin/env python3
"""
25-Month Backtest on Delta Exchange India BTCUSDT 30m Data
Exact live bot config from .eve
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from live_config_backtester import LiveBotConfig, LiveConfigBacktester

# Load Delta data
print("Loading Delta 25-month data...")
ohlcv_df = pd.read_csv("delta_BTCUSDT_30m_25months.csv")
ohlcv_df["timestamp"] = pd.to_datetime(ohlcv_df["timestamp"])

print(f"Loaded {len(ohlcv_df)} candles")
print(f"Date range: {ohlcv_df['timestamp'].iloc[0]} to {ohlcv_df['timestamp'].iloc[-1]}")
print(f"Price range: {ohlcv_df['close'].min():,.2f} to {ohlcv_df['close'].max():,.2f}")

# Create synthetic funding rates (8-hour intervals, typical ~0.01%/8h)
print("\nGenerating synthetic funding rates (Delta typical ~0.01%/8h)...")
funding_times = pd.date_range(
    start=ohlcv_df['timestamp'].iloc[0].floor('8h'),
    end=ohlcv_df['timestamp'].iloc[-1].ceil('8h'),
    freq='8h'
)
funding_df = pd.DataFrame({
    'timestamp': funding_times.astype('int64') // 10**6,  # Convert to ms epoch
    'funding_rate': 0.0001,  # 0.01% per 8h = typical Delta BTC rate
    'mark_price': ohlcv_df.set_index('timestamp')['close'].reindex(funding_times, method='ffill').values
})
print(f"Generated {len(funding_df)} funding rates")

# Run backtest with exact live config
config = LiveBotConfig()
backtester = LiveConfigBacktester(config, funding_df)

print("\nRunning 25-month backtest with exact .eve config...")
trades, equity = backtester.run(ohlcv_df)

# Detailed bracket report
trades_df = pd.DataFrame([t.__dict__ for t in trades])

print("\n" + "=" * 140)
print("25-MONTH DELTA BACKTEST — BRACKET DETAILS PER TRADE (Exact .eve Config)")
print("=" * 140)
print(f"{'#':>4} {'Date':>10} {'Time':>8} {'Dir':>5} {'Qty':>6} {'Entry':>10} {'SL':>10} {'TP':>10} {'Exit':>10} {'Pts':>8} {'Gross':>9} {'Net':>9} {'Reason':>20} {'Stage':>5} {'Bars':>4}")
print("-" * 140)

for _, t in trades_df.iterrows():
    is_long = t['direction'] == 'LONG'
    entry = t['entry_price']

    # Recalculate initial SL/TP from ATR at entry
    # We need to approximate ATR - use points captured as proxy
    if t['trail_stage_at_exit'] > 0:
        atr_est = abs(t['points_captured']) / t['trail_stage_at_exit'] * 5  # rough
    else:
        atr_est = 150  # fallback

    sl_dist = atr_est * 0.6
    tp_dist = sl_dist * 4.0

    if is_long:
        sl_init = entry - sl_dist
        tp_init = entry + tp_dist
    else:
        sl_init = entry + sl_dist
        tp_init = entry - tp_dist

    dt = pd.Timestamp(t['entry_time'], unit='ms')
    date_str = dt.strftime('%Y-%m-%d')
    time_str = dt.strftime('%H:%M')

    print(f"{t['trade_id']:>4} {date_str:>10} {time_str:>8} {t['direction']:>5} {t['size_btc']:>6.3f} "
          f"{entry:>10.2f} {sl_init:>10.2f} {tp_init:>10.2f} {t['exit_price']:>10.2f} "
          f"{t['points_captured']:>8.2f} {t['gross_pnl']:>9.4f} {t['net_pnl']:>9.4f} "
          f"{t['exit_reason']:>20} {t['trail_stage_at_exit']:>5} {t['bars_held']:>4}")

print("=" * 140)

# Summary
total = len(trades_df)
wins = len(trades_df[trades_df['net_pnl'] > 0])
losses = len(trades_df[trades_df['net_pnl'] <= 0])
net_total = trades_df['net_pnl'].sum()
gross_total = trades_df['gross_pnl'].sum()
total_fees = trades_df['entry_fee'].sum() + trades_df['entry_gst'].sum() + trades_df['exit_fee'].sum() + trades_df['exit_gst'].sum()
total_funding = trades_df['funding_paid'].sum()

print(f"\nSUMMARY:")
print(f"  Period: {ohlcv_df['timestamp'].iloc[0].date()} to {ohlcv_df['timestamp'].iloc[-1].date()}")
print(f"  Total Trades: {total} | Wins: {wins} | Losses: {losses} | Win Rate: {wins/total*100:.1f}%")
print(f"  Gross P&L: ${gross_total:.2f} | Net P&L: ${net_total:.2f}")
print(f"  Fees+GST: ${total_fees:.2f} | Funding: ${total_funding:.4f} | Net Drag: ${total_fees - total_funding:.2f}")
print(f"  Avg Points/Trade: {trades_df['points_captured'].mean():.1f}")
print(f"  Best Trade: {trades_df['points_captured'].max():.1f} pts (${trades_df['net_pnl'].max():.2f})")
print(f"  Worst Trade: {trades_df['points_captured'].min():.1f} pts (${trades_df['net_pnl'].min():.2f})")

# Monthly breakdown
trades_df['entry_dt'] = pd.to_datetime(trades_df['entry_time'], unit='ms')
trades_df['month'] = trades_df['entry_dt'].dt.to_period('M')
monthly = trades_df.groupby('month').agg({
    'trade_id': 'count',
    'net_pnl': 'sum',
    'points_captured': 'mean'
}).round(2)
monthly.columns = ['Trades', 'Net $', 'Avg Pts']
print(f"\nMONTHLY BREAKDOWN:")
print(monthly.to_string())

# Export
trades_df.to_csv("backtest_delta_25months_trades.csv", index=False)
print(f"\nExported {len(trades_df)} trades to backtest_delta_25months_trades.csv")

# Equity curve data
equity_df = pd.DataFrame(equity, columns=['timestamp', 'equity'])
equity_df['timestamp'] = pd.to_datetime(equity_df['timestamp'], unit='ms')
equity_df.to_csv("backtest_delta_25months_equity.csv", index=False)
print(f"Exported equity curve to backtest_delta_25months_equity.csv")