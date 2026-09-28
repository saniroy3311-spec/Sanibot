"""
strategy/trend_breakout.py — Shiva Sniper smart trend-breakout profile.

Goals:
- keep early entries (ADX 13 + rising instead of waiting for ADX 20+)
- reject chop using 3-bar box, EMA separation/direction, volume/body quality,
  confirmed 1H EMA direction, and loose market structure
- use loss-based cooldown instead of a fixed long delay after every signal
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from indicators.engine import Signal, SignalType, IndicatorSnapshot
from strategy.guards import passes_extension_guard
from config import (
    ATR_MIN,
    ADX_TREND_TH,
    ADX_REQUIRE_RISING,
    EMA_SEPARATION_ATR_MULT,
    BREAKOUT_BUFFER_PTS,
    FILTER_BODY_MULT,
    FILTER_VOL_ENABLED,
    FILTER_VOL_MULT,
    OPT_HTF_TREND_ENABLED,
    DEAD_ZONE_FILTER_ENABLED,
    DEAD_ZONE_START_HOUR_IST,
    DEAD_ZONE_END_HOUR_IST,
    STRUCTURE_FILTER_ENABLED,
    SIGNAL_COOLDOWN_SEC,
    WIN_COOLDOWN_SEC,
    LOSS_COOLDOWN_BARS,
    CANDLE_TIMEFRAME,
)

_prev_adx = 0.0
_cooldown_until = 0.0
_last_signal_time = 0.0


def _timeframe_seconds(tf: str) -> int:
    tf = str(tf).strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1]) * 60
    if tf.endswith("h"):
        return int(tf[:-1]) * 3600
    if tf.endswith("d"):
        return int(tf[:-1]) * 86400
    return 1800


def notify_trade_exit(was_loss: bool) -> None:
    """Called by main.py after a trade fully closes."""
    global _cooldown_until
    if was_loss:
        delay = LOSS_COOLDOWN_BARS * _timeframe_seconds(CANDLE_TIMEFRAME)
    else:
        delay = WIN_COOLDOWN_SEC
    _cooldown_until = max(_cooldown_until, time.time() + max(0, delay))


def _in_dead_zone() -> bool:
    if not DEAD_ZONE_FILTER_ENABLED:
        return False
    ist_hour = (datetime.utcnow() + timedelta(hours=5, minutes=30)).hour
    start = DEAD_ZONE_START_HOUR_IST % 24
    end = DEAD_ZONE_END_HOUR_IST % 24
    if start < end:
        return start <= ist_hour < end
    return ist_hour >= start or ist_hour < end


def evaluate(snap: IndicatorSnapshot, has_position: bool = False) -> Signal:
    global _prev_adx, _last_signal_time

    if has_position:
        return Signal(SignalType.NONE, False, False, "NONE")

    now = time.time()
    if now < _cooldown_until:
        return Signal(SignalType.NONE, False, False, "COOLDOWN")
    if SIGNAL_COOLDOWN_SEC > 0 and (now - _last_signal_time) < SIGNAL_COOLDOWN_SEC:
        return Signal(SignalType.NONE, False, False, "COOLDOWN")

    if _in_dead_zone():
        return Signal(SignalType.NONE, False, False, "DEAD_ZONE_FILTER")

    # Minimum movement: do not trade dead BTC sessions.
    if snap.atr < ATR_MIN:
        return Signal(SignalType.NONE, False, False, "ATR_LOW")

    # EMA separation prevents the 9/15 pair from trading while tangled.
    ema_gap = abs(snap.ema_fast - snap.ema_trend)
    if ema_gap < EMA_SEPARATION_ATR_MULT * max(snap.atr, 1.0):
        return Signal(SignalType.NONE, False, False, "EMA_TANGLED")

    # ADX must be high enough AND still strengthening.
    curr_adx = float(getattr(snap, "adx", 0.0) or 0.0)
    is_rising = (curr_adx > _prev_adx) if _prev_adx > 0 else True
    _prev_adx = curr_adx
    if curr_adx < float(ADX_TREND_TH):
        return Signal(SignalType.NONE, False, False, "ADX_LOW")
    if ADX_REQUIRE_RISING and not is_rising:
        return Signal(SignalType.NONE, False, False, "ADX_NOT_RISING")

    body = abs(snap.close - snap.open)
    upper_wick = snap.high - max(snap.open, snap.close)
    lower_wick = min(snap.open, snap.close) - snap.low
    candle_range = max(snap.high - snap.low, 0.0)

    body_ok = body >= max(snap.atr, 1.0) * FILTER_BODY_MULT
    volume_ok = (not FILTER_VOL_ENABLED) or (
        snap.volume > 0 and snap.vol_sma > 0 and snap.volume >= snap.vol_sma * FILTER_VOL_MULT
    )
    if not body_ok or not volume_ok or candle_range <= 0:
        return Signal(SignalType.NONE, False, False, "CANDLE_QUALITY")

    box_high = float(getattr(snap, "box_high", snap.prev_high) or snap.prev_high)
    box_low = float(getattr(snap, "box_low", snap.prev_low) or snap.prev_low)
    long_breakout = snap.close > box_high + BREAKOUT_BUFFER_PTS
    short_breakout = snap.close < box_low - BREAKOUT_BUFFER_PTS

    # A large, well-supported expansion candle may start directly out of a box;
    # it should not be rejected just because the PREVIOUS bars were sideways.
    strong_expansion = (
        body >= 0.45 * max(snap.atr, 1.0)
        and (not FILTER_VOL_ENABLED or snap.volume >= snap.vol_sma)
    )
    long_structure_ok = (
        not STRUCTURE_FILTER_ENABLED
        or bool(getattr(snap, "structure_long_ok", True))
        or strong_expansion
    )
    short_structure_ok = (
        not STRUCTURE_FILTER_ENABLED
        or bool(getattr(snap, "structure_short_ok", True))
        or strong_expansion
    )

    htf_long_ok = (not OPT_HTF_TREND_ENABLED) or bool(getattr(snap, "htf_trend_up", False))
    htf_short_ok = (not OPT_HTF_TREND_ENABLED) or bool(getattr(snap, "htf_trend_down", False))

    long_ok = (
        long_breakout
        and htf_long_ok
        and snap.ema_fast > snap.ema_trend
        and snap.close > snap.ema_fast
        and snap.close > snap.ema_trend
        and snap.dip > snap.dim
        and upper_wick <= body
        and (snap.close - snap.low) >= 0.55 * candle_range
        and long_structure_ok
        and passes_extension_guard(snap, is_long=True)
    )

    short_ok = (
        short_breakout
        and htf_short_ok
        and snap.ema_fast < snap.ema_trend
        and snap.close < snap.ema_fast
        and snap.close < snap.ema_trend
        and snap.dim > snap.dip
        and lower_wick <= body
        and (snap.high - snap.close) >= 0.55 * candle_range
        and short_structure_ok
        and passes_extension_guard(snap, is_long=False)
    )

    if long_ok:
        _last_signal_time = now
        return Signal(SignalType.TREND_LONG, is_long=True, is_trend=True, regime="BREAKOUT")

    if short_ok:
        _last_signal_time = now
        return Signal(SignalType.TREND_SHORT, is_long=False, is_trend=True, regime="BREAKOUT")

    # Pullback entry: still allowed, but only with HTF + EMA direction and a
    # clean rejection of the 15 EMA. This gives extra quality trades without
    # opening the floodgates in chop.
    dist_to_ema15 = abs(snap.close - snap.ema_trend)
    if dist_to_ema15 <= 0.35 * max(snap.atr, 1.0):
        if (
            htf_long_ok
            and snap.ema_fast > snap.ema_trend
            and snap.close > snap.open
            and snap.low <= snap.ema_trend
            and snap.close > snap.ema_trend
            and upper_wick <= body
            and long_structure_ok
        ):
            _last_signal_time = now
            return Signal(SignalType.TREND_LONG, is_long=True, is_trend=True, regime="PULLBACK")

        if (
            htf_short_ok
            and snap.ema_fast < snap.ema_trend
            and snap.close < snap.open
            and snap.high >= snap.ema_trend
            and snap.close < snap.ema_trend
            and lower_wick <= body
            and short_structure_ok
        ):
            _last_signal_time = now
            return Signal(SignalType.TREND_SHORT, is_long=False, is_trend=True, regime="PULLBACK")

    return Signal(SignalType.NONE, False, False, "NONE")
