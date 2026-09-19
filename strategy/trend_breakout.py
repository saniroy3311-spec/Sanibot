"""
strategy/trend_breakout.py — Shiva Sniper Bot-v10 / Sanibot (Delta Exchange India)
30m Execution with 1-Hour (1H) 15 EMA Alignment Filter
"""
from __future__ import annotations
import time

from indicators.engine import Signal, SignalType, IndicatorSnapshot
from strategy.guards import passes_extension_guard
from config import ADX_TREND_TH, BREAKOUT_BUFFER_PTS, OPT_HTF_TREND_ENABLED

_last_signal_time = 0.0
_prev_adx = 0.0


def evaluate(snap: IndicatorSnapshot, has_position: bool = False) -> Signal:
    global _last_signal_time, _prev_adx

    if has_position:
        return Signal(SignalType.NONE, False, False, "NONE")

    now = time.time()
    if (now - _last_signal_time) < 1700:
        return Signal(SignalType.NONE, False, False, "NONE")

    if snap.atr < 220.0:
        return Signal(SignalType.NONE, False, False, "NONE")

    # Dynamic ADX Velocity & Rising Momentum Gate
    curr_adx = getattr(snap, "adx", 25.0)
    is_rising = (curr_adx > _prev_adx) if _prev_adx > 0 else True
    _prev_adx = curr_adx
    if curr_adx < 16.0 or not is_rising:
        return Signal(SignalType.NONE, False, False, "NONE")

    # Trend & Filter Checks
    if not snap.trend_regime or not snap.filters_ok:
        return Signal(SignalType.NONE, False, False, "NONE")

    # 1-Hour Higher Timeframe (1H) Alignment Check (15 EMA)
    htf_long_ok = (getattr(snap, "htf_trend_up", 1.0) > 0.5) if OPT_HTF_TREND_ENABLED else True
    htf_short_ok = (getattr(snap, "htf_trend_down", 1.0) > 0.5) if OPT_HTF_TREND_ENABLED else True

    # Flat / Tangled EMA Gate (30m 9 & 15 EMA separation)
    if abs(snap.ema_fast - snap.ema_trend) < (0.05 * snap.atr):
        return Signal(SignalType.NONE, False, False, "NONE")

    # Candle Geometry: Body & Wicks
    body = abs(snap.close - snap.open)
    upper_wick = snap.high - max(snap.open, snap.close)
    lower_wick = min(snap.open, snap.close) - snap.low
    candle_range = snap.high - snap.low

    long_trigger = (snap.close > snap.prev_high + BREAKOUT_BUFFER_PTS)
    short_trigger = (snap.close < snap.prev_low - BREAKOUT_BUFFER_PTS)

    # LONG: 30m breakout + 30m 9/15 EMA alignment + 1-Hour 15 EMA confirmation
    if (long_trigger
            and htf_long_ok
            and snap.close > snap.ema_fast
            and snap.close > snap.ema_trend
            and snap.dip > snap.dim
            and upper_wick <= body
            and (candle_range > 0 and (snap.close - snap.low) >= 0.60 * candle_range)
            and passes_extension_guard(snap, is_long=True)):
        _last_signal_time = now
        return Signal(SignalType.TREND_LONG, is_long=True, is_trend=True, regime="TREND")

    # SHORT: Breakdown below prev low, 30m EMA alignment, 1H HTF confirmation
    if (short_trigger
            and htf_short_ok
            and snap.close < snap.ema_fast
            and snap.close < snap.ema_trend
            and snap.dim > snap.dip
            and lower_wick <= body
            and (candle_range > 0 and (snap.high - snap.close) >= 0.60 * candle_range)
            and passes_extension_guard(snap, is_long=False)):
        _last_signal_time = now
        return Signal(SignalType.TREND_SHORT, is_long=False, is_trend=True, regime="TREND")

    return Signal(SignalType.NONE, False, False, "NONE")
