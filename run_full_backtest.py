#!/usr/bin/env python3
"""
run_full_backtest.py — 2-Year Realistic Backtest Runner
========================================================
Orchestrates the complete backtest pipeline:
1. Loads 2-year OHLCV data (Binance BTCUSDT 30m)
2. Loads funding rates (Delta Exchange)
3. Runs realistic event-driven backtest
4. Generates performance dashboard
5. Prints formatted terminal report

Usage:
    python run_full_backtest.py --ohlcv binance_2yr_30m.csv --funding delta_2yr_funding.csv
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path

import pandas as pd
import numpy as np


# ──────────────────────────────────────────────────────────────────────
# DATA LOADING
# ──────────────────────────────────────────────────────────────────────
def load_ohlcv_csv(path: str) -> pd.DataFrame:
    """Load OHLCV CSV with flexible column handling."""
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for k in ("timestamp", "time", "date", "open", "high", "low", "close", "volume"):
        if k in cols:
            rename[cols[k]] = k
    df = df.rename(columns=rename)

    if "timestamp" not in df.columns:
        if "time" in df.columns:
            df["timestamp"] = df["time"]
        elif "date" in df.columns:
            df["timestamp"] = pd.to_datetime(df["date"]).astype("int64") // 1_000_000

    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("int64")

    # Convert to milliseconds if needed
    if df["timestamp"].iloc[0] < 1_000_000_000_000:
        df["timestamp"] = df["timestamp"] * 1000

    df = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df = df.dropna().sort_values("timestamp").reset_index(drop=True)
    return df


def load_funding_csv(path: str) -> pd.DataFrame:
    """Load funding rates CSV."""
    if not os.path.exists(path):
        return pd.DataFrame()

    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    rename = {}
    for k in ("timestamp", "time", "date", "funding_rate", "rate", "mark_price", "mark"):
        if k in cols:
            rename[cols[k]] = k
    df = df.rename(columns=rename)

    if "timestamp" not in df.columns:
        if "time" in df.columns:
            df["timestamp"] = df["time"]
        elif "date" in df.columns:
            df["timestamp"] = pd.to_datetime(df["date"]).astype("int64") // 1_000_000

    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce").astype("int64")
    if df["timestamp"].iloc[0] < 1_000_000_000_000:
        df["timestamp"] = df["timestamp"] * 1000

    # Ensure required columns
    if "funding_rate" not in df.columns and "rate" in df.columns:
        df["funding_rate"] = df["rate"]
    if "mark_price" not in df.columns and "mark" in df.columns:
        df["mark_price"] = df["mark"]

    for c in ("funding_rate", "mark_price"):
        if c not in df.columns:
            df[c] = 0.0
        else:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0).astype(float)

    df = df[["timestamp", "funding_rate", "mark_price"]].copy()
    df = df.dropna().sort_values("timestamp").reset_index(drop=True)
    return df


# ──────────────────────────────────────────────────────────────────────
# MAIN RUNNER
# ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description="Run 2-Year Realistic Event-Driven Backtest",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
    python run_full_backtest.py \\
        --ohlcv binance_2yr_30m.csv \\
        --funding delta_2yr_funding.csv \\
        --output-dir ./backtest_results
        """
    )
    ap.add_argument("--ohlcv", required=True, help="Path to Binance 30m OHLCV CSV")
    ap.add_argument("--funding", default=None, help="Path to Delta funding rates CSV (optional)")
    ap.add_argument("--output-dir", default=".", help="Output directory for results")
    ap.add_argument("--capital", type=float, default=50000.0, help="Initial capital USD")
    ap.add_argument("--position-btc", type=float, default=0.1, help="Position size in BTC")
    ap.add_argument("--no-dashboard", action="store_true", help="Skip dashboard generation")
    ap.add_argument("--quiet", action="store_true", help="Suppress progress output")

    args = ap.parse_args()

    # Validate inputs
    if not os.path.exists(args.ohlcv):
        print(f"ERROR: OHLCV file not found: {args.ohlcv}")
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ─── Load Data ───
    if not args.quiet:
        print("=" * 70)
        print("2-YEAR REALISTIC BACKTEST PIPELINE")
        print("=" * 70)
        print(f"Loading OHLCV data from {args.ohlcv}...")

    ohlcv_df = load_ohlcv_csv(args.ohlcv)

    if not args.quiet:
        print(f"  Loaded {len(ohlcv_df):,} bars")
        start_ts = pd.Timestamp(ohlcv_df.iloc[0]["timestamp"], unit="ms", tz="UTC")
        end_ts = pd.Timestamp(ohlcv_df.iloc[-1]["timestamp"], unit="ms", tz="UTC")
        print(f"  Period: {start_ts.date()} to {end_ts.date()}")

    # Load funding
    if args.funding and os.path.exists(args.funding):
        if not args.quiet:
            print(f"Loading funding rates from {args.funding}...")
        funding_df = load_funding_csv(args.funding)
        if not args.quiet:
            print(f"  Loaded {len(funding_df):,} funding records")
    else:
        if not args.quiet:
            print("No funding file provided - using synthetic rates")
        funding_df = pd.DataFrame()

    # ─── Configure Backtest ───
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from realistic_backtester import BacktestConfig, RealisticBacktester

    config = BacktestConfig(
        initial_capital=args.capital,
        position_btc_size=args.position_btc,
    )

    if not args.quiet:
        print(f"\nConfiguration:")
        print(f"  Initial Capital: ${config.initial_capital:,.2f}")
        lots = int(config.position_btc_size * config.lot_size_multiplier)
        print(f"  Position Size: {config.position_btc_size} BTC ({lots} lots)")
        print(f"  Taker Fee: {config.taker_fee_pct*100:.3f}% | Maker Fee: {config.maker_fee_pct*100:.3f}%")
        print(f"  GST (Tax): {config.gst_pct*100:.0f}% on fees")
        print(f"  SL Confirmation: {config.sl_confirm_ticks} ticks")
        print(f"  Slippage: {config.slippage_pct*100:.3f}%")

    # ─── Run Backtest ───
    if not args.quiet:
        print("\n" + "=" * 70)
        print("STARTING BACKTEST")
        print("=" * 70)

    backtester = RealisticBacktester(config, funding_df)
    trades, equity_curve = backtester.run(ohlcv_df)

    # ─── Generate Results ───
    results = backtester.get_results_dict()

    # ─── Print Terminal Report ───
    print_full_terminal_report(results, config)

    # ─── Generate Dashboard ───
    if not args.no_dashboard:
        if not args.quiet:
            print("\nGenerating performance dashboard...")
        from visualizer import create_performance_dashboard, create_detailed_analysis_charts

        dash_path = output_dir / "backtest_performance_dashboard.png"
        create_performance_dashboard(
            equity_curve, trades, config.initial_capital, str(dash_path)
        )

        # Additional charts
        extra = create_detailed_analysis_charts(equity_curve, trades, config.initial_capital, str(output_dir))
        for f in extra:
            if not args.quiet:
                print(f"  [OK] {f}")

    # ─── Save Trade Log ───
    if trades:
        trades_path = output_dir / "backtest_trades.csv"
        trades_df = pd.DataFrame([t.__dict__ for t in trades])
        trades_df.to_csv(trades_path, index=False)
        if not args.quiet:
            print(f"\nTrade log saved to {trades_path}")

    # ─── Save Equity Curve ───
    equity_path = output_dir / "backtest_equity_curve.csv"
    eq_df = pd.DataFrame(equity_curve)
    eq_df.to_csv(equity_path, index=False)
    if not args.quiet:
        print(f"Equity curve saved to {equity_path}")

    # ─── Save Summary JSON ───
    import json
    summary_path = output_dir / "backtest_summary.json"
    # Convert non-serializable objects
    serializable_results = {
        k: v for k, v in results.items()
        if k not in ('trades', 'equity_curve')
    }
    with open(summary_path, 'w') as f:
        json.dump(serializable_results, f, indent=2, default=str)
    if not args.quiet:
        print(f"Summary JSON saved to {summary_path}")

    if not args.quiet:
        print("\n" + "=" * 70)
        print("BACKTEST COMPLETE")
        print("=" * 70)

    return 0


def print_full_terminal_report(results: Dict, config: "BacktestConfig"):
    """Print the strictly formatted terminal summary table."""
    if not results:
        print("No results to display")
        return

    print("\n" + "=" * 70)
    print("      2-YEAR REALISTIC BACKTEST PERFORMANCE REPORT")
    print("=" * 70)

    # 1. Initial Capital & Final Capital
    print(f"1. Capital           : In ${results['initial_capital']:>12,.2f} / Out ${results['final_capital']:>12,.2f}")

    # 2. Gross P/L
    print(f"2. Gross P/L         : ${results['gross_pnl']:>14,.2f}")

    # 3. Net P/L ($ and %)
    net_pnl = results['net_pnl']
    roi_pct = results['roi_pct']
    print(f"3. Net P/L           : ${net_pnl:>14,.2f} ({roi_pct:+.2f}%)")

    # 4. Total Points Captured
    print(f"4. Total Points      : {results['total_points_captured']:>14,.2f} BTC Points")

    # 5. Total Trades Executed
    print(f"5. Total Trades      : {results['total_trades']:>14}")

    # 6. Win Rate (%) with Win/Loss counts
    win_rate = results['win_rate_pct']
    wins = results['wins']
    losses = results['losses']
    print(f"6. Win Rate          : {win_rate:>12.2f}% ({wins}W / {losses}L)")

    # 7. Average PnL per Trade
    print(f"7. Avg PnL / Trade   : ${results['avg_pnl_per_trade']:>14,.2f}")

    # 8. Maximum Drawdown ($ and %)
    print(f"8. Max Drawdown      : -${results['max_drawdown_usd']:>13,.2f} (-{results['max_drawdown_pct']:.2f}%)")

    # 9. Profit Factor
    pf = results['profit_factor']
    pf_str = f"{pf:.2f}" if pf != float('inf') else "∞"
    print(f"9. Profit Factor     : {pf_str:>14}")

    # 10. Total Fee Drag Breakdown
    print("-" * 70)
    print("10. TOTAL FEE DRAG BREAKDOWN")
    print(f"    Exchange Fees    : -${results['total_exchange_fees']:>13,.2f}")
    print(f"    18% GST (Tax)    : -${results['total_gst_paid']:>13,.2f}")
    funding = results['total_funding_accrual']
    funding_sign = "+" if funding >= 0 else ""
    print(f"    Funding Accrual  : {funding_sign}${funding:>13,.2f}")
    total_drag = results['total_fee_drag']
    print(f"    TOTAL DRAG       : -${total_drag:>13,.2f}")

    # 11. Monthly Breakdown Table
    print("\n" + "=" * 70)
    print("           MONTHLY PERFORMANCE BREAKDOWN")
    print("=" * 70)
    print(f"{'Month':<12} {'Trades':>7} {'W/L':>8} {'Net P/L':>14} {'Max DD %':>10}")
    print("-" * 70)

    # This would need the monthly data from equity curve
    # For now, print placeholder
    print("  (See dashboard for detailed monthly breakdown)")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    sys.exit(main())