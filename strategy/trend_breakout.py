"""
strategy/trend_breakout.py — Shiva Sniper Bot-v10
"""
from __future__ import annotations

from indicators.engine import Signal, SignalType, IndicatorSnapshot
from config import ADX_TREND_TH, BREAKOUT_BUFFER_PTS


def evaluate(snap: IndicatorSnapshot, has_position: bool = False) -> Signal:
    """
    Trend Breakout entry evaluation for a confirmed bar.
    Direction: Price relative to 50 EMA and 200 EMA.
    Extension Guard: <= 1.8x ATR distance from 50 EMA (blocks late chasing).
    """
    if has_position:
        return Signal(SignalType.NONE, False, False, "NONE")

    if not snap.trend_regime or not snap.filters_ok:
        return Signal(SignalType.NONE, False, False, "NONE")

    # Extension distance from 50 EMA
    extension = abs(snap.close - snap.ema_fast) / max(snap.atr, 1.0)
    if extension > 1.8:
        return Signal(SignalType.NONE, False, False, "NONE")

    # LONG: breakout above prev bar high, bull structure
    if (snap.close > snap.prev_high + BREAKOUT_BUFFER_PTS
            and snap.close > snap.ema_fast
            and snap.close > snap.ema_trend
            and snap.dip > snap.dim):
        return Signal(SignalType.TREND_LONG, is_long=True, is_trend=True, regime="TREND")

    # SHORT: breakout below prev bar low, bear structure
    if (snap.close < snap.prev_low - BREAKOUT_BUFFER_PTS
            and snap.close < snap.ema_fast
            and snap.close < snap.ema_trend
            and snap.dim > snap.dip):
        return Signal(SignalType.TREND_SHORT, is_long=False, is_trend=True, regime="TREND")

    return Signal(SignalType.NONE, False, False, "NONE")
