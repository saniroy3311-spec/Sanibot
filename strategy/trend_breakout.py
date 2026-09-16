"""
strategy/trend_breakout.py — Shiva Sniper Bot-v10
"""
from __future__ import annotations

from indicators.engine import Signal, SignalType, IndicatorSnapshot
from strategy.guards import passes_extension_guard
from config import ADX_TREND_TH, BREAKOUT_BUFFER_PTS


def evaluate(snap: IndicatorSnapshot, has_position: bool = False) -> Signal:
    """
    Trend Breakout entry evaluation for a confirmed bar.
    Direction: Price relative to 50 EMA and 200 EMA.
    Extension Guard: <= 1.8x ATR distance from 50 EMA (blocks late chasing).
    """
    if has_position:
        return Signal(SignalType.NONE, False, False, "NONE")

    if snap.atr < 220.0:
        return Signal(SignalType.NONE, False, False, "NONE")

    if not snap.trend_regime or not snap.filters_ok:
        return Signal(SignalType.NONE, False, False, "NONE")

    # Early Candle 1 Trigger (Breakout of prev extreme OR Reversal across prev midpoint)
    prev_midpoint = (snap.prev_high + snap.prev_low) / 2.0
    long_trigger = (
        snap.close > snap.prev_high + BREAKOUT_BUFFER_PTS
        or (snap.close > snap.open and snap.close > prev_midpoint and (snap.close - snap.open) >= 0.16 * snap.atr)
    )
    short_trigger = (
        snap.close < snap.prev_low - BREAKOUT_BUFFER_PTS
        or (snap.close < snap.open and snap.close < prev_midpoint and (snap.open - snap.close) >= 0.16 * snap.atr)
    )

    # LONG: early candle 1 trigger, bull structure
    if (long_trigger
            and snap.close > snap.ema_fast
            and snap.close > snap.ema_trend
            and snap.dip > snap.dim
            and passes_extension_guard(snap, is_long=True)):
        return Signal(SignalType.TREND_LONG, is_long=True, is_trend=True, regime="TREND")

    # SHORT: early candle 1 trigger, bear structure
    if (short_trigger
            and snap.close < snap.ema_fast
            and snap.close < snap.ema_trend
            and snap.dim > snap.dip
            and passes_extension_guard(snap, is_long=False)):
        return Signal(SignalType.TREND_SHORT, is_long=False, is_trend=True, regime="TREND")

    return Signal(SignalType.NONE, False, False, "NONE")
