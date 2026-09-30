"""
strategy/guards.py — shared entry guards for Shiva Sniper.

PINE PARITY BUILD.

Old behaviour read EXTENSION_MAX_MULT / TIGHT_EXTENSION_MULT / WICK_FRACTION
straight from os.environ at import time, using key names that did not match
the ones config.py exposes. Result: the Pine inputs "Extension tight x ATR"
and "Extension close-near-edge fraction" were effectively hard-coded and could
not be tuned from .env. They now come from config.py, single source of truth.

Pine reference:
    extension = |close - emaF| / atrS
    extOkL = extension <= extTight
             or (extension <= extMax and rng > 0 and close >= high - wickFrac*rng)
    extOkS = extension <= extTight
             or (extension <= extMax and rng > 0 and close <= low  + wickFrac*rng)
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from config import (
    EXTENSION_MAX_MULT,
    EXTENSION_TIGHT_MULT,
    EXTENSION_WICK_FRACTION,
)

if TYPE_CHECKING:
    from indicators.engine import IndicatorSnapshot


def passes_extension_guard(snap: "IndicatorSnapshot", is_long: bool) -> bool:
    """
    Reject entries that are too far from the fast EMA.

    <= EXTENSION_TIGHT_MULT x ATR : accept, no extra test.
    tight..EXTENSION_MAX_MULT     : accept only if the candle closed near the
                                    favourable edge of its own range.
    > EXTENSION_MAX_MULT          : reject as a late/FOMO entry.
    """
    extension = abs(snap.close - snap.ema_fast) / max(snap.atr, 1.0)

    if extension <= EXTENSION_TIGHT_MULT:
        return True

    if extension > EXTENSION_MAX_MULT:
        return False

    bar_range = max(snap.high - snap.low, 0.0)
    if bar_range <= 0:
        return False

    if is_long:
        return snap.close >= snap.high - EXTENSION_WICK_FRACTION * bar_range
    return snap.close <= snap.low + EXTENSION_WICK_FRACTION * bar_range
