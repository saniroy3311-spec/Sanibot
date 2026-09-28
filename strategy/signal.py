"""
strategy/signal.py — strategy selector and shared signal exports.
"""
from indicators.engine import (  # noqa: F401
    evaluate as _evaluate_rsi_bounce,
    SignalType,
    Signal,
    IndicatorSnapshot,
)
from config import ENTRY_STRATEGY


def _noop_notify_trade_exit(was_loss: bool) -> None:
    return None


if ENTRY_STRATEGY == "trend_breakout":
    from strategy.trend_breakout import evaluate as evaluate  # noqa: F401
    from strategy.trend_breakout import notify_trade_exit as notify_trade_exit  # noqa: F401
else:
    evaluate = _evaluate_rsi_bounce  # noqa: F401
    notify_trade_exit = _noop_notify_trade_exit  # noqa: F401
