"""
strategy/guards.py — Shiva Sniper Bot-v10

Single source of truth for the EMA-extension + wick guard used by every
entry-evaluation path (indicators/engine.py AND strategy/trend_breakout.py).

Fixed 2026-09-15: trend_breakout.py had drifted to a stale 1.8x/300pt cap
while indicators/engine.py moved to 3.5x + wick guard, causing silent
signal drops. This module exists so that can't happen again — tune the
constants here ONCE and both paths pick it up automatically.
"""

from indicators.engine import IndicatorSnapshot

MAX_EXTENSION = 3.5      # hard cap — beyond this, always reject (too extended)
TIGHT_EXTENSION = 1.8    # below this, no wick check needed
WICK_FRACTION = 0.25     # close must be in the outer 25% of the bar range


def passes_extension_guard(snap: IndicatorSnapshot, is_long: bool) -> bool:
    """
    True if price is not too extended from the 50 EMA to take a fresh
    breakout entry. Direction-aware: for longs, a strong bar closes near
    its high; for shorts, near its low.
    """
    extension = abs(snap.close - snap.ema_fast) / max(snap.atr, 1.0)

    if extension > MAX_EXTENSION:
        return False

    if extension <= TIGHT_EXTENSION:
        return True

    bar_range = snap.high - snap.low
    if is_long:
        return snap.close >= snap.high - WICK_FRACTION * bar_range
    else:
        return snap.close <= snap.low + WICK_FRACTION * bar_range
