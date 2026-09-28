"""
strategy/guards.py — shared entry guards for Shiva Sniper.

The extension ceiling is now controlled from .env so a strong breakout can
still be taken, while very late/FOMO entries are rejected.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from indicators.engine import IndicatorSnapshot

MAX_EXTENSION = float(os.environ.get("EXTENSION_MAX_MULT", "2.2"))
TIGHT_EXTENSION = float(os.environ.get("TIGHT_EXTENSION_MULT", "1.8"))
WICK_FRACTION = float(os.environ.get("WICK_FRACTION", "0.25"))


def passes_extension_guard(snap: "IndicatorSnapshot", is_long: bool) -> bool:
    """
    Reject entries that are too far from the fast EMA.

    Up to TIGHT_EXTENSION x ATR: accept without an extra close-location test.
    Between TIGHT_EXTENSION and MAX_EXTENSION: require the candle to close near
    the favourable edge of its range. Above MAX_EXTENSION: reject as too late.
    """
    extension = abs(snap.close - snap.ema_fast) / max(snap.atr, 1.0)

    if extension > MAX_EXTENSION:
        return False

    if extension <= TIGHT_EXTENSION:
        return True

    bar_range = max(snap.high - snap.low, 0.0)
    if bar_range <= 0:
        return False

    if is_long:
        return snap.close >= snap.high - WICK_FRACTION * bar_range
    return snap.close <= snap.low + WICK_FRACTION * bar_range
