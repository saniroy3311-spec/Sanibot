#!/usr/bin/env python3
"""
visualizer.py — Backtest Performance Dashboard
================================================
Generates a 3-panel performance visualization:
1. Portfolio Equity Curve ($ USD) with initial capital baseline
2. Underwater Drawdown Chart (% depth from peak)
3. Monthly Returns Bar Chart with percentage labels
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import FuncFormatter
from typing import List, Dict, Optional
import os


# Color palette (colorblind-safe, works in light/dark)
COLORS = {
    'equity': '#1f77b4',        # Blue
    'equity_bg': '#e8f0fe',     # Light blue fill
    'baseline': '#666666',      # Gray baseline
    'drawdown': '#d62728',      # Red
    'drawdown_bg': '#fde8e8',   # Light red fill
    'monthly_pos': '#2ca02c',   # Green
    'monthly_neg': '#d62728',   # Red
    'grid': '#dddddd',
    'text': '#333333',
    'text_secondary': '#666666',
}


def format_currency(x, pos):
    """Format y-axis as currency."""
    if x >= 1e6:
        return f'${x/1e6:.1f}M'
    elif x >= 1e3:
        return f'${x/1e3:.0f}K'
    return f'${x:,.0f}'


def format_pct(x, pos):
    """Format y-axis as percentage."""
    return f'{x:.1f}%'


def create_performance_dashboard(
    equity_curve: List[Dict],
    trades: List,
    initial_capital: float,
    output_path: str = "backtest_performance_dashboard.png",
    figsize: tuple = (16, 12),
    dpi: int = 150
) -> str:
    """
    Create 3-panel performance dashboard.

    Args:
        equity_curve: List of dicts with 'timestamp' and 'capital'
        trades: List of CompletedTrade objects
        initial_capital: Starting capital
        output_path: Output file path
        figsize: Figure size (width, height)
        dpi: Output DPI

    Returns:
        Path to saved figure
    """
    if not equity_curve:
        print("⚠️ No equity curve data to plot")
        return ""

    # Convert to DataFrames
    eq_df = pd.DataFrame(equity_curve)
    eq_df['timestamp'] = pd.to_datetime(eq_df['timestamp'])
    eq_df = eq_df.sort_values('timestamp').reset_index(drop=True)

    # Compute drawdown series
    eq_df['peak'] = eq_df['capital'].cummax()
    eq_df['drawdown_pct'] = (eq_df['peak'] - eq_df['capital']) / eq_df['peak'] * 100
    eq_df['drawdown_usd'] = eq_df['peak'] - eq_df['capital']

    # Monthly returns from trades
    if trades:
        trades_df = pd.DataFrame([t.__dict__ for t in trades])
        trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])
        trades_df['month'] = trades_df['exit_time'].dt.strftime('%Y-%m')

        monthly_pnl = trades_df.groupby('month')['net_pnl'].sum()
        monthly_pnl_pct = (monthly_pnl / initial_capital) * 100
        monthly_df = pd.DataFrame({
            'month': monthly_pnl.index.astype(str),
            'pnl': monthly_pnl.values,
            'pnl_pct': monthly_pnl_pct.values
        })
    else:
        monthly_df = pd.DataFrame(columns=['month', 'pnl', 'pnl_pct'])

    # ── Create figure ──
    fig = plt.figure(figsize=figsize, facecolor='white')
    gs = fig.add_gridspec(3, 1, height_ratios=[2.5, 1.5, 1.2], hspace=0.3)

    # ══════════════════════════════════════════════════════════════════
    # PANEL 1: EQUITY CURVE
    # ══════════════════════════════════════════════════════════════════
    ax1 = fig.add_subplot(gs[0, 0])
    ax1.set_facecolor('#fafafa')

    # Equity line
    ax1.plot(eq_df['timestamp'], eq_df['capital'],
             color=COLORS['equity'], linewidth=1.2, label='Portfolio Equity')

    # Fill under equity curve
    ax1.fill_between(eq_df['timestamp'],
                     initial_capital, eq_df['capital'],
                     where=(eq_df['capital'] >= initial_capital),
                     color=COLORS['equity_bg'], alpha=0.5)
    ax1.fill_between(eq_df['timestamp'],
                     initial_capital, eq_df['capital'],
                     where=(eq_df['capital'] < initial_capital),
                     color=COLORS['drawdown_bg'], alpha=0.5)

    # Initial capital baseline
    ax1.axhline(y=initial_capital, color=COLORS['baseline'],
                linestyle='--', linewidth=1, alpha=0.7, label='Initial Capital')

    # Final capital marker
    final_capital = eq_df['capital'].iloc[-1]
    final_date = eq_df['timestamp'].iloc[-1]
    ax1.plot(final_date, final_capital, 'o', color=COLORS['equity'],
             markersize=6, zorder=5)
    ax1.annotate(f'${final_capital:,.0f}',
                 xy=(final_date, final_capital),
                 xytext=(10, 10), textcoords='offset points',
                 fontsize=9, fontweight='bold', color=COLORS['equity'],
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=COLORS['equity']))

    ax1.set_ylabel('Portfolio Value ($)', fontsize=11, fontweight='bold', color=COLORS['text'])
    ax1.set_title('Portfolio Equity Curve', fontsize=13, fontweight='bold', color=COLORS['text'], pad=10)
    ax1.yaxis.set_major_formatter(FuncFormatter(format_currency))
    ax1.grid(True, color=COLORS['grid'], linestyle='-', linewidth=0.5, alpha=0.7)
    ax1.legend(loc='upper left', framealpha=0.9, fontsize=9)

    # Format x-axis
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=0, ha='center', fontsize=8)

    # Add key stats text box
    total_return = (final_capital - initial_capital) / initial_capital * 100
    stats_text = f"Total Return: {total_return:+.1f}%  |  Peak: ${eq_df['peak'].max():,.0f}"
    ax1.text(0.02, 0.95, stats_text, transform=ax1.transAxes,
             fontsize=9, verticalalignment='top',
             bbox=dict(boxstyle='round,pad=0.4', facecolor='white', edgecolor=COLORS['grid'], alpha=0.9))

    # ══════════════════════════════════════════════════════════════════
    # PANEL 2: UNDERWATER DRAWDOWN
    # ══════════════════════════════════════════════════════════════════
    ax2 = fig.add_subplot(gs[1, 0], sharex=ax1)
    ax2.set_facecolor('#fafafa')

    # Drawdown area fill
    ax2.fill_between(eq_df['timestamp'], 0, -eq_df['drawdown_pct'],
                     color=COLORS['drawdown_bg'], alpha=0.6)
    ax2.plot(eq_df['timestamp'], -eq_df['drawdown_pct'],
             color=COLORS['drawdown'], linewidth=1)

    # Zero line
    ax2.axhline(y=0, color=COLORS['baseline'], linewidth=0.8, alpha=0.5)

    # Max drawdown marker
    max_dd_idx = eq_df['drawdown_pct'].idxmax()
    max_dd_val = eq_df['drawdown_pct'].iloc[max_dd_idx]
    max_dd_date = eq_df['timestamp'].iloc[max_dd_idx]
    ax2.plot(max_dd_date, -max_dd_val, 'v', color=COLORS['drawdown'],
             markersize=8, zorder=5)
    ax2.annotate(f'Max DD: {max_dd_val:.1f}%',
                 xy=(max_dd_date, -max_dd_val),
                 xytext=(10, -15), textcoords='offset points',
                 fontsize=9, fontweight='bold', color=COLORS['drawdown'],
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor=COLORS['drawdown']))

    ax2.set_ylabel('Drawdown (%)', fontsize=11, fontweight='bold', color=COLORS['text'])
    ax2.set_title('Underwater Drawdown Chart', fontsize=13, fontweight='bold', color=COLORS['text'], pad=10)
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: f'{abs(x):.1f}%'))
    ax2.grid(True, color=COLORS['grid'], linestyle='-', linewidth=0.5, alpha=0.7)

    # Invert y-axis for underwater effect
    ax2.invert_yaxis()

    # ══════════════════════════════════════════════════════════════════
    # PANEL 3: MONTHLY RETURNS
    # ══════════════════════════════════════════════════════════════════
    ax3 = fig.add_subplot(gs[2, 0])
    ax3.set_facecolor('#fafafa')

    if not monthly_df.empty:
        x_pos = range(len(monthly_df))
        colors = [COLORS['monthly_pos'] if p >= 0 else COLORS['monthly_neg']
                  for p in monthly_df['pnl_pct']]

        bars = ax3.bar(x_pos, monthly_df['pnl_pct'], color=colors,
                       edgecolor='white', linewidth=0.5, width=0.7, alpha=0.85)

        # Add percentage labels on bars
        for i, (bar, pnl_pct, pnl_usd) in enumerate(zip(bars, monthly_df['pnl_pct'], monthly_df['pnl'])):
            height = bar.get_height()
            label_y = height + (0.2 if height >= 0 else -0.5)
            ax3.text(bar.get_x() + bar.get_width()/2., label_y,
                     f'{pnl_pct:+.1f}%', ha='center', va='bottom' if height >= 0 else 'top',
                     fontsize=8, fontweight='bold', color=COLORS['text'])

        ax3.set_xticks(x_pos)
        ax3.set_xticklabels(monthly_df['month'], rotation=45, ha='right', fontsize=8)
    else:
        ax3.text(0.5, 0.5, 'No trades executed', transform=ax3.transAxes,
                 ha='center', va='center', fontsize=12, color=COLORS['text_secondary'])

    ax3.axhline(y=0, color=COLORS['baseline'], linewidth=0.8)
    ax3.set_ylabel('Return (%)', fontsize=11, fontweight='bold', color=COLORS['text'])
    ax3.set_title('Monthly Returns', fontsize=13, fontweight='bold', color=COLORS['text'], pad=10)
    ax3.yaxis.set_major_formatter(FuncFormatter(format_pct))
    ax3.grid(True, color=COLORS['grid'], linestyle='-', linewidth=0.5, alpha=0.5, axis='y')

    # Summary stats at bottom
    if trades:
        win_trades = [t for t in trades if t.net_pnl > 0]
        loss_trades = [t for t in trades if t.net_pnl <= 0]
        win_rate = len(win_trades) / len(trades) * 100 if trades else 0
        avg_win = np.mean([t.net_pnl for t in win_trades]) if win_trades else 0
        avg_loss = np.mean([t.net_pnl for t in loss_trades]) if loss_trades else 0

        summary = (f"Trades: {len(trades)}  |  Win Rate: {win_rate:.1f}%  |  "
                   f"Avg Win: ${avg_win:,.0f}  |  Avg Loss: ${avg_loss:,.0f}")
        fig.text(0.5, 0.01, summary, ha='center', fontsize=9,
                 color=COLORS['text_secondary'])

    # Overall title
    fig.suptitle('2-Year Realistic Backtest Performance Dashboard',
                 fontsize=16, fontweight='bold', color=COLORS['text'], y=0.98)

    # Save
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    print(f"[OK] Dashboard saved to {output_path}")
    return output_path


def create_detailed_analysis_charts(
    equity_curve: List[Dict],
    trades: List,
    initial_capital: float,
    output_dir: str = "."
) -> List[str]:
    """Create additional analysis charts for deeper inspection."""
    if not trades:
        return []

    trades_df = pd.DataFrame([t.__dict__ for t in trades])
    trades_df['exit_time'] = pd.to_datetime(trades_df['exit_time'])
    trades_df['entry_time'] = pd.to_datetime(trades_df['entry_time'])

    saved_files = []

    # 1. Trade PnL Distribution
    fig, ax = plt.subplots(figsize=(10, 6))
    pnls = trades_df['net_pnl']
    ax.hist(pnls, bins=30, color=COLORS['equity'], alpha=0.7, edgecolor='white')
    ax.axvline(x=0, color=COLORS['baseline'], linestyle='--', linewidth=1)
    ax.axvline(x=pnls.mean(), color=COLORS['equity'], linestyle='--', linewidth=1.5,
               label=f'Mean: ${pnls.mean():,.0f}')
    ax.set_xlabel('Net PnL ($)', fontsize=11)
    ax.set_ylabel('Frequency', fontsize=11)
    ax.set_title('Trade PnL Distribution', fontsize=13, fontweight='bold')
    ax.legend()
    ax.grid(True, alpha=0.3)
    path = os.path.join(output_dir, "trade_pnl_distribution.png")
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    saved_files.append(path)

    # 2. Exit Reason Breakdown
    fig, ax = plt.subplots(figsize=(10, 6))
    exit_counts = trades_df['exit_reason'].value_counts()
    colors = [COLORS['monthly_neg'] if 'SL' in r or 'Max' in r else COLORS['monthly_pos']
              for r in exit_counts.index]
    bars = ax.barh(range(len(exit_counts)), exit_counts.values, color=colors, edgecolor='white')
    ax.set_yticks(range(len(exit_counts)))
    ax.set_yticklabels(exit_counts.index, fontsize=10)
    ax.set_xlabel('Number of Trades', fontsize=11)
    ax.set_title('Exit Reason Distribution', fontsize=13, fontweight='bold')
    for i, (bar, cnt) in enumerate(zip(bars, exit_counts.values)):
        ax.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2,
                str(cnt), va='center', fontsize=9)
    ax.grid(True, alpha=0.3, axis='x')
    path = os.path.join(output_dir, "exit_reason_breakdown.png")
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    saved_files.append(path)

    # 3. Cumulative PnL by Trade
    fig, ax = plt.subplots(figsize=(12, 6))
    cum_pnl = trades_df['net_pnl'].cumsum()
    ax.plot(range(1, len(cum_pnl) + 1), cum_pnl, color=COLORS['equity'], linewidth=1.5)
    ax.fill_between(range(1, len(cum_pnl) + 1), 0, cum_pnl,
                    where=(cum_pnl >= 0), color=COLORS['equity_bg'], alpha=0.5)
    ax.fill_between(range(1, len(cum_pnl) + 1), 0, cum_pnl,
                    where=(cum_pnl < 0), color=COLORS['drawdown_bg'], alpha=0.5)
    ax.axhline(y=0, color=COLORS['baseline'], linestyle='--', linewidth=0.8)
    ax.set_xlabel('Trade Number', fontsize=11)
    ax.set_ylabel('Cumulative PnL ($)', fontsize=11)
    ax.set_title('Cumulative PnL by Trade Sequence', fontsize=13, fontweight='bold')
    ax.yaxis.set_major_formatter(FuncFormatter(format_currency))
    ax.grid(True, alpha=0.3)
    path = os.path.join(output_dir, "cumulative_pnl.png")
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    saved_files.append(path)

    # 4. Holding Period Distribution
    fig, ax = plt.subplots(figsize=(10, 6))
    trades_df['holding_hours'] = (trades_df['exit_time'] - trades_df['entry_time']).dt.total_seconds() / 3600
    ax.hist(trades_df['holding_hours'], bins=30, color=COLORS['equity'], alpha=0.7, edgecolor='white')
    ax.set_xlabel('Holding Period (hours)', fontsize=11)
    ax.set_ylabel('Frequency', fontsize=11)
    ax.set_title('Trade Holding Period Distribution', fontsize=13, fontweight='bold')
    ax.grid(True, alpha=0.3)
    path = os.path.join(output_dir, "holding_period_distribution.png")
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    saved_files.append(path)

    return saved_files


def main():
    """Quick test with synthetic data."""
    print("Testing visualizer with synthetic data...")

    # Generate synthetic equity curve
    dates = pd.date_range(start="2024-08-01", end="2026-08-01", freq="D")
    np.random.seed(42)
    returns = np.random.normal(0.0001, 0.01, len(dates))
    equity = 50000 * (1 + returns).cumprod()

    equity_curve = [{'timestamp': d, 'capital': e} for d, e in zip(dates, equity)]

    # Generate synthetic trades
    class MockTrade:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    mock_trades = []
    for i in range(50):
        entry = dates[i*15]
        exit = entry + pd.Timedelta(days=np.random.randint(1, 30))
        pnl = np.random.normal(100, 500)
        mock_trades.append(MockTrade(
            net_pnl=pnl,
            exit_time=exit,
            entry_time=entry,
            exit_reason=np.random.choice(['SL', 'Trail_SL_Stage2', 'TP', 'Max_SL', 'BE']),
            direction=np.random.choice(['LONG', 'SHORT']),
        ))

    create_performance_dashboard(equity_curve, mock_trades, 50000,
                                 "test_dashboard.png")
    create_detailed_analysis_charts(equity_curve, mock_trades, 50000)

    print("Test complete!")


if __name__ == "__main__":
    main()