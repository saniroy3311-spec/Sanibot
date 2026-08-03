#!/usr/bin/env python3
"""
realistic_backtester.py — Realistic Event-Driven Backtest Engine
===================================================================
Core engine for 2-year realistic backtesting with:
- Micro-tick generation via Brownian Bridge (intra-bar simulation)
- 5-tick Stop Loss confirmation (no single-wick stop-outs)
- Intra-bar trailing stop evaluation on micro-tick stream
- Realistic fees: 0.05% taker entry, 0.02% maker exit + 18% GST on fees
- Funding rate accrual every 8 hours (00:00, 08:00, 16:00 UTC)
- 0.1 BTC position size = 100 Delta lots
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
import math


# ═══════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════
@dataclass
class BacktestConfig:
    """All backtest parameters in one place."""
    # Position Sizing
    symbol: str = "BTCUSDT"
    initial_capital: float = 50000.0          # $50,000 USD
    position_btc_size: float = 0.1            # 0.1 BTC per position
    lot_size_multiplier: int = 1000           # 1 contract = 0.001 BTC

    # Fees & Taxation
    taker_fee_pct: float = 0.0005             # 0.05% taker fee (entry)
    maker_fee_pct: float = 0.0002             # 0.02% maker fee (exit limit)
    gst_pct: float = 0.18                     # 18% GST on fees (Delta India)
    slippage_pct: float = 0.0001              # 0.01% slippage on market orders

    # Stop Loss Confirmation
    sl_confirm_ticks: int = 5                 # Consecutive ticks below/above SL
    trail_confirm_ticks: int = 2              # Post-arm trail confirmation

    # Trailing Loop
    trail_loop_interval_sec: float = 0.1      # 100ms intra-bar evaluation

    # Funding Rates (8-hour intervals: 00:00, 08:00, 16:00 UTC)
    default_funding_rate: float = 0.0001      # 0.01% per 8h fallback
    funding_interval_hours: int = 8

    # Micro-tick Generation
    ticks_per_bar: int = 20  # OPTIMIZED FOR SPEED                  # 30m bar → 120 ticks (15s each)
    brownian_noise_scale: float = 0.02        # Noise as fraction of bar range

    # Pine Script Parity Parameters (from config.py)
    TRAIL_STAGES: List[Tuple[float, float, float]] = field(default_factory=lambda: [
        (0.8,  0.50, 0.40),   # Stage 1
        (1.5,  0.40, 0.30),   # Stage 2
        (2.5,  0.30, 0.25),   # Stage 3
        (4.0,  0.20, 0.15),   # Stage 4
        (6.0,  0.15, 0.10),   # Stage 5
    ])
    PINE_MINTICK: float = 0.5
    BE_MULT: float = 0.6
    MAX_SL_MULT: float = 1.5
    MAX_SL_POINTS: float = 500.0
    TREND_RR: float = 4.0
    RANGE_RR: float = 2.5
    TREND_ATR_MULT: float = 0.6
    RANGE_ATR_MULT: float = 0.5
    ADX_TREND_TH: float = 22.0
    ADX_RANGE_TH: float = 18.0
    FILTER_ATR_MULT: float = 1.4
    FILTER_VOL_MULT: float = 1.0
    BREAKOUT_BUFFER_PTS: float = 0.0

    # Optimization Parameters (from config.py)
    OPT_ADX_TREND_TH: float = 22.0
    OPT_ADX_RANGE_TH: float = 18.0
    OPT_ADX_MIN_FILTER: float = 15.0
    OPT_HTF_TREND_ENABLED: bool = True
    OPT_HTF_EMA_LEN: int = 200
    OPT_HTF_TIMEFRAME: str = "4h"
    OPT_EMA_FAST_LEN: int = 50
    OPT_EMA_SLOW_LEN: int = 200
    OPT_ATR_MIN_FILTER: float = 0.0
    OPT_ATR_MIN_PCT: float = 0.0
    OPT_INITIAL_SL_PCT: float = 0.0
    OPT_TRAIL_TRIGGER_1_PCT: float = 0.0
    OPT_TRAIL_TRIGGER_2_PCT: float = 0.0

    def update_from_config_module(self):
        """Update optimization parameters from config.py module."""
        from config import (
            OPT_ADX_TREND_TH, OPT_ADX_RANGE_TH, OPT_ADX_MIN_FILTER,
            OPT_HTF_TREND_ENABLED, OPT_HTF_EMA_LEN, OPT_HTF_TIMEFRAME,
            OPT_EMA_FAST_LEN, OPT_EMA_SLOW_LEN,
            OPT_ATR_MIN_FILTER, OPT_ATR_MIN_PCT,
            OPT_INITIAL_SL_PCT,
            OPT_TRAIL_TRIGGER_1_PCT, OPT_TRAIL_TRIGGER_2_PCT,
            ADX_TREND_TH, ADX_RANGE_TH,
            FILTER_ATR_MULT, FILTER_VOL_MULT,
            TREND_RR, RANGE_RR, TREND_ATR_MULT, RANGE_ATR_MULT,
            MAX_SL_MULT, MAX_SL_POINTS,
            BREAKOUT_BUFFER_PTS,
        )
        self.OPT_ADX_TREND_TH = OPT_ADX_TREND_TH
        self.OPT_ADX_RANGE_TH = OPT_ADX_RANGE_TH
        self.OPT_ADX_MIN_FILTER = OPT_ADX_MIN_FILTER
        self.OPT_HTF_TREND_ENABLED = OPT_HTF_TREND_ENABLED
        self.OPT_HTF_EMA_LEN = OPT_HTF_EMA_LEN
        self.OPT_HTF_TIMEFRAME = OPT_HTF_TIMEFRAME
        self.OPT_EMA_FAST_LEN = OPT_EMA_FAST_LEN
        self.OPT_EMA_SLOW_LEN = OPT_EMA_SLOW_LEN
        self.OPT_ATR_MIN_FILTER = OPT_ATR_MIN_FILTER
        self.OPT_ATR_MIN_PCT = OPT_ATR_MIN_PCT
        self.OPT_INITIAL_SL_PCT = OPT_INITIAL_SL_PCT
        self.OPT_TRAIL_TRIGGER_1_PCT = OPT_TRAIL_TRIGGER_1_PCT
        self.OPT_TRAIL_TRIGGER_2_PCT = OPT_TRAIL_TRIGGER_2_PCT
        # Also sync base params
        self.ADX_TREND_TH = ADX_TREND_TH
        self.ADX_RANGE_TH = ADX_RANGE_TH
        self.FILTER_ATR_MULT = FILTER_ATR_MULT
        self.FILTER_VOL_MULT = FILTER_VOL_MULT
        self.TREND_RR = TREND_RR
        self.RANGE_RR = RANGE_RR
        self.TREND_ATR_MULT = TREND_ATR_MULT
        self.RANGE_ATR_MULT = RANGE_ATR_MULT
        self.MAX_SL_MULT = MAX_SL_MULT
        self.MAX_SL_POINTS = MAX_SL_POINTS
        self.BREAKOUT_BUFFER_PTS = BREAKOUT_BUFFER_PTS


# ═══════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════
@dataclass
class Tick:
    """Single micro-tick in the synthetic stream."""
    timestamp: pd.Timestamp
    price: float        # Mid price
    bid: float          # Bid price
    ask: float          # Ask price
    volume: float       # Volume per tick


@dataclass
class Position:
    """Active position state."""
    direction: str                # 'LONG' or 'SHORT'
    entry_price: float            # Filled entry price (with slippage)
    size_btc: float               # 0.1 BTC
    lots: int                     # 100 lots
    sl_price: float               # Current stop loss price
    initial_sl: float             # Initial SL at entry
    entry_fee: float              # Taker fee paid on entry
    entry_gst: float              # GST on entry fee
    trail_stage: int = 0          # Current trail stage (0-5)
    peak_price: float = 0.0       # Highest (long) / lowest (short) since entry
    entry_time: Optional[pd.Timestamp] = None
    entry_bar_idx: int = -1       # Bar index at entry
    is_trend: bool = False        # Trend vs range trade


@dataclass
class CompletedTrade:
    """Finalized trade record."""
    trade_id: int
    direction: str
    is_trend: bool
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    size_btc: float
    lots: int
    gross_pnl: float              # Raw PnL before fees
    net_pnl: float                # After all fees, GST, funding
    points_captured: float        # Price points (exit - entry for long)
    exit_reason: str              # SL, Trail SL, Max SL, TP, Time, BE
    trail_stage_at_exit: int
    bars_held: int
    entry_fee: float
    entry_gst: float
    exit_fee: float
    exit_gst: float
    funding_paid: float           # Net funding (negative = paid)


@dataclass
class BarIndicators:
    """Pre-computed indicators for a single bar."""
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    ema_fast: float
    ema_trend: float
    atr: float
    atr_sma: float
    rsi: float
    dip: float
    dim: float
    adx: float
    adx_raw: float
    vol_sma: float
    prev_high: float
    prev_low: float
    htf_trend_up: float = 1.0
    htf_trend_down: float = 1.0


# ═══════════════════════════════════════════════════════════════════════
# MICRO-TICK GENERATOR (Brownian Bridge)
# ═══════════════════════════════════════════════════════════════════════
class MicroTickGenerator:
    """
    Generates realistic high-frequency tick streams from 30m OHLCV bars.
    Uses Brownian Bridge noise to simulate intrabar price movements
    while preserving the OHLC boundaries.
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.tick_spread = 0.5  # Typical BTCUSDT bid-ask spread ($0.50)

    def generate_ticks_for_bar(self, bar: BarIndicators) -> List[Tick]:
        """
        Decompose a 30m bar into synthetic micro-ticks using Brownian Bridge.

        The path goes: open → low → high → close (or open → high → low → close)
        with Brownian noise injected at each step to simulate realistic tick movement.
        """
        n_ticks = self.config.ticks_per_bar
        open_p, high_p, low_p, close_p = bar.open, bar.high, bar.low, bar.close
        bar_range = high_p - low_p

        # Determine the path based on candle direction
        if close_p >= open_p:
            # Bullish candle: open → low → high → close
            path_segments = [(open_p, low_p), (low_p, high_p), (high_p, close_p)]
        else:
            # Bearish candle: open → high → low → close
            path_segments = [(open_p, high_p), (high_p, low_p), (low_p, close_p)]

        ticks_per_seg = n_ticks // 3
        remainder = n_ticks % 3

        all_prices = []
        for i, (p_start, p_end) in enumerate(path_segments):
            seg_ticks = ticks_per_seg + (1 if i < remainder else 0)
            if seg_ticks <= 0:
                continue

            # Linear interpolation
            base_prices = np.linspace(p_start, p_end, seg_ticks)

            # Brownian Bridge noise: variance peaks in middle of segment
            t = np.linspace(0, 1, seg_ticks)
            # Bridge variance: t*(1-t) peaks at 0.25 at t=0.5
            bridge_var = t * (1 - t) * 4  # Max 1.0 at t=0.5
            noise_scale = bar_range * self.config.brownian_noise_scale
            noise = np.random.normal(0, noise_scale, seg_ticks) * np.sqrt(bridge_var)

            # Apply noise and clip to bar boundaries
            seg_prices = base_prices + noise
            seg_prices = np.clip(seg_prices, low_p, high_p)
            all_prices.extend(seg_prices)

        # Generate timestamps (15-second intervals for 30m bar)
        start_ts = bar.timestamp
        tick_interval_sec = 1800 // len(all_prices)
        timestamps = pd.date_range(
            start=start_ts,
            periods=len(all_prices),
            freq=f'{tick_interval_sec}s'  # seconds
        )

        # Convert to Tick objects with bid/ask spread
        tick_list = []
        for ts, p in zip(timestamps, all_prices):
            tick_list.append(Tick(
                timestamp=ts,
                price=float(p),
                bid=float(p - self.tick_spread / 2),
                ask=float(p + self.tick_spread / 2),
                volume=bar.volume / len(all_prices)
            ))

        return tick_list


# ═══════════════════════════════════════════════════════════════════════
# INDICATOR CALCULATOR (Reuses strategy_logic)
# ═══════════════════════════════════════════════════════════════════════
class IndicatorCalculator:
    """Computes all indicators needed for signal generation using strategy_logic."""

    def __init__(self, config: BacktestConfig):
        self.config = config

    def compute_full_series(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute full indicator series - delegates to strategy_logic."""
        from strategy_logic import compute_full_series
        return compute_full_series(df)

    def row_to_indicators(self, row, prev_row) -> BarIndicators:
        """Convert a series row to BarIndicators object."""
        return BarIndicators(
            timestamp=pd.Timestamp(row["timestamp"], unit="ms", tz="UTC"),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            ema_fast=float(row["ema_fast"]),
            ema_trend=float(row["ema_trend"]),
            atr=float(row["atr"]),
            atr_sma=float(row["atr_sma"]),
            rsi=float(row["rsi"]),
            dip=float(row["dip"]),
            dim=float(row["dim"]),
            adx=float(row["adx"]),
            adx_raw=float(row["adx_raw"]),
            vol_sma=float(row["vol_sma"]),
            prev_high=float(prev_row["high"]),
            prev_low=float(prev_row["low"]),
            htf_trend_up=float(row.get("htf_trend_up", 1.0)),
            htf_trend_down=float(row.get("htf_trend_down", 1.0)),
        )

    def evaluate_entry_signal(self, ind: BarIndicators, has_position: bool) -> Tuple[bool, bool, str]:
        """
        Evaluate entry signal based on indicators.
        Delegates to strategy_logic for consistency.
        """
        from strategy_logic import evaluate_entry, SignalType
        from dataclasses import dataclass

        # Convert BarIndicators to IndicatorSnapshot for strategy_logic
        @dataclass
        class IndicatorSnapshot:
            ema_trend: float
            ema_fast: float
            atr: float
            rsi: float
            dip: float
            dim: float
            adx: float
            adx_raw: float
            vol_sma: float
            atr_sma: float
            trend_regime: bool
            range_regime: bool
            filters_ok: bool
            atr_ok: bool
            vol_ok: bool
            body_ok: bool
            atr_min_ok: bool
            adx_min_ok: bool
            htf_trend_up: float
            htf_trend_down: float
            open: float
            high: float
            low: float
            close: float
            volume: float
            prev_high: float
            prev_low: float
            timestamp: int

        # Compute filters
        atr_ok = ind.atr < ind.atr_sma * self.config.FILTER_ATR_MULT
        body_ok = True
        vol_ok = ind.volume > 0 and ind.vol_sma > 0 and ind.volume > ind.vol_sma * self.config.FILTER_VOL_MULT

        # ATR minimum filter
        atr_min_ok = True
        if hasattr(self.config, 'OPT_ATR_MIN_FILTER') and self.config.OPT_ATR_MIN_FILTER > 0:
            atr_min_ok = ind.atr >= self.config.OPT_ATR_MIN_FILTER
        if hasattr(self.config, 'OPT_ATR_MIN_PCT') and self.config.OPT_ATR_MIN_PCT > 0:
            atr_min_ok = atr_min_ok and (ind.atr / ind.close >= self.config.OPT_ATR_MIN_PCT)

        filters_ok = atr_ok and vol_ok and body_ok and atr_min_ok

        adx_v = ind.adx
        trend_regime = adx_v > self.config.ADX_TREND_TH
        range_regime = adx_v < self.config.ADX_RANGE_TH

        adx_min_ok = adx_v >= getattr(self.config, 'OPT_ADX_MIN_FILTER', 0)

        snap = IndicatorSnapshot(
            ema_trend=ind.ema_trend,
            ema_fast=ind.ema_fast,
            atr=ind.atr,
            rsi=ind.rsi,
            dip=ind.dip,
            dim=ind.dim,
            adx=ind.adx,
            adx_raw=ind.adx_raw,
            vol_sma=ind.vol_sma,
            atr_sma=ind.atr_sma,
            trend_regime=trend_regime,
            range_regime=range_regime,
            filters_ok=filters_ok,
            atr_ok=atr_ok,
            vol_ok=vol_ok,
            body_ok=body_ok,
            atr_min_ok=atr_min_ok,
            adx_min_ok=adx_min_ok,
            htf_trend_up=ind.htf_trend_up,
            htf_trend_down=ind.htf_trend_down,
            open=ind.open,
            high=ind.high,
            low=ind.low,
            close=ind.close,
            volume=ind.volume,
            prev_high=ind.prev_high,
            prev_low=ind.prev_low,
            timestamp=int(ind.timestamp.timestamp() * 1000),
        )

        sig = evaluate_entry(snap, has_position)
        if sig.signal_type == SignalType.NONE:
            return False, False, "none"
        is_long = sig.is_long
        regime = sig.regime
        return True, is_long, regime

    def calc_initial_levels(self, entry_price: float, atr: float, is_long: bool, is_trend: bool) -> Tuple[float, float, float]:
        """Calculate initial SL, TP, and stop distance."""
        from strategy_logic import calc_levels
        from config import TREND_RR, RANGE_RR, TREND_ATR_MULT, RANGE_ATR_MULT, MAX_SL_POINTS, OPT_INITIAL_SL_PCT

        rr = TREND_RR if is_trend else RANGE_RR
        atr_mult = TREND_ATR_MULT if is_trend else RANGE_ATR_MULT
        stop_dist = min(atr * atr_mult, MAX_SL_POINTS)

        # Optimization: Use fixed % SL if configured
        if OPT_INITIAL_SL_PCT > 0:
            stop_dist = entry_price * OPT_INITIAL_SL_PCT

        if is_long:
            sl = entry_price - stop_dist
            tp = entry_price + stop_dist * rr
        else:
            sl = entry_price + stop_dist
            tp = entry_price - stop_dist * rr

        return sl, tp, stop_dist


# ═══════════════════════════════════════════════════════════════════════
# REALISTIC BACKTESTER ENGINE
# ═══════════════════════════════════════════════════════════════════════
class RealisticBacktester:
    """
    Event-driven backtester with:
    - Micro-tick level simulation
    - 5-tick SL confirmation
    - Dynamic trailing on synthetic ticks
    - Realistic fees, GST, funding, slippage
    """

    def __init__(self, config: BacktestConfig, funding_df: pd.DataFrame = None):
        self.config = config
        self.funding_df = funding_df

        # State
        self.capital = config.initial_capital
        self.position: Optional[Position] = None
        self.sl_tick_counter: int = 0
        self.trades: List[CompletedTrade] = []
        self.equity_curve: List[Dict] = []

        # Global aggregators for reporting
        self.total_gross_pnl: float = 0.0
        self.total_points_captured: float = 0.0
        self.total_exchange_fees: float = 0.0
        self.total_gst_paid: float = 0.0
        self.total_funding_accrual: float = 0.0
        self.peak_capital: float = config.initial_capital
        self.max_drawdown_usd: float = 0.0
        self.max_drawdown_pct: float = 0.0

        # Components
        self.tick_generator = MicroTickGenerator(config)
        self.indicator_calc = IndicatorCalculator(config)

        # Pre-built funding rate lookup
        self.funding_lookup = self._build_funding_lookup() if funding_df is not None else {}

        self.trade_id_counter = 0

    def btc_to_lots(self, btc_amount: float) -> int:
        """Convert BTC to Delta Exchange lots."""
        return int(btc_amount * self.config.lot_size_multiplier)

    def _build_funding_lookup(self) -> Dict[int, float]:
        """Build timestamp → funding_rate lookup for O(1) access."""
        lookup = {}
        for _, row in self.funding_df.iterrows():
            ts = int(row["timestamp"])
            lookup[ts] = float(row["funding_rate"])
        return lookup

    def get_funding_rate(self, timestamp: pd.Timestamp) -> float:
        """Get funding rate for a specific timestamp (8-hour intervals)."""
        # Round to nearest 8-hour boundary
        ts_sec = int(timestamp.timestamp())
        interval_sec = self.config.funding_interval_hours * 3600
        bucket = (ts_sec // interval_sec) * interval_sec

        if bucket in self.funding_lookup:
            return self.funding_lookup[bucket]
        return self.config.default_funding_rate

    def process_funding(self, timestamp: pd.Timestamp):
        """Apply funding rate charge/credit if at funding interval boundary."""
        if self.position is None:
            return

        # Check if we're at a funding timestamp (00:00, 08:00, 16:00 UTC)
        if timestamp.hour % self.config.funding_interval_hours == 0 and timestamp.minute == 0:
            # Avoid double-processing within same interval
            funding_ts = int(timestamp.timestamp())
            interval_sec = self.config.funding_interval_hours * 3600
            bucket = (funding_ts // interval_sec) * interval_sec

            # Track last processed funding bucket
            if not hasattr(self, '_last_funding_bucket'):
                self._last_funding_bucket = -1

            if bucket != self._last_funding_bucket:
                self._last_funding_bucket = bucket

                rate = self.get_funding_rate(timestamp)
                notional = self.position.size_btc * self.position.entry_price
                funding_amt = notional * rate

                if self.position.direction == 'LONG':
                    self.capital -= funding_amt
                    self.total_funding_accrual -= funding_amt
                    funding_paid = funding_amt
                else:
                    self.capital += funding_amt
                    self.total_funding_accrual += funding_amt
                    funding_paid = -funding_amt

                # Record funding in current trade (will be picked up at exit)
                if self.position:
                    self.position.funding_paid = getattr(self.position, 'funding_paid', 0) + funding_paid

    def execute_entry(self, direction: str, tick: Tick, initial_sl: float, is_trend: bool, bar_idx: int):
        """Execute position entry with realistic slippage and fees."""
        if self.position is not None:
            return

        # Fill price with slippage
        if direction == 'LONG':
            fill_price = tick.ask * (1 + self.config.slippage_pct)
        else:
            fill_price = tick.bid * (1 - self.config.slippage_pct)

        size_btc = self.config.position_btc_size
        lots = self.btc_to_lots(size_btc)

        # Calculate fees
        notional = size_btc * fill_price
        entry_fee = notional * self.config.taker_fee_pct
        entry_gst = entry_fee * self.config.gst_pct

        # Deduct from capital
        self.capital -= (entry_fee + entry_gst)
        self.total_exchange_fees += entry_fee
        self.total_gst_paid += entry_gst

        self.trade_id_counter += 1

        self.position = Position(
            direction=direction,
            entry_price=fill_price,
            size_btc=size_btc,
            lots=lots,
            sl_price=initial_sl,
            initial_sl=initial_sl,
            entry_fee=entry_fee,
            entry_gst=entry_gst,
            entry_time=tick.timestamp,
            entry_bar_idx=bar_idx,
            is_trend=is_trend,
            peak_price=fill_price,
        )
        self.sl_tick_counter = 0

    def check_sl_and_trailing(self, tick: Tick, atr: float):
        """Evaluate SL and trailing stops on micro-tick stream."""
        if self.position is None:
            return

        pos = self.position
        price = tick.bid if pos.direction == 'LONG' else tick.ask

        # Update peak price
        if pos.direction == 'LONG':
            pos.peak_price = max(pos.peak_price, price)
            profit_dist = price - pos.entry_price
        else:
            pos.peak_price = min(pos.peak_price, price)
            profit_dist = pos.entry_price - price

        # Breakeven trigger
        if pos.trail_stage == 0 and profit_dist > atr * self.config.BE_MULT:
            # Move SL to breakeven
            pos.sl_price = max(pos.sl_price, pos.entry_price) if pos.direction == 'LONG' else min(pos.sl_price, pos.entry_price)

        # Trail stage upgrade
        new_stage = self._calculate_trail_stage(profit_dist, atr)
        if new_stage > pos.trail_stage:
            pos.trail_stage = new_stage
            # Tighten SL to trail level
            trail_sl = self._compute_trail_sl(pos.trail_stage, pos.peak_price, profit_dist, pos.direction, atr)
            if trail_sl is not None:
                if pos.direction == 'LONG':
                    pos.sl_price = max(pos.sl_price, trail_sl)
                else:
                    pos.sl_price = min(pos.sl_price, trail_sl)

        # Check SL breach with confirmation ticks
        sl_hit = False
        if pos.direction == 'LONG':
            if price <= pos.sl_price:
                self.sl_tick_counter += 1
            else:
                self.sl_tick_counter = 0
            if self.sl_tick_counter >= self.config.sl_confirm_ticks:
                sl_hit = True
        else:
            if price >= pos.sl_price:
                self.sl_tick_counter += 1
            else:
                self.sl_tick_counter = 0
            if self.sl_tick_counter >= self.config.sl_confirm_ticks:
                sl_hit = True

        if sl_hit:
            reason = "SL" if pos.trail_stage == 0 else f"Trail_SL_Stage{pos.trail_stage}"
            self.execute_exit(tick, reason, atr)

    def _calculate_trail_stage(self, profit_dist: float, atr: float) -> int:
        """Determine trail stage based on profit distance."""
        stage = 0
        for i, (trigger_mult, _, _) in enumerate(self.config.TRAIL_STAGES):
            if profit_dist >= atr * trigger_mult:
                stage = i + 1
            else:
                break
        return stage

    def _compute_trail_sl(self, stage: int, peak_price: float, profit_dist: float,
                          direction: str, atr: float) -> Optional[float]:
        """
        Compute trail SL price using Pine Script exact logic.
        trail_points and trail_offset are in TICKS (multiplied by mintick).
        """
        if stage == 0:
            return None

        idx = stage - 1
        _, pts_mult, off_mult = self.config.TRAIL_STAGES[idx]

        # Pine: activation = atr * pts_mult * mintick
        activation = atr * pts_mult * self.config.PINE_MINTICK
        if profit_dist < activation:
            return None

        # Pine: offset = atr * off_mult * mintick
        offset = atr * off_mult * self.config.PINE_MINTICK

        if direction == 'LONG':
            return peak_price - offset
        else:
            return peak_price + offset

    def check_max_sl(self, tick: Tick, atr: float) -> bool:
        """Check if max SL (catastrophe stop) is hit."""
        if self.position is None:
            return False

        pos = self.position
        price = tick.bid if pos.direction == 'LONG' else tick.ask
        threshold = min(atr * self.config.MAX_SL_MULT, self.config.MAX_SL_POINTS)

        if pos.direction == 'LONG':
            max_sl_price = pos.entry_price - threshold
            if price <= max_sl_price:
                self.execute_exit(tick, "Max_SL", atr)
                return True
        else:
            max_sl_price = pos.entry_price + threshold
            if price >= max_sl_price:
                self.execute_exit(tick, "Max_SL", atr)
                return True
        return False

    def execute_exit(self, tick: Tick, reason: str, atr: float):
        """Execute position exit with realistic fees."""
        pos = self.position
        if pos is None:
            return

        # Fill price
        if pos.direction == 'LONG':
            fill_price = tick.bid  # Exit at bid (maker)
        else:
            fill_price = tick.ask  # Exit at ask (maker)

        # PnL calculations
        if pos.direction == 'LONG':
            points_captured = fill_price - pos.entry_price
            gross_pnl = points_captured * pos.size_btc
        else:
            points_captured = pos.entry_price - fill_price
            gross_pnl = points_captured * pos.size_btc

        self.total_points_captured += points_captured
        self.total_gross_pnl += gross_pnl

        # Exit fees (maker)
        notional = pos.size_btc * fill_price
        exit_fee = notional * self.config.maker_fee_pct
        exit_gst = exit_fee * self.config.gst_pct

        self.total_exchange_fees += exit_fee
        self.total_gst_paid += exit_gst

        # Net PnL
        funding_paid = getattr(pos, 'funding_paid', 0.0)
        net_pnl = gross_pnl - (pos.entry_fee + pos.entry_gst + exit_fee + exit_gst + funding_paid)

        # Update capital
        self.capital += net_pnl

        # Track drawdown
        if self.capital > self.peak_capital:
            self.peak_capital = self.capital
        dd_usd = self.peak_capital - self.capital
        dd_pct = (dd_usd / self.peak_capital) * 100 if self.peak_capital > 0 else 0
        if dd_usd > self.max_drawdown_usd:
            self.max_drawdown_usd = dd_usd
        if dd_pct > self.max_drawdown_pct:
            self.max_drawdown_pct = dd_pct

        # Record trade
        self.trades.append(CompletedTrade(
            trade_id=self.trade_id_counter,
            direction=pos.direction,
            is_trend=pos.is_trend,
            entry_time=pos.entry_time,
            exit_time=tick.timestamp,
            entry_price=pos.entry_price,
            exit_price=fill_price,
            size_btc=pos.size_btc,
            lots=pos.lots,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            points_captured=points_captured,
            exit_reason=reason,
            trail_stage_at_exit=pos.trail_stage,
            bars_held=0,  # Will be filled by caller
            entry_fee=pos.entry_fee,
            entry_gst=pos.entry_gst,
            exit_fee=exit_fee,
            exit_gst=exit_gst,
            funding_paid=funding_paid,
        ))

        self.position = None
        self.sl_tick_counter = 0

    def run(self, ohlcv_df: pd.DataFrame):
        """Main backtest loop over 30m bars."""
        print(f"Starting 2-Year Realistic Backtest across {len(ohlcv_df)} 30-minute bars...")

        # Compute indicators
        print("Computing indicators...")
        series = self.indicator_calc.compute_full_series(ohlcv_df).reset_index(drop=True)

        for i in range(1, len(series)):
            row = series.iloc[i]
            prev_row = series.iloc[i - 1]

            # Skip if indicators not ready
            if (np.isnan(row["ema_trend"]) or np.isnan(row["adx"]) or
                np.isnan(row["atr"]) or np.isnan(row["atr_sma"]) or
                np.isnan(row["vol_sma"])):
                continue

            # Build indicator snapshot
            ind = self.indicator_calc.row_to_indicators(row, prev_row)
            atr = ind.atr

            # Check for existing position management
            if self.position is not None:
                # Generate micro-ticks for this bar
                ticks = self.tick_generator.generate_ticks_for_bar(ind)

                for tick in ticks:
                    # Process funding
                    self.process_funding(tick.timestamp)

                    # Check SL and trailing on each tick
                    self.check_sl_and_trailing(tick, atr)

                    # Check max SL (catastrophe stop)
                    if self.check_max_sl(tick, atr):
                        break  # Position closed

                # Record equity at bar close
                if self.position:
                    # Mark-to-market at bar close
                    mtm_price = ind.close
                    if self.position.direction == 'LONG':
                        mtm_pnl = (mtm_price - self.position.entry_price) * self.position.size_btc
                    else:
                        mtm_pnl = (self.position.entry_price - mtm_price) * self.position.size_btc
                    mtm_capital = self.capital + mtm_pnl
                else:
                    mtm_capital = self.capital

                self.equity_curve.append({
                    'timestamp': ind.timestamp,
                    'capital': mtm_capital,
                    'realized_capital': self.capital,
                })
                continue

            # No position - check for entry signal
            should_enter, is_long, regime = self.indicator_calc.evaluate_entry_signal(ind, False)
            if should_enter:
                is_trend = (regime == "trend")
                initial_sl, initial_tp, stop_dist = self.indicator_calc.calc_initial_levels(
                    ind.close, atr, is_long, is_trend
                )

                # Generate ticks for entry bar and attempt entry on first tick
                ticks = self.tick_generator.generate_ticks_for_bar(ind)
                direction = 'LONG' if is_long else 'SHORT'

                for tick in ticks:
                    self.process_funding(tick.timestamp)
                    self.execute_entry(direction, tick, initial_sl, is_trend, i)
                    break  # Enter on first tick of bar

            # Record equity
            self.equity_curve.append({
                'timestamp': ind.timestamp,
                'capital': self.capital,
                'realized_capital': self.capital,
            })

        # Close any open position at end
        if self.position is not None:
            last_row = series.iloc[-1]
            last_tick = Tick(
                timestamp=pd.Timestamp(last_row["timestamp"], unit="ms", tz="UTC"),
                price=last_row["close"],
                bid=last_row["close"] - 0.25,
                ask=last_row["close"] + 0.25,
                volume=1
            )
            self.execute_exit(last_tick, "End_of_Data", last_row["atr"])

        self.generate_report()
        return self.trades, self.equity_curve

    def generate_report(self):
        """Print detailed terminal report."""
        if not self.trades:
            print("⚠️ No trades were executed.")
            return

        trades_df = pd.DataFrame([t.__dict__ for t in self.trades])

        win_trades = trades_df[trades_df['net_pnl'] > 0]
        loss_trades = trades_df[trades_df['net_pnl'] <= 0]

        total_trades = len(trades_df)
        wins = len(win_trades)
        losses = len(loss_trades)
        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

        net_total_pnl = self.capital - self.config.initial_capital
        roi_pct = (net_total_pnl / self.config.initial_capital) * 100

        gross_profit = win_trades['gross_pnl'].sum() if not win_trades.empty else 0
        gross_loss = abs(loss_trades['gross_pnl'].sum()) if not loss_trades.empty else 1
        profit_factor = gross_profit / gross_loss if gross_loss != 0 else float('inf')

        avg_pnl = trades_df['net_pnl'].mean()

        # Monthly breakdown
        trades_df['month'] = pd.to_datetime(trades_df['exit_time']).dt.strftime('%Y-%m')
        monthly = trades_df.groupby('month').agg(
            trades=('trade_id', 'count'),
            wins=('net_pnl', lambda x: (x > 0).sum()),
            losses=('net_pnl', lambda x: (x <= 0).sum()),
            net_pnl=('net_pnl', 'sum'),
        ).reset_index()

        print("\n" + "=" * 70)
        print("      2-YEAR REALISTIC BACKTEST PERFORMANCE REPORT")
        print("=" * 70)
        print(f"{'1. Initial Capital:':<30} ${self.config.initial_capital:>14,.2f}")
        print(f"{'   Final Capital:':<30} ${self.capital:>14,.2f}")
        print(f"{'2. Gross P/L (pre-fees):':<30} ${self.total_gross_pnl:>14,.2f}")
        print(f"{'3. Net P/L (all-in):':<30} ${net_total_pnl:>14,.2f} ({roi_pct:+.2f}%)")
        print(f"{'4. Total Points Captured:':<30} {self.total_points_captured:>14,.2f}")
        print(f"{'5. Total Trades Executed:':<30} {total_trades:>14}")
        print(f"{'6. Win Rate:':<30} {win_rate:.2f}% ({wins}W / {losses}L)")
        print(f"{'7. Avg PnL per Trade:':<30} ${avg_pnl:>14,.2f}")
        print(f"{'8. Maximum Drawdown:':<30} -${self.max_drawdown_usd:>13,.2f} (-{self.max_drawdown_pct:.2f}%)")
        print(f"{'9. Profit Factor:':<30} {profit_factor:.2f}")

        # Fee Drag Breakdown
        print("-" * 70)
        print(f"{'10. TOTAL FEE DRAG BREAKDOWN':<30}")
        print(f"{'    Exchange Fees (Taker+Maker):':<30} -${self.total_exchange_fees:>13,.2f}")
        print(f"{'    18% GST on Fees:':<30} -${self.total_gst_paid:>13,.2f}")
        print(f"{'    Net Funding Accrual:':<30} ${self.total_funding_accrual:>13,.2f}")
        total_drag = self.total_exchange_fees + self.total_gst_paid - self.total_funding_accrual
        print(f"{'    TOTAL DRAG:':<30} -${total_drag:>13,.2f}")
        print("=" * 70)

        # Monthly Breakdown Table
        print("\n" + "=" * 70)
        print("           MONTHLY PERFORMANCE BREAKDOWN")
        print("=" * 70)
        print(f"{'Month':<12} {'Trades':>7} {'W/L':>8} {'Net P/L':>14} {'Max DD %':>10}")
        print("-" * 70)

        for _, m in monthly.iterrows():
            month_str = str(m['month'])
            trades_cnt = m['trades']
            w = m['wins']
            l = m['losses']
            net = m['net_pnl']

            # Calculate monthly max drawdown from equity curve
            month_start = pd.Period(month_str).to_timestamp().tz_localize('UTC')
            month_end = (pd.Period(month_str) + 1).to_timestamp().tz_localize('UTC')
            month_equity = [e for e in self.equity_curve
                          if month_start <= e['timestamp'] < month_end]
            if month_equity:
                equity_vals = [e['capital'] for e in month_equity]
                peak = equity_vals[0]
                max_dd = 0
                for v in equity_vals:
                    if v > peak:
                        peak = v
                    dd = (peak - v) / peak * 100 if peak > 0 else 0
                    max_dd = max(max_dd, dd)
            else:
                max_dd = 0

            print(f"{month_str:<12} {trades_cnt:>7} {w}W/{l}L {net:>14,.2f} {max_dd:>9.2f}%")

        print("=" * 70 + "\n")

    def get_results_dict(self) -> Dict:
        """Return results as dictionary for external use."""
        if not self.trades:
            return {}

        trades_df = pd.DataFrame([t.__dict__ for t in self.trades])
        win_trades = trades_df[trades_df['net_pnl'] > 0]
        loss_trades = trades_df[trades_df['net_pnl'] <= 0]

        return {
            'initial_capital': self.config.initial_capital,
            'final_capital': self.capital,
            'gross_pnl': self.total_gross_pnl,
            'net_pnl': self.capital - self.config.initial_capital,
            'roi_pct': (self.capital - self.config.initial_capital) / self.config.initial_capital * 100,
            'total_points_captured': self.total_points_captured,
            'total_trades': len(trades_df),
            'wins': len(win_trades),
            'losses': len(loss_trades),
            'win_rate_pct': len(win_trades) / len(trades_df) * 100 if len(trades_df) > 0 else 0,
            'avg_pnl_per_trade': trades_df['net_pnl'].mean(),
            'max_drawdown_usd': self.max_drawdown_usd,
            'max_drawdown_pct': self.max_drawdown_pct,
            'profit_factor': win_trades['gross_pnl'].sum() / abs(loss_trades['gross_pnl'].sum())
                           if not loss_trades.empty and loss_trades['gross_pnl'].sum() != 0 else float('inf'),
            'total_exchange_fees': self.total_exchange_fees,
            'total_gst_paid': self.total_gst_paid,
            'total_funding_accrual': self.total_funding_accrual,
            'total_fee_drag': self.total_exchange_fees + self.total_gst_paid - self.total_funding_accrual,
            'trades': self.trades,
            'equity_curve': self.equity_curve,
        }


# ═══════════════════════════════════════════════════════════════════════
# MAIN - Quick Test
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Quick sanity test with synthetic data
    print("Running quick test with synthetic data...")

    dates = pd.date_range(start="2024-08-01", periods=1000, freq="30min", tz="UTC")
    np.random.seed(42)
    price_path = 60000 + np.cumsum(np.random.normal(10, 50, len(dates)))

    df = pd.DataFrame({
        'timestamp': (dates.view('int64') // 1_000_000).astype('int64'),
        'open': price_path,
        'high': price_path + np.abs(np.random.normal(10, 20, len(dates))),
        'low': price_path - np.abs(np.random.normal(10, 20, len(dates))),
        'close': price_path + np.random.normal(0, 10, len(dates)),
        'volume': np.random.uniform(50, 500, len(dates))
    })

    config = BacktestConfig()
    backtester = RealisticBacktester(config)
    backtester.run(df)