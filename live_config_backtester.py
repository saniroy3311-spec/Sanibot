#!/usr/bin/env python3
"""
Live Config Backtester — Exact match to Sanibot LIVE configuration
=================================================================
Uses the EXACT parameters from the .eve file / config.py live values:
- ENTRY_STRATEGY=rsi_bounce (uses OPT_* params for EMAs but NOT for SL/TP)
- EMA_FAST_LEN=10 (OPT_EMA_FAST_LEN), EMA_TREND_LEN=160 (OPT_EMA_SLOW_LEN)
- ADX_TREND_TH=22, ADX_RANGE_TH=5, ADX_MIN_FILTER=0
- FILTER_ATR_MULT=1.4, FILTER_VOL_MULT=1.0, FILTER_VOL_ENABLED=true
- TREND_RR=4.0, RANGE_RR=2.5
- TREND_ATR_MULT=0.6, RANGE_ATR_MULT=0.5
- MAX_SL_MULT=1.5, MAX_SL_POINTS=500
- BE_MULT=0.5 (but .eve shows 0.5, config.py shows 0.4 - using .eve value 0.5)
- PINE_MINTICK=0.5
- TRAIL_STAGES from config.py (Pine-exact)
- TRAIL_ARM_USE_TRIGGER=true
- TRAIL_OFFSET_FLOOR_MULT=0.15
- BAR_CLOSE_SL_EVAL=true
- SL_CONFIRM_TICKS=5
- TP_HARD_EXIT=false
- COMMISSION_PCT=0.0005 (0.05% taker)
- GST_PCT=0.18 (18% GST on fees)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
import math


# ═══════════════════════════════════════════════════════════════════════
# LIVE BOT CONFIGURATION (Exact from .eve / config.py for rsi_bounce strategy)
# ═══════════════════════════════════════════════════════════════════════
@dataclass
class LiveBotConfig:
    """All live bot parameters in one place - matches .eve exactly"""

    # Position Sizing
    symbol: str = "BTC/USDT"
    initial_capital: float = 50000.0          # $50,000 USD
    position_btc_size: float = 0.005          # 0.005 BTC per position (from .eve POSITION_BTC_SIZE)
    lot_size_multiplier: int = 1000           # 1 contract = 0.001 BTC (Delta)

    # Fees & Taxation (Delta India)
    taker_fee_pct: float = 0.0005             # 0.05% taker fee (entry)
    maker_fee_pct: float = 0.0002             # 0.02% maker fee (exit limit)
    gst_pct: float = 0.18                     # 18% GST on fees (Delta India)
    slippage_pct: float = 0.0001              # 0.01% slippage on market orders

    # Stop Loss Confirmation (from .eve)
    sl_confirm_ticks: int = 5                 # SL_CONFIRM_TICKS=5
    trail_confirm_ticks: int = 2              # TRAIL_SL_CONFIRM_TICKS=2

    # Trailing Loop
    trail_loop_interval_sec: float = 0.1      # TRAIL_LOOP_SEC=0.1 (fast)

    # Funding Rates (8-hour intervals: 00:00, 08:00, 16:00 UTC)
    default_funding_rate: float = 0.0001      # 0.01% per 8h fallback
    funding_interval_hours: int = 8

    # Micro-tick Generation
    ticks_per_bar: int = 120                  # 30m bar → 120 ticks (15s each)
    brownian_noise_scale: float = 0.02        # Noise as fraction of bar range

    # PINE-EXACT TRAIL STAGES (from config.py - TradingView Inputs panel)
    TRAIL_STAGES: List[Tuple[float, float, float]] = field(default_factory=lambda: [
        (0.8,  0.50, 0.40),   # Stage 1
        (1.5,  0.40, 0.30),   # Stage 2
        (2.5,  0.30, 0.25),   # Stage 3
        (4.0,  0.20, 0.15),   # Stage 4
        (6.0,  0.15, 0.10),   # Stage 5
    ])
    PINE_MINTICK: float = 0.5

    # === STRATEGY PARAMETERS (Exact from .eve for rsi_bounce) ===
    # EMA Lengths (uses OPT_* params for calculations) - FROM .eve LINES 82-83
    OPT_EMA_FAST_LEN: int = 50          # .eve: OPT_EMA_FAST_LEN=50
    OPT_EMA_SLOW_LEN: int = 200         # .eve: OPT_EMA_SLOW_LEN=200

    # Regime (Pine-exact)
    ADX_TREND_TH: float = 22.0          # ADX_TREND_TH=22
    ADX_RANGE_TH: float = 5.0           # ADX_RANGE_TH=5
    ADX_MIN_FILTER: float = 0.0         # ADX_MIN_FILTER=0
    ADX_TOLERANCE: float = 0.0          # ADX_TOLERANCE=0

    # Entry Filters
    FILTER_ATR_MULT: float = 1.4        # FILTER_ATR_MULT=1.4
    FILTER_BODY_MULT: float = 0.5       # FILTER_BODY_MULT=0.5
    FILTER_BODY_TOLERANCE: float = 0.0  # FILTER_BODY_TOLERANCE=0
    FILTER_VOL_ENABLED: bool = True     # FILTER_VOL_ENABLED=true
    FILTER_VOL_MULT: float = 1.0        # FILTER_VOL_MULT=1.0
    BREAKOUT_BUFFER_PTS: float = 0.0    # BREAKOUT_BUFFER_PTS=0

    # Risk / Reward (Pine-exact for rsi_bounce)
    # Note: For rsi_bounce, TREND_ATR_MULT=0.6, RANGE_ATR_MULT=0.5 (NOT overridden by TB)
    TREND_RR: float = 4.0               # TREND_RR=4.0
    RANGE_RR: float = 2.5               # RANGE_RR=2.5
    TREND_ATR_MULT: float = 0.6         # TREND_ATR_MULT=0.6
    RANGE_ATR_MULT: float = 0.5         # RANGE_ATR_MULT=0.5
    MAX_SL_MULT: float = 1.5            # MAX_SL_MULT=1.5
    MAX_SL_POINTS: float = 500.0        # MAX_SL_POINTS=500
    BE_MULT: float = 0.5                # BE_MULT=0.5 (from .eve, config.py has 0.4)

    # HTF Trend Filter
    OPT_HTF_TREND_ENABLED: bool = True
    OPT_HTF_EMA_LEN: int = 200
    OPT_HTF_TIMEFRAME: str = "4h"

    # ATR Minimum Filter (OPT_* disabled for rsi_bounce)
    OPT_ATR_MIN_FILTER: float = 0.0
    OPT_ATR_MIN_PCT: float = 0.0

    # SL Configuration
    OPT_INITIAL_SL_PCT: float = 0.0     # Disabled (ATR-based)
    BAR_CLOSE_SL_EVAL: bool = True      # Bar-close only SL evaluation

    # TP Configuration
    TP_HARD_EXIT: bool = False          # TP is NOT a hard exit

    # Trailing Configuration
    TRAIL_ARM_USE_TRIGGER: bool = True  # Arm at trigger (t#Trig) not points (t#Pts)
    TRAIL_ARM_FLOOR_MULT: float = 0.0
    TRAIL_OFFSET_FLOOR_MULT: float = 0.15

    # Optimization trail triggers (disabled for rsi_bounce)
    OPT_TRAIL_TRIGGER_1_PCT: float = 0.0
    OPT_TRAIL_TRIGGER_2_PCT: float = 0.0

    # Other
    RSI_LEN: int = 14
    RSI_OB: int = 70
    RSI_OS: int = 30
    ATR_LEN: int = 14
    DI_LEN: int = 14
    ADX_SMOOTH: int = 14
    ADX_EMA: int = 5

    # Exit
    SL_FIRE_VIA_BRACKET: bool = False
    TRAIL_EXIT_FROM_DELTA_WS: bool = False
    TRAIL_FIRE_SL_ON_CANDLE_EXTREME: bool = False
    ALLOW_REVERSAL: bool = False
    TIME_EXIT_MINUTES: int = 0


# ═══════════════════════════════════════════════════════════════════════
# DATA STRUCTURES (Same as realistic_backtester)
# ═══════════════════════════════════════════════════════════════════════
@dataclass
class Tick:
    """Single micro-tick in the synthetic stream."""
    timestamp: pd.Timestamp
    price: float
    bid: float
    ask: float
    volume: float


@dataclass
class Position:
    """Active position state."""
    direction: str
    entry_price: float
    size_btc: float
    lots: int
    sl_price: float
    initial_sl: float
    entry_fee: float
    entry_gst: float
    trail_stage: int = 0
    peak_price: float = 0.0
    entry_time: Optional[pd.Timestamp] = None
    entry_bar_idx: int = -1
    is_trend: bool = False
    funding_paid: float = 0.0
    be_done: bool = False  # Breakeven armed flag


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
    gross_pnl: float
    net_pnl: float
    points_captured: float
    exit_reason: str
    trail_stage_at_exit: int
    bars_held: int
    entry_fee: float
    entry_gst: float
    exit_fee: float
    exit_gst: float
    funding_paid: float


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
# INDICATOR CALCULATIONS (Exact from strategy_logic.py)
# ═══════════════════════════════════════════════════════════════════════
def _first_valid_idx(arr: np.ndarray) -> int:
    for i, v in enumerate(arr):
        if not np.isnan(v):
            return i
    return -1


def _rma(series: pd.Series, length: int) -> pd.Series:
    """Runtime Moving Average (Wilder's smoothing)"""
    arr = series.to_numpy(dtype=np.float64)
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)
    start = _first_valid_idx(arr)
    if start < 0 or n - start < length:
        return pd.Series(out, index=series.index)
    seed_end = start + length
    seed = float(np.mean(arr[start:seed_end]))
    out[seed_end - 1] = seed
    alpha = 1.0 / length
    for i in range(seed_end, n):
        v = arr[i]
        if np.isnan(v):
            out[i] = out[i - 1]
        else:
            out[i] = out[i - 1] * (1.0 - alpha) + v * alpha
    return pd.Series(out, index=series.index)


def _ema(series: pd.Series, length: int) -> pd.Series:
    arr = series.to_numpy(dtype=np.float64)
    n = len(arr)
    out = np.full(n, np.nan, dtype=np.float64)
    start = _first_valid_idx(arr)
    if start < 0 or n - start < length:
        return pd.Series(out, index=series.index)
    seed_end = start + length
    seed = float(np.mean(arr[start:seed_end]))
    out[seed_end - 1] = seed
    alpha = 2.0 / (length + 1.0)
    for i in range(seed_end, n):
        v = arr[i]
        if np.isnan(v):
            out[i] = out[i - 1]
        else:
            out[i] = out[i - 1] * (1.0 - alpha) + v * alpha
    return pd.Series(out, index=series.index)


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    tr.iloc[0] = high.iloc[0] - low.iloc[0]
    return tr


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int) -> pd.Series:
    return _rma(_true_range(high, low, close), length)


def _rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta.clip(upper=0.0))
    avg_gain = _rma(gain.fillna(0.0), length)
    avg_loss = _rma(loss.fillna(0.0), length)
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = rsi.where(avg_loss != 0.0, 100.0)
    return rsi


def _dmi(high: pd.Series, low: pd.Series, close: pd.Series, di_len: int, adx_smooth: int):
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm  = pd.Series(plus_dm,  index=high.index).fillna(0.0)
    minus_dm = pd.Series(minus_dm, index=high.index).fillna(0.0)

    tr = _true_range(high, low, close)
    atr_di = _rma(tr, di_len)
    sm_plus  = _rma(plus_dm,  di_len)
    sm_minus = _rma(minus_dm, di_len)

    plus_di  = 100.0 * sm_plus  / atr_di.replace(0.0, np.nan)
    minus_di = 100.0 * sm_minus / atr_di.replace(0.0, np.nan)
    plus_di  = plus_di.fillna(0.0)
    minus_di = minus_di.fillna(0.0)

    dx_denom = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / dx_denom
    dx = dx.fillna(0.0)

    adx_raw = _rma(dx, adx_smooth)
    return plus_di, minus_di, adx_raw


def compute_full_series(df: pd.DataFrame, config: LiveBotConfig) -> pd.DataFrame:
    """
    Compute full indicator series using LIVE bot parameters.
    This EXACTLY replicates strategy_logic.compute_full_series with OPT_* EMA params.
    """
    min_bars = config.OPT_EMA_SLOW_LEN + 10  # Use slow EMA for min_bars
    if len(df) < min_bars:
        raise ValueError(f"Need >={min_bars} bars, got {len(df)}")

    df = df.reset_index(drop=True).copy()
    high   = df["high"].astype(float)
    low    = df["low"].astype(float)
    close  = df["close"].astype(float)
    open_  = df["open"].astype(float)
    volume = df["volume"].astype(float)

    out = pd.DataFrame()
    out["timestamp"] = df["timestamp"].values if "timestamp" in df.columns else np.arange(len(df))
    out["open"]   = open_.values
    out["high"]   = high.values
    out["low"]    = low.values
    out["close"]  = close.values
    out["volume"] = volume.values

    # Use OPT_* EMA lengths (LIVE bot uses 10/160, NOT 50/200!)
    out["ema_trend"] = _ema(close, config.OPT_EMA_SLOW_LEN).values
    out["ema_fast"]  = _ema(close, config.OPT_EMA_FAST_LEN).values

    atr = _atr(high, low, close, config.ATR_LEN)
    out["atr"]     = atr.values
    out["atr_sma"] = atr.rolling(50).mean().values

    out["rsi"] = _rsi(close, config.RSI_LEN).values

    plus_di, minus_di, adx_raw = _dmi(high, low, close, config.DI_LEN, config.ADX_SMOOTH)
    out["dip"]     = plus_di.values
    out["dim"]     = minus_di.values
    out["adx_raw"] = adx_raw.values
    out["adx"]     = _ema(adx_raw, config.ADX_EMA).values

    out["vol_sma"] = volume.rolling(20).mean().values

    # Higher Timeframe Trend Filter (4H 200 EMA) - resample 30m to 4H
    if config.OPT_HTF_TREND_ENABLED:
        htf_periods = 8  # 8 * 30m = 4H
        htf_close = close.rolling(htf_periods).apply(
            lambda x: x.iloc[-1] if len(x) == htf_periods else np.nan
        )
        htf_ema = _ema(htf_close.dropna(), config.OPT_HTF_EMA_LEN)
        out["htf_ema"] = htf_ema.reindex(close.index, method='ffill').values
        out["htf_trend_up"] = (close > out["htf_ema"]).astype(float)
        out["htf_trend_down"] = (close < out["htf_ema"]).astype(float)
    else:
        out["htf_ema"] = np.nan
        out["htf_trend_up"] = 1.0
        out["htf_trend_down"] = 1.0

    return out


# ═══════════════════════════════════════════════════════════════════════
# MICRO-TICK GENERATOR (Same as realistic_backtester)
# ═══════════════════════════════════════════════════════════════════════
class MicroTickGenerator:
    def __init__(self, config: LiveBotConfig):
        self.config = config
        self.tick_spread = 0.5

    def generate_ticks_for_bar(self, bar: BarIndicators) -> List[Tick]:
        n_ticks = self.config.ticks_per_bar
        open_p, high_p, low_p, close_p = bar.open, bar.high, bar.low, bar.close
        bar_range = high_p - low_p

        if close_p >= open_p:
            path_segments = [(open_p, low_p), (low_p, high_p), (high_p, close_p)]
        else:
            path_segments = [(open_p, high_p), (high_p, low_p), (low_p, close_p)]

        ticks_per_seg = n_ticks // 3
        remainder = n_ticks % 3

        all_prices = []
        for i, (p_start, p_end) in enumerate(path_segments):
            seg_ticks = ticks_per_seg + (1 if i < remainder else 0)
            if seg_ticks <= 0:
                continue

            base_prices = np.linspace(p_start, p_end, seg_ticks)
            t = np.linspace(0, 1, seg_ticks)
            bridge_var = t * (1 - t) * 4
            noise_scale = bar_range * self.config.brownian_noise_scale
            noise = np.random.normal(0, noise_scale, seg_ticks) * np.sqrt(bridge_var)
            seg_prices = base_prices + noise
            seg_prices = np.clip(seg_prices, low_p, high_p)
            all_prices.extend(seg_prices)

        start_ts = bar.timestamp
        tick_interval_sec = 1800 // len(all_prices)
        timestamps = pd.date_range(
            start=start_ts,
            periods=len(all_prices),
            freq=f'{tick_interval_sec}s'
        )

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
# LIVE BACKTESTER ENGINE
# ═══════════════════════════════════════════════════════════════════════
class LiveConfigBacktester:
    """
    Event-driven backtester that EXACTLY matches live bot behavior:
    - Uses LIVE bot config parameters
    - 5-tick SL confirmation
    - Intra-bar trailing on micro-ticks
    - Realistic fees: 0.05% taker entry, 0.02% maker exit + 18% GST
    - Funding rate accrual every 8 hours
    """

    def __init__(self, config: LiveBotConfig, funding_df: pd.DataFrame = None):
        self.config = config
        self.funding_df = funding_df

        self.capital = config.initial_capital
        self.position: Optional[Position] = None
        self.sl_tick_counter: int = 0
        self.trail_tick_counter: int = 0
        self.trades: List[CompletedTrade] = []
        self.equity_curve: List[Dict] = []

        self.total_gross_pnl: float = 0.0
        self.total_points_captured: float = 0.0
        self.total_exchange_fees: float = 0.0
        self.total_gst_paid: float = 0.0
        self.total_funding_accrual: float = 0.0
        self.peak_capital: float = config.initial_capital
        self.max_drawdown_usd: float = 0.0
        self.max_drawdown_pct: float = 0.0

        self.tick_generator = MicroTickGenerator(config)
        self.funding_lookup = self._build_funding_lookup() if funding_df is not None else {}
        self.trade_id_counter = 0
        self._last_funding_bucket = -1

    def btc_to_lots(self, btc_amount: float) -> int:
        return int(btc_amount * self.config.lot_size_multiplier)

    def _build_funding_lookup(self) -> Dict[int, float]:
        lookup = {}
        for _, row in self.funding_df.iterrows():
            ts = int(row["timestamp"])
            lookup[ts] = float(row["funding_rate"])
        return lookup

    def get_funding_rate(self, timestamp: pd.Timestamp) -> float:
        ts_sec = int(timestamp.timestamp())
        interval_sec = self.config.funding_interval_hours * 3600
        bucket = (ts_sec // interval_sec) * interval_sec
        if bucket in self.funding_lookup:
            return self.funding_lookup[bucket]
        return self.config.default_funding_rate

    def process_funding(self, timestamp: pd.Timestamp):
        if self.position is None:
            return

        if timestamp.hour % self.config.funding_interval_hours == 0 and timestamp.minute == 0:
            funding_ts = int(timestamp.timestamp())
            interval_sec = self.config.funding_interval_hours * 3600
            bucket = (funding_ts // interval_sec) * interval_sec

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

                self.position.funding_paid += funding_paid

    def calc_initial_levels(self, entry_price: float, atr: float, is_long: bool, is_trend: bool) -> Tuple[float, float, float]:
        """Calculate initial SL and TP using LIVE bot logic."""
        cfg = self.config

        rr = cfg.TREND_RR if is_trend else cfg.RANGE_RR
        atr_mult = cfg.TREND_ATR_MULT if is_trend else cfg.RANGE_ATR_MULT
        stop_dist = min(atr * atr_mult, cfg.MAX_SL_POINTS)

        if cfg.OPT_INITIAL_SL_PCT > 0:
            stop_dist = entry_price * cfg.OPT_INITIAL_SL_PCT

        if is_long:
            sl = entry_price - stop_dist
            tp = entry_price + stop_dist * rr
        else:
            sl = entry_price + stop_dist
            tp = entry_price - stop_dist * rr

        return sl, tp, stop_dist

    def evaluate_entry(self, ind: BarIndicators, has_position: bool) -> Tuple[bool, bool, str]:
        """Evaluate entry signal using LIVE bot logic (rsi_bounce strategy)."""
        if has_position:
            return False, False, "none"

        cfg = self.config

        # ATR minimum filter
        atr_min_ok = True
        if cfg.OPT_ATR_MIN_FILTER > 0:
            atr_min_ok = ind.atr >= cfg.OPT_ATR_MIN_FILTER
        if cfg.OPT_ATR_MIN_PCT > 0:
            atr_min_ok = atr_min_ok and (ind.atr / ind.close >= cfg.OPT_ATR_MIN_PCT)

        # Filters
        atr_ok = ind.atr < ind.atr_sma * cfg.FILTER_ATR_MULT
        body_ok = True  # No body filter in live
        vol_ok = ind.volume > 0 and ind.vol_sma > 0 and ind.volume > ind.vol_sma * cfg.FILTER_VOL_MULT
        filters_ok = atr_ok and vol_ok and body_ok and atr_min_ok

        # ADX regime
        adx_v = ind.adx
        trend_regime = adx_v > cfg.ADX_TREND_TH
        range_regime = adx_v < cfg.ADX_RANGE_TH

        # ADX minimum filter
        adx_min_ok = adx_v >= cfg.ADX_MIN_FILTER

        if not adx_min_ok:
            return False, False, "none"

        # Entry logic (rsi_bounce strategy)
        # Trend entries
        trend_long = (
            trend_regime
            and ind.ema_fast > ind.ema_trend
            and ind.dip > ind.dim
            and ind.close > ind.prev_high + cfg.BREAKOUT_BUFFER_PTS
            and filters_ok
            and (not cfg.OPT_HTF_TREND_ENABLED or ind.htf_trend_up > 0.5)
        )
        trend_short = (
            trend_regime
            and ind.ema_fast < ind.ema_trend
            and ind.dim > ind.dip
            and ind.close < ind.prev_low - cfg.BREAKOUT_BUFFER_PTS
            and filters_ok
            and (not cfg.OPT_HTF_TREND_ENABLED or ind.htf_trend_down > 0.5)
        )

        # Range entries
        range_long = (
            range_regime
            and ind.rsi < cfg.RSI_OS
            and filters_ok
            and (not cfg.OPT_HTF_TREND_ENABLED or ind.htf_trend_up > 0.5)
        )
        range_short = (
            range_regime
            and ind.rsi > cfg.RSI_OB
            and filters_ok
            and (not cfg.OPT_HTF_TREND_ENABLED or ind.htf_trend_down > 0.5)
        )

        if trend_long:
            return True, True, "trend"
        if trend_short:
            return True, False, "trend"
        if range_long:
            return True, True, "range"
        if range_short:
            return True, False, "range"

        return False, False, "none"

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
        Compute trail SL price using Pine Script EXACT logic.
        trailing activates when profit >= atr * pts_mult * mintick
        offset = atr * off_mult * mintick
        """
        if stage == 0:
            return None

        idx = stage - 1
        _, pts_mult, off_mult = self.config.TRAIL_STAGES[idx]

        activation = atr * pts_mult * self.config.PINE_MINTICK
        if profit_dist < activation:
            return None

        offset = atr * off_mult * self.config.PINE_MINTICK

        if direction == 'LONG':
            return peak_price - offset
        else:
            return peak_price + offset

    def check_max_sl(self, tick: Tick, atr: float) -> bool:
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

    def execute_entry(self, direction: str, tick: Tick, initial_sl: float, is_trend: bool, bar_idx: int):
        if self.position is not None:
            return

        if direction == 'LONG':
            fill_price = tick.ask * (1 + self.config.slippage_pct)
        else:
            fill_price = tick.bid * (1 - self.config.slippage_pct)

        size_btc = self.config.position_btc_size
        lots = self.btc_to_lots(size_btc)

        notional = size_btc * fill_price
        entry_fee = notional * self.config.taker_fee_pct
        entry_gst = entry_fee * self.config.gst_pct

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
            funding_paid=0.0,
        )
        self.sl_tick_counter = 0
        self.trail_tick_counter = 0

    def execute_exit(self, tick: Tick, reason: str, atr: float):
        pos = self.position
        if pos is None:
            return

        if pos.direction == 'LONG':
            fill_price = tick.bid  # Exit at bid (maker)
        else:
            fill_price = tick.ask  # Exit at ask (maker)

        if pos.direction == 'LONG':
            points_captured = fill_price - pos.entry_price
            gross_pnl = points_captured * pos.size_btc
        else:
            points_captured = pos.entry_price - fill_price
            gross_pnl = points_captured * pos.size_btc

        self.total_points_captured += points_captured
        self.total_gross_pnl += gross_pnl

        notional = pos.size_btc * fill_price
        exit_fee = notional * self.config.maker_fee_pct
        exit_gst = exit_fee * self.config.gst_pct

        self.total_exchange_fees += exit_fee
        self.total_gst_paid += exit_gst

        net_pnl = gross_pnl - (pos.entry_fee + pos.entry_gst + exit_fee + exit_gst + pos.funding_paid)

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

        # Calculate bars held
        if self.equity_curve:
            bars_held = len([e for e in self.equity_curve if pos.entry_time <= e['timestamp'] <= tick.timestamp])
        else:
            bars_held = 0

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
            bars_held=bars_held,
            entry_fee=pos.entry_fee,
            entry_gst=pos.entry_gst,
            exit_fee=exit_fee,
            exit_gst=exit_gst,
            funding_paid=pos.funding_paid,
        ))

        self.position = None
        self.sl_tick_counter = 0
        self.trail_tick_counter = 0

    def run(self, ohlcv_df: pd.DataFrame):
        print(f"Starting Live-Config Backtest across {len(ohlcv_df)} 30-minute bars...")
        print(f"Config: EMA {self.config.OPT_EMA_FAST_LEN}/{self.config.OPT_EMA_SLOW_LEN}, "
              f"ADX {self.config.ADX_TREND_TH}/{self.config.ADX_RANGE_TH}, "
              f"Pos {self.config.position_btc_size} BTC")

        print("Computing indicators...")
        series = compute_full_series(ohlcv_df, self.config).reset_index(drop=True)

        for i in range(1, len(series)):
            row = series.iloc[i]
            prev_row = series.iloc[i - 1]

            if (np.isnan(row["ema_trend"]) or np.isnan(row["adx"]) or
                np.isnan(row["atr"]) or np.isnan(row["atr_sma"]) or
                np.isnan(row["vol_sma"])):
                continue

            # Build indicator snapshot
            ind = BarIndicators(
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
            atr = ind.atr

            if self.position is not None:
                ticks = self.tick_generator.generate_ticks_for_bar(ind)

                for tick in ticks:
                    self.process_funding(tick.timestamp)
                    self.check_sl_and_trailing(tick, atr, is_bar_close=False)
                    if self.check_max_sl(tick, atr):
                        break

                # BAR_CLOSE_SL_EVAL: Check Initial SL at bar close (Pine-exact)
                if self.position is not None:
                    bar_close_tick = Tick(
                        timestamp=ind.timestamp,
                        price=ind.close,
                        bid=ind.close - 0.25,
                        ask=ind.close + 0.25,
                        volume=1
                    )
                    self.check_sl_and_trailing(bar_close_tick, atr, is_bar_close=True)

                # Record equity at bar close
                if self.position:
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

            # No position - check for entry
            should_enter, is_long, regime = self.evaluate_entry(ind, False)
            if should_enter:
                is_trend = (regime == "trend")
                initial_sl, initial_tp, stop_dist = self.calc_initial_levels(
                    ind.close, atr, is_long, is_trend
                )

                ticks = self.tick_generator.generate_ticks_for_bar(ind)
                direction = 'LONG' if is_long else 'SHORT'

                for tick in ticks:
                    self.process_funding(tick.timestamp)
                    self.execute_entry(direction, tick, initial_sl, is_trend, i)
                    break

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

    def check_sl_and_trailing(self, tick: Tick, atr: float, is_bar_close: bool = False):
        """Check SL and trailing stops.

        With BAR_CLOSE_SL_EVAL=True (Pine-exact):
        - Initial SL (pre-BE, pre-trail) ONLY evaluated at bar close
        - BE SL (once be_done=True) evaluates on ticks
        - Trail SL (trail_stage > 0) evaluates on ticks
        - Max SL, TP always evaluate on ticks
        """
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

        # Breakeven (Pine-exact: profit > atr * BE_MULT)
        # Track if BE just got armed this tick
        was_be_done = getattr(pos, 'be_done', False)
        if pos.trail_stage == 0 and profit_dist > atr * self.config.BE_MULT:
            if pos.direction == 'LONG':
                pos.sl_price = max(pos.sl_price, pos.entry_price)
            else:
                pos.sl_price = min(pos.sl_price, pos.entry_price)
            pos.be_done = True

        # Trail stage upgrade
        new_stage = self._calculate_trail_stage(profit_dist, atr)
        if new_stage > pos.trail_stage:
            pos.trail_stage = new_stage
            trail_sl = self._compute_trail_sl(pos.trail_stage, pos.peak_price, profit_dist, pos.direction, atr)
            if trail_sl is not None:
                if pos.direction == 'LONG':
                    pos.sl_price = max(pos.sl_price, trail_sl)
                else:
                    pos.sl_price = min(pos.sl_price, trail_sl)

        # Determine if we're in Initial SL phase (pre-BE, pre-trail)
        is_initial_sl_phase = (pos.trail_stage == 0 and not getattr(pos, 'be_done', False))

        # BAR_CLOSE_SL_EVAL: Skip Initial SL check on ticks, only check at bar close
        if self.config.BAR_CLOSE_SL_EVAL and is_initial_sl_phase and not is_bar_close:
            # Skip tick-level Initial SL check - will be caught at bar close
            return

        # SL breach with confirmation ticks
        sl_hit = False
        if pos.direction == 'LONG':
            if price <= pos.sl_price:
                self.sl_tick_counter += 1
            else:
                self.sl_tick_counter = 0

            required_ticks = self.config.sl_confirm_ticks if pos.trail_stage == 0 else self.config.trail_confirm_ticks
            if self.sl_tick_counter >= required_ticks:
                sl_hit = True
        else:
            if price >= pos.sl_price:
                self.sl_tick_counter += 1
            else:
                self.sl_tick_counter = 0

            required_ticks = self.config.sl_confirm_ticks if pos.trail_stage == 0 else self.config.trail_confirm_ticks
            if self.sl_tick_counter >= required_ticks:
                sl_hit = True

        if sl_hit:
            reason = "SL" if pos.trail_stage == 0 else f"Trail_SL_Stage{pos.trail_stage}"
            self.execute_exit(tick, reason, atr)

    def generate_report(self):
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

        print("\n" + "=" * 80)
        print("      LIVE CONFIG BACKTEST PERFORMANCE REPORT (12 Months)")
        print("=" * 80)
        print(f"{'Initial Capital:':<35} ${self.config.initial_capital:>14,.2f}")
        print(f"{'Final Capital:':<35} ${self.capital:>14,.2f}")
        print(f"{'Gross P/L (pre-fees):':<35} ${self.total_gross_pnl:>14,.2f}")
        print(f"{'Net P/L (all-in):':<35} ${net_total_pnl:>14,.2f} ({roi_pct:+.2f}%)")
        print(f"{'Total Points Captured:':<35} {self.total_points_captured:>14,.2f}")
        print(f"{'Total Trades Executed:':<35} {total_trades:>14}")
        print(f"{'Win Rate:':<35} {win_rate:.2f}% ({wins}W / {losses}L)")
        print(f"{'Avg PnL per Trade:':<35} ${avg_pnl:>14,.2f}")
        print(f"{'Maximum Drawdown:':<35} -${self.max_drawdown_usd:>13,.2f} (-{self.max_drawdown_pct:.2f}%)")
        print(f"{'Profit Factor:':<35} {profit_factor:.2f}")

        print("-" * 80)
        print(f"{'TOTAL FEE DRAG BREAKDOWN':<35}")
        print(f"{'  Exchange Fees (Taker+Maker):':<35} -${self.total_exchange_fees:>13,.2f}")
        print(f"{'  18% GST on Fees:':<35} -${self.total_gst_paid:>13,.2f}")
        print(f"{'  Net Funding Accrual:':<35} ${self.total_funding_accrual:>13,.2f}")
        total_drag = self.total_exchange_fees + self.total_gst_paid - self.total_funding_accrual
        print(f"{'  TOTAL DRAG:':<35} -${total_drag:>13,.2f}")
        print("=" * 80)

        print("\n" + "=" * 80)
        print("           MONTHLY PERFORMANCE BREAKDOWN")
        print("=" * 80)
        print(f"{'Month':<12} {'Trades':>7} {'W/L':>8} {'Net P/L':>14} {'Max DD %':>10}")
        print("-" * 80)

        for _, m in monthly.iterrows():
            month_str = str(m['month'])
            trades_cnt = m['trades']
            w = m['wins']
            l = m['losses']
            net = m['net_pnl']

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

        print("=" * 80 + "\n")

        # Export to CSV
        trades_df.to_csv("backtest_trades.csv", index=False)
        print(f"Exported {len(trades_df)} trades to backtest_trades.csv")
        monthly.to_csv("backtest_monthly.csv", index=False)
        print(f"Exported monthly summary to backtest_monthly.csv")

    def get_results_dict(self) -> Dict:
        if not self.trades:
            return {}

        trades_df = pd.DataFrame([t.__dict__ for t in self.trades])
        win_trades = trades_df[trades_df['net_pnl'] > 0]
        loss_trades = trades_df[trades_df['net_pnl'] <= 0]

        # Export trades to CSV
        trades_df.to_csv("backtest_trades.csv", index=False)
        print(f"\nExported {len(trades_df)} trades to backtest_trades.csv")

        # Export monthly summary
        monthly.to_csv("backtest_monthly.csv", index=False)
        print(f"Exported monthly summary to backtest_monthly.csv")

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


if __name__ == "__main__":
    import pandas as pd
    from pathlib import Path

    # Load 1-year data
    data_file = Path("binance_2yr_30m.csv")
    funding_file = Path("delta_2yr_funding.csv")

    if not data_file.exists():
        print("Run fetch_2yr_data.py first to get data")
        exit(1)

    df = pd.read_csv(data_file)
    print(f"Loaded {len(df)} bars")
    print(f"Date range: {pd.to_datetime(df.iloc[0]['timestamp'], unit='ms')} to {pd.to_datetime(df.iloc[-1]['timestamp'], unit='ms')}")

    funding_df = pd.read_csv(funding_file) if funding_file.exists() else None

    config = LiveBotConfig()
    backtester = LiveConfigBacktester(config, funding_df)
    trades, equity = backtester.run(df)