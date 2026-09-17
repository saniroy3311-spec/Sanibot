"""
strategy/trend_breakout.py — Shiva Sniper Bot-v10
Optimized with Wick Filter, Candle Range Location, and Flat EMA Gate
"""
from __future__ import annotations
import time

from indicators.engine import Signal, SignalType, IndicatorSnapshot
from strategy.guards import passes_extension_guard
from config import ADX_TREND_TH, BREAKOUT_BUFFER_PTS

_last_signal_time = 0.0


def evaluate(snap: IndicatorSnapshot, has_position: bool = False) -> Signal:
    """
    Trend Breakout entry evaluation for a confirmed bar.
    Direction: Price relative to 50 EMA and 200 EMA.
    Extension Guard: <= 1.8x ATR distance from 50 EMA (blocks late chasing).
    Wick Guard: Rejects candles where wick > body or closing in rejection zone.
    """
    global _last_signal_time

    if has_position:
        return Signal(SignalType.NONE, False, False, "NONE")

    # 1. 1-Candle Cooldown: Prevent re-entering within 28 minutes of last entry
    now = time.time()
    if (now - _last_signal_time) < 1700:
        return Signal(SignalType.NONE, False, False, "NONE")

    # 2. Client ATR Gating: 220 threshold
    if snap.atr < 220.0:
        return Signal(SignalType.NONE, False, False, "NONE")

    # 3. Trend & Filter Checks
    if not snap.trend_regime or not snap.filters_ok:
        return Signal(SignalType.NONE, False, False, "NONE")

    # 4. Flat / Tangled EMA Gate (Minimum separation required)
    if abs(snap.ema_fast - snap.ema_trend) < (0.05 * snap.atr):
        return Signal(SignalType.NONE, False, False, "NONE")

    # 5. Candle Geometry: Body & Wicks
    body = abs(snap.close - snap.open)
    upper_wick = snap.high - max(snap.open, snap.close)
    lower_wick = min(snap.open, snap.close) - snap.low
    candle_range = snap.high - snap.low

    # 6. Clean Breakout Triggers (Strict Breakout of Previous Extreme)
    long_trigger = (snap.close > snap.prev_high + BREAKOUT_BUFFER_PTS)
    short_trigger = (snap.close < snap.prev_low - BREAKOUT_BUFFER_PTS)

    # LONG: Breakout above prev high, EMA alignment, strong bull body (No Shooting Star)
    if (long_trigger
            and snap.close > snap.ema_fast
            and snap.close > snap.ema_trend
            and snap.dip > snap.dim
            and upper_wick <= body
            and (candle_range > 0 and (snap.close - snap.low) >= 0.60 * candle_range)
            and passes_extension_guard(snap, is_long=True)):
        _last_signal_time = now
        return Signal(SignalType.TREND_LONG, is_long=True, is_trend=True, regime="TREND")

    # SHORT: Breakdown below prev low, EMA alignment, strong bear body (No Hammer)
    if (short_trigger
            and snap.close < snap.ema_fast
            and snap.close < snap.ema_trend
            and snap.dim > snap.dip
            and lower_wick <= body
            and (candle_range > 0 and (snap.high - snap.close) >= 0.60 * candle_range)
            and passes_extension_guard(snap, is_long=False)):
        _last_signal_time = now
        return Signal(SignalType.TREND_SHORT, is_long=False, is_trend=True, regime="TREND")

    return Signal(SignalType.NONE, False, False, "NONE")