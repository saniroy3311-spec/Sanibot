"""
strategy/trend_breakout.py — Shiva Sniper Bot-v10
Upgraded with Option 4 Dual-Tranche, 6-Bar Donchian Box, 
1H HTF Alignment, ADX Velocity Gate, and Asian Dead-Zone Filter.
"""
from __future__ import annotations
import time
from datetime import datetime, timedelta

from indicators.engine import Signal, SignalType, IndicatorSnapshot
from strategy.guards import passes_extension_guard
from config import BREAKOUT_BUFFER_PTS

_last_signal_time = 0.0
_prev_adx = 0.0
_recent_highs: list[float] = []
_recent_lows: list[float] = []


def evaluate(snap: IndicatorSnapshot, has_position: bool = False) -> Signal:
    global _last_signal_time, _prev_adx, _recent_highs, _recent_lows

    if has_position:
        return Signal(SignalType.NONE, False, False, "NONE")

    now = time.time()
    # 1. 2-Hour Cooldown after trade exit
    if (now - _last_signal_time) < 1800.0:
        return Signal(SignalType.NONE, False, False, "NONE")

    # 2. Asian Dead-Zone Filter: Block entries 02:00 to 07:00 IST
    utc_now = datetime.utcnow()
    ist_hour = (utc_now + timedelta(hours=5, minutes=30)).hour
    if 2 <= ist_hour < 7:
        return Signal(SignalType.NONE, False, False, "DEAD_ZONE_FILTER")

    # 3. Client ATR Minimum Gate: 180.0 threshold
    if snap.atr < 180.0:
        return Signal(SignalType.NONE, False, False, "NONE")

    # 4. Flat / Tangled EMA Gate (0.08x ATR minimum separation required)
    if abs(snap.ema_fast - snap.ema_trend) < (0.08 * snap.atr):
        return Signal(SignalType.NONE, False, False, "NONE")

    # 5. Dynamic ADX Velocity Gate (ADX >= 16.0 and rising)
    curr_adx = getattr(snap, "adx", 25.0)
    is_rising = (curr_adx > _prev_adx) if _prev_adx > 0 else True
    _prev_adx = curr_adx
    if curr_adx < 16.0 or not is_rising:
        return Signal(SignalType.NONE, False, False, "NONE")

    # 6. Track Rolling 6-Bar Consolidation Box (3-Hour Range)
    _recent_highs.append(snap.high)
    _recent_lows.append(snap.low)
    if len(_recent_highs) > 20:
        _recent_highs = _recent_highs[-20:]
        _recent_lows = _recent_lows[-20:]

    if len(_recent_highs) < 7:
        return Signal(SignalType.NONE, False, False, "NONE")

    box_high = max(_recent_highs[-5:-1])
    box_low = min(_recent_lows[-5:-1])

    # 7. Candle Geometry & Wick Guards
    body = abs(snap.close - snap.open)
    upper_wick = snap.high - max(snap.open, snap.close)
    lower_wick = min(snap.open, snap.close) - snap.low
    candle_range = snap.high - snap.low

    # Strategy 1: 6-Bar Donchian Momentum Breakout
    long_breakout = (snap.close > box_high + BREAKOUT_BUFFER_PTS)
    short_breakout = (snap.close < box_low - BREAKOUT_BUFFER_PTS)

    if (long_breakout
            and snap.htf_trend_up > 0.5
            and snap.close > snap.ema_fast
            and snap.close > snap.ema_trend
            and snap.dip > snap.dim
            and upper_wick <= body
            and (candle_range > 0 and (snap.close - snap.low) >= 0.55 * candle_range)
            and passes_extension_guard(snap, is_long=True)):
        _last_signal_time = now
        return Signal(SignalType.TREND_LONG, is_long=True, is_trend=True, regime="BREAKOUT")

    if (short_breakout
            and snap.htf_trend_down > 0.5
            and snap.close < snap.ema_fast
            and snap.close < snap.ema_trend
            and snap.dim > snap.dip
            and lower_wick <= body
            and (candle_range > 0 and (snap.high - snap.close) >= 0.55 * candle_range)
            and passes_extension_guard(snap, is_long=False)):
        _last_signal_time = now
        return Signal(SignalType.TREND_SHORT, is_long=False, is_trend=True, regime="BREAKOUT")

    # Strategy 2: Pullback Dip Retest
    dist_to_ema15 = abs(snap.close - snap.ema_trend)
    if dist_to_ema15 <= (0.35 * snap.atr):
        if (snap.htf_trend_up > 0.5
                and snap.close > snap.open
                and snap.low <= snap.ema_trend
                and snap.close > snap.ema_trend
                and upper_wick <= body):
            _last_signal_time = now
            return Signal(SignalType.TREND_LONG, is_long=True, is_trend=False, regime="PULLBACK")

        if (snap.htf_trend_down > 0.5
                and snap.close < snap.open
                and snap.high >= snap.ema_trend
                and snap.close < snap.ema_trend
                and lower_wick <= body):
            _last_signal_time = now
            return Signal(SignalType.TREND_SHORT, is_long=False, is_trend=False, regime="PULLBACK")

    return Signal(SignalType.NONE, False, False, "NONE")
