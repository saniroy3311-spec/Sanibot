"""
strategy/trend_breakout.py — Shiva Sniper trend-breakout profile.

PINE PARITY BUILD (matches "Sanibot Trend-Breakout — Profit Setup D").

What changed vs the previous version
────────────────────────────────────
P1  ADX_RISING_MODE. Pine offers three rising checks. The old bot only had
    the "stale value" one: it compared ADX against the last value it happened
    to store, which was skipped whenever an earlier gate returned first
    (ATR_LOW / EMA_TANGLED / COOLDOWN) and whenever a position was open.
    After a trade the stored value could be hours old, so the first bar back
    was judged against a stale bar and good breakouts were dropped.
    Now `correct` mode compares this bar's ADX with the PREVIOUS BAR's ADX
    (snap.adx_prev), exactly like Pine's `adx > adx[1]`.

P2  USE_PULLBACK_ENTRIES. Pine has a `usePullback` checkbox; the bot had the
    pullback branch hard-wired on. Now it is .env-controlled.

P3  Extension guard thresholds now come from config (so EXTENSION_MAX_MULT /
    EXTENSION_TIGHT_MULT / WICK_FRACTION in .env actually reach the guard),
    instead of being read once from os.environ at import time in guards.py.

P4  Candle-quality is evaluated BEFORE direction, and `rng > 0` is required,
    matching Pine's `candleOk`. Structure/extension order is unchanged.

Pine reference (sigOk):
    gateOk  = not blocked and atr >= atrMin and |emaF-emaT| >= emaSep*atrS
    sigOk   = gateOk and adx >= adxTh and rising and candleOk and sigDir != 0
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from indicators.engine import Signal, SignalType, IndicatorSnapshot
from strategy.guards import passes_extension_guard
from config import (
    ATR_MIN,
    ADX_TREND_TH,
    ADX_REQUIRE_RISING,
    ADX_RISING_MODE,
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
    USE_PULLBACK_ENTRIES,
    PULLBACK_NEAR_EMA_ATR_MULT,
    SIGNAL_COOLDOWN_SEC,
    WIN_COOLDOWN_SEC,
    LOSS_COOLDOWN_BARS,
    CANDLE_TIMEFRAME,
)

logger = logging.getLogger(__name__)

# Legacy "stale value" tracker — only used when ADX_RISING_MODE=bot.
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
    """Called by main.py after a trade fully closes (Pine: cdUntil from exit_time)."""
    global _cooldown_until
    if was_loss:
        delay = LOSS_COOLDOWN_BARS * _timeframe_seconds(CANDLE_TIMEFRAME)
    else:
        delay = WIN_COOLDOWN_SEC
    _cooldown_until = max(_cooldown_until, time.time() + max(0, delay))


def reset_cooldown() -> None:
    """Manual override hook (Telegram controller / tests)."""
    global _cooldown_until
    _cooldown_until = 0.0


def _in_dead_zone() -> bool:
    if not DEAD_ZONE_FILTER_ENABLED:
        return False
    ist_hour = (datetime.utcnow() + timedelta(hours=5, minutes=30)).hour
    start = DEAD_ZONE_START_HOUR_IST % 24
    end = DEAD_ZONE_END_HOUR_IST % 24
    if start < end:
        return start <= ist_hour < end
    return ist_hour >= start or ist_hour < end


def _adx_is_rising(snap: IndicatorSnapshot) -> bool:
    """
    Pine input "ADX rising check":
      "Off"                      -> always true
      "Correct (adx > adx[1])"   -> this bar's ADX vs PREVIOUS BAR's ADX
      "Bot (stale value)"        -> legacy behaviour, kept for A/B testing
    """
    global _prev_adx

    mode = ADX_RISING_MODE
    curr = float(getattr(snap, "adx", 0.0) or 0.0)

    if mode == "off" or not ADX_REQUIRE_RISING:
        _prev_adx = curr
        return True

    if mode == "bot":
        rising = (curr > _prev_adx) if _prev_adx > 0 else True
        _prev_adx = curr
        return rising

    # "correct" — Pine-exact. adx_prev is the previous CONFIRMED bar's
    # EMA(5)-smoothed ADX, supplied by indicators/engine.py.
    prev = float(getattr(snap, "adx_prev", 0.0) or 0.0)
    _prev_adx = curr
    if prev <= 0:
        return True
    return curr > prev


def evaluate(snap: IndicatorSnapshot, has_position: bool = False) -> Signal:
    global _last_signal_time

    if has_position:
        return Signal(SignalType.NONE, False, False, "NONE")

    now = time.time()
    if now < _cooldown_until:
        return Signal(SignalType.NONE, False, False, "COOLDOWN")
    if SIGNAL_COOLDOWN_SEC > 0 and (now - _last_signal_time) < SIGNAL_COOLDOWN_SEC:
        return Signal(SignalType.NONE, False, False, "COOLDOWN")

    if _in_dead_zone():
        return Signal(SignalType.NONE, False, False, "DEAD_ZONE_FILTER")

    atr_s = max(snap.atr, 1.0)

    # ── Pine gateOk ───────────────────────────────────────────────────────────
    if snap.atr < ATR_MIN:
        return Signal(SignalType.NONE, False, False, "ATR_LOW")

    ema_gap = abs(snap.ema_fast - snap.ema_trend)
    if ema_gap < EMA_SEPARATION_ATR_MULT * atr_s:
        return Signal(SignalType.NONE, False, False, "EMA_TANGLED")

    # ── Pine: adx >= adxTh and rising ─────────────────────────────────────────
    curr_adx = float(getattr(snap, "adx", 0.0) or 0.0)
    is_rising = _adx_is_rising(snap)

    if curr_adx < float(ADX_TREND_TH):
        return Signal(SignalType.NONE, False, False, "ADX_LOW")
    if not is_rising:
        return Signal(SignalType.NONE, False, False, "ADX_NOT_RISING")

    # ── Pine candleOk ─────────────────────────────────────────────────────────
    body = abs(snap.close - snap.open)
    upper_wick = snap.high - max(snap.open, snap.close)
    lower_wick = min(snap.open, snap.close) - snap.low
    candle_range = max(snap.high - snap.low, 0.0)

    body_ok = body >= atr_s * FILTER_BODY_MULT
    volume_ok = (not FILTER_VOL_ENABLED) or (
        snap.volume > 0 and snap.vol_sma > 0 and snap.volume >= snap.vol_sma * FILTER_VOL_MULT
    )
    if not body_ok or not volume_ok or candle_range <= 0:
        return Signal(SignalType.NONE, False, False, "CANDLE_QUALITY")

    # ── Pine longBO / shortBO ─────────────────────────────────────────────────
    box_high = float(getattr(snap, "box_high", snap.prev_high) or snap.prev_high)
    box_low = float(getattr(snap, "box_low", snap.prev_low) or snap.prev_low)
    long_breakout = snap.close > box_high + BREAKOUT_BUFFER_PTS
    short_breakout = snap.close < box_low - BREAKOUT_BUFFER_PTS

    # Pine `strong`: a large, well-supported expansion candle bypasses structure.
    strong_expansion = (
        body >= 0.45 * atr_s
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

    # ── Pine pbLong / pbShort ─────────────────────────────────────────────────
    if not USE_PULLBACK_ENTRIES:
        return Signal(SignalType.NONE, False, False, "NONE")

    dist_to_ema_trend = abs(snap.close - snap.ema_trend)
    if dist_to_ema_trend <= PULLBACK_NEAR_EMA_ATR_MULT * atr_s:
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
