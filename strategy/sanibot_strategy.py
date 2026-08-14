"""
Sanibot Event-Driven Strategy for Backtesting Framework.

Adapts Sanibot's entry conditions (trend breakout + RSI bounce)
and dynamic trailing stop-loss into an event-driven strategy.

Key features:
- Dual strategy: trend_breakout / rsi_bounce
- 5-stage trailing stop with breakeven
- Bar-close SL evaluation (BAR_CLOSE_SL_EVAL)
- Wick filters: MAX_DELTA_TICK_JUMP, streak recovery, stale timeout
- Offset recalibration freeze post-trail-arm (FIX-5)
- Signal types: TREND_LONG/SHORT, RANGE_LONG/SHORT, reversal handling
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from enum import Enum

from events import (
    MarketEvent, SignalEvent, OrderEvent, FillEvent,
    SignalType, OrderSide, OrderType, FillType,
)
from portfolio import Portfolio
from execution import SimulatedBroker, ExchangeConfig, DEFAULT_EXCHANGES

# Import Sanibot's indicator and risk modules
from indicators.engine import (
    IndicatorSnapshot,
    evaluate as rsi_bounce_evaluate,
    Signal as IndicatorSignal,
    SignalType as IndicatorSignalType,
)
from risk.calculator import RiskLevels, TrailState, calc_levels, calc_trail_stage
from strategy.trend_breakout import evaluate as trend_breakout_evaluate

logger = logging.getLogger(__name__)


class StrategyMode(Enum):
    """Strategy operating mode."""
    TREND_BREAKOUT = "trend_breakout"
    RSI_BOUNCE = "rsi_bounce"


@dataclass
class StrategyConfig:
    """Configuration for Sanibot strategy.

    Default values are Pine Script parity values from Sanibot v10.
    These can be overridden by config.json when creating the strategy.
    """
    mode: StrategyMode = StrategyMode.RSI_BOUNCE
    symbol: str = "BTC/USD"
    timeframe: str = "30m"

    # Risk management
    risk_per_trade: float = 0.02      # 2% risk per trade
    max_positions: int = 1            # Max concurrent positions

    # Trailing stop (Pine-exact from TradingView Inputs panel)
    trail_stages: List[tuple] = field(default_factory=lambda: [
        (0.8,  0.50, 0.40),   # Stage 1
        (1.5,  0.40, 0.30),   # Stage 2
        (2.5,  0.30, 0.25),   # Stage 3
        (4.0,  0.20, 0.15),   # Stage 4
        (6.0,  0.15, 0.10),   # Stage 5
    ])
    pine_mintick: float = 0.5

    # Bar-close SL evaluation (Pine calc_on_every_tick=false parity)
    bar_close_sl_eval: bool = True

    # Wick filters
    max_delta_tick_jump: float = 3.0
    streak_recovery: int = 3
    stale_timeout: int = 30

    # Exchange
    exchange_name: str = "delta"
    commission_per_lot: float = 0.0
    slippage_ticks: float = 1.0

    # Indicators (Pine-exact lengths)
    ema_fast_len: int = 50
    ema_trend_len: int = 200
    rsi_len: int = 14
    adx_len: int = 14
    dmi_len: int = 14
    atr_len: int = 14
    adx_trend_th: float = 22.0


class SanibotStrategy:
    """
    Event-driven Sanibot strategy for backtesting.

    Processes MarketEvents and generates SignalEvents/Orders.
    Maintains trailing stop state and handles dynamic SL updates.
    """

    def __init__(
        self,
        config: StrategyConfig,
        portfolio: Portfolio,
        broker: SimulatedBroker,
    ):
        self.config = config
        self.portfolio = portfolio
        self.broker = broker

        # Strategy state
        self.current_bar: Optional[MarketEvent] = None
        self.indicator_snapshot: Optional[IndicatorSnapshot] = None

        # Position tracking per symbol
        self.trail_states: Dict[str, TrailState] = {}
        self.risk_levels: Dict[str, RiskLevels] = {}
        self.entry_bar_boundaries: Dict[str, int] = {}

        # Indicators
        self._ema_fast_values: List[float] = []
        self._ema_trend_values: List[float] = []
        self._rsi_values: List[float] = []
        self._adx_values: List[float] = []
        self._di_plus_values: List[float] = []
        self._di_minus_values: List[float] = []
        self._atr_values: List[float] = []
        self._close_values: List[float] = []
        self._high_values: List[float] = []
        self._low_values: List[float] = []

        # Bar tracking
        self.bar_count = 0

        # Events generated
        self.pending_signals: List[SignalEvent] = []
        self.pending_orders: List[OrderEvent] = []

        logger.info(f"SanibotStrategy initialized: mode={config.mode.value}, symbol={config.symbol}")

    def on_market_event(self, market_event: MarketEvent) -> List[SignalEvent]:
        """
        Process a new market bar.

        This is the main entry point for the event-driven backtest.
        Updates indicators, checks trailing stops, evaluates entries.
        """
        self.current_bar = market_event
        self.bar_count += 1

        # Update indicator series
        self._update_indicators(market_event)

        # First, check trailing stops for existing positions (intrabar)
        if self.config.bar_close_sl_eval:
            # Only evaluate SL at bar close - skip intrabar
            pass
        else:
            # Evaluate trailing stop intrabar (using bar high/low as proxy)
            self._check_trailing_stops_intrabar(market_event)

        # Compute indicator snapshot for this bar
        self.indicator_snapshot = self._compute_indicator_snapshot(market_event)

        # Check for exit conditions (bar-close evaluation)
        self._check_bar_close_exits(market_event)

        # Evaluate entry signals (only if not in position)
        signals = self._evaluate_entries(market_event)

        # Update trail state if in position
        if self.indicator_snapshot and market_event.symbol in self.trail_states:
            self._update_trail_state(market_event)

        return signals

    def _update_indicators(self, market_event: MarketEvent):
        """Update indicator values with new bar data."""
        self._close_values.append(market_event.close)
        self._high_values.append(market_event.high)
        self._low_values.append(market_event.low)

        # Keep only needed history
        max_len = max(
            self.config.ema_fast_len,
            self.config.ema_trend_len,
            self.config.rsi_len,
            self.config.adx_len,
            self.config.dmi_len,
            self.config.atr_len,
        ) + 10

        if len(self._close_values) > max_len:
            self._close_values = self._close_values[-max_len:]
            self._high_values = self._high_values[-max_len:]
            self._low_values = self._low_values[-max_len:]

    def _compute_indicator_snapshot(self, market_event: MarketEvent) -> IndicatorSnapshot:
        """Compute all indicators for current bar."""
        import pandas as pd
        from indicators.engine import (
            compute_ema, compute_rsi, compute_adx_dmi, compute_atr
        )

        # Need enough data
        min_bars = max(
            self.config.ema_trend_len,
            self.config.rsi_len,
            self.config.adx_len,
            self.config.atr_len,
        )

        if len(self._close_values) < min_bars:
            # Not enough data - return empty snapshot
            return IndicatorSnapshot(
                timestamp=market_event.timestamp,
                close=market_event.close,
                high=market_event.high,
                low=market_event.low,
                prev_high=market_event.prev_high,
                prev_low=market_event.prev_low,
                ema_fast=0.0,
                ema_trend=0.0,
                rsi=50.0,
                adx=0.0,
                dip=0.0,
                dim=0.0,
                atr=market_event.high - market_event.low,  # Approximation
                trend_regime=False,
                range_regime=False,
                filters_ok=True,
            )

        # Convert lists to pandas Series for indicator functions
        close_series = pd.Series(self._close_values)
        high_series = pd.Series(self._high_values)
        low_series = pd.Series(self._low_values)

        # Compute indicators
        ema_fast = float(compute_ema(close_series, self.config.ema_fast_len).iloc[-1])
        ema_trend = float(compute_ema(close_series, self.config.ema_trend_len).iloc[-1])
        rsi_series = compute_rsi(close_series, self.config.rsi_len)
        rsi = float(rsi_series.iloc[-1])
        adx, dip, dim = compute_adx_dmi(
            high_series, low_series, close_series,
            self.config.adx_len, self.config.dmi_len, 5
        )
        atr_series = compute_atr(
            high_series, low_series, close_series,
            self.config.atr_len
        )
        atr = float(atr_series.iloc[-1])

        # Regime detection
        trend_regime = adx > self.config.adx_trend_th
        range_regime = not trend_regime and rsi >= 40 and rsi <= 60

        # Bar-close evaluation filters (from monitor/trail_loop.py)
        filters_ok = self._check_bar_close_filters(market_event, adx, rsi, dip, dim)

        return IndicatorSnapshot(
            timestamp=market_event.timestamp,
            close=market_event.close,
            high=market_event.high,
            low=market_event.low,
            prev_high=market_event.prev_high,
            prev_low=market_event.prev_low,
            ema_fast=ema_fast,
            ema_trend=ema_trend,
            rsi=rsi,
            adx=adx,
            dip=dip,
            dim=dim,
            atr=atr,
            trend_regime=trend_regime,
            range_regime=range_regime,
            filters_ok=filters_ok,
        )

    def _check_bar_close_filters(
        self,
        market_event: MarketEvent,
        adx: float,
        rsi: float,
        dip: float,
        dim: float
    ) -> bool:
        """Check bar-close evaluation filters (from trail_loop.py)."""
        # MAX_DELTA_TICK_JUMP filter
        if market_event.prev_high and market_event.prev_low:
            prev_range = market_event.prev_high - market_event.prev_low
            if prev_range > 0:
                current_range = market_event.high - market_event.low
                range_ratio = current_range / prev_range
                if range_ratio > self.config.max_delta_tick_jump:
                    return False

        # STREAK_RECOVERY - check if too many consecutive failed breaks
        # Simplified: track in strategy state if needed
        # STALE_TIMEOUT - not applicable in backtest (no real-time)

        return True

    def _evaluate_entries(self, market_event: MarketEvent) -> List[SignalEvent]:
        """Evaluate entry signals based on strategy mode."""
        signals = []

        if not self.indicator_snapshot:
            return signals

        symbol = market_event.symbol
        position = self.portfolio.get_position(symbol)

        # Skip if already in position
        from portfolio import PositionSide
        if position.side != PositionSide.FLAT:
            return signals

        # Select evaluation function based on mode
        if self.config.mode == StrategyMode.TREND_BREAKOUT:
            sig = trend_breakout_evaluate(self.indicator_snapshot, has_position=False)
        else:
            sig = rsi_bounce_evaluate(self.indicator_snapshot, has_position=False)

        if sig.signal_type == IndicatorSignalType.NONE:
            return signals

        # Convert to our SignalEvent
        signal_event = SignalEvent(
            timestamp=market_event.timestamp,
            symbol=symbol,
            signal_type=SignalType(sig.signal_type.value),
            is_long=sig.is_long,
            is_trend=sig.is_trend,
            regime=sig.regime,
            price=market_event.close,
            atr=self.indicator_snapshot.atr,
            strength=1.0,
            metadata={
                'ema_fast': self.indicator_snapshot.ema_fast,
                'ema_trend': self.indicator_snapshot.ema_trend,
                'rsi': self.indicator_snapshot.rsi,
                'adx': self.indicator_snapshot.adx,
                'dip': self.indicator_snapshot.dip,
                'dim': self.indicator_snapshot.dim,
            }
        )

        signals.append(signal_event)
        self.pending_signals.append(signal_event)

        logger.info(
            f"Signal generated: {signal_event.signal_type.value} {symbol} "
            f"close={market_event.close:.2f} atr={self.indicator_snapshot.atr:.2f}"
        )

        return signals

    def _check_trailing_stops_intrabar(self, market_event: MarketEvent):
        """Check trailing stop using bar high/low as intrabar proxy."""
        symbol = market_event.symbol
        if symbol not in self.trail_states:
            return

        trail_state = self.trail_states[symbol]
        risk = self.risk_levels.get(symbol)

        if not risk:
            return

        # Use high/low as intrabar price check
        # For long: check if low hit trail SL
        # For short: check if high hit trail SL
        is_long = risk.is_long

        if is_long:
            # Check if low price hit trailing SL
            if trail_state.current_sl > 0 and market_event.low <= trail_state.current_sl:
                self._trigger_exit(market_event, symbol, "Trail SL (intrabar)", trail_state.current_sl)
        else:
            # Check if high price hit trailing SL
            if trail_state.current_sl > 0 and market_event.high >= trail_state.current_sl:
                self._trigger_exit(market_event, symbol, "Trail SL (intrabar)", trail_state.current_sl)

    def _check_bar_close_exits(self, market_event: MarketEvent):
        """Check exit conditions at bar close."""
        symbol = market_event.symbol

        # Check TP hit
        if symbol in self.risk_levels:
            risk = self.risk_levels[symbol]
            is_long = risk.is_long

            if is_long and market_event.high >= risk.tp:
                self._trigger_exit(market_event, symbol, "Take Profit", risk.tp)
            elif not is_long and market_event.low <= risk.tp:
                self._trigger_exit(market_event, symbol, "Take Profit", risk.tp)

            # Check initial SL (if trail not improved)
            if symbol in self.trail_states:
                trail_state = self.trail_states[symbol]
                if trail_state.current_sl > 0:
                    # Check if it's still at initial SL (not improved by trail or BE)
                    sl_improved = (is_long and trail_state.current_sl > risk.sl) or \
                                  (not is_long and trail_state.current_sl < risk.sl)
                    be_at_entry = trail_state.be_done and abs(trail_state.current_sl - risk.entry_price) < 1e-6

                    if not sl_improved and not be_at_entry:
                        # Still at initial SL
                        if is_long and market_event.low <= risk.sl:
                            self._trigger_exit(market_event, symbol, "Initial SL", risk.sl)
                        elif not is_long and market_event.high >= risk.sl:
                            self._trigger_exit(market_event, symbol, "Initial SL", risk.sl)
                    else:
                        # Check trailing SL at bar close
                        if is_long and market_event.close <= trail_state.current_sl:
                            self._trigger_exit(market_event, symbol, f"Trail S{trail_state.stage}", trail_state.current_sl)
                        elif not is_long and market_event.close >= trail_state.current_sl:
                            self._trigger_exit(market_event, symbol, f"Trail S{trail_state.stage}", trail_state.current_sl)

    def _update_trail_state(self, market_event: MarketEvent):
        """Update trailing stop state based on current bar."""
        symbol = market_event.symbol
        if symbol not in self.trail_states or symbol not in self.risk_levels:
            return

        trail_state = self.trail_states[symbol]
        risk = self.risk_levels[symbol]
        is_long = risk.is_long
        atr = self.indicator_snapshot.atr
        entry_price = risk.entry_price

        # Calculate peak profit distance
        if is_long:
            trail_state.peak_price = max(trail_state.peak_price, market_event.high)
            peak_profit_dist = max(0.0, trail_state.peak_price - entry_price)
        else:
            trail_state.peak_price = min(trail_state.peak_price, market_event.low)
            peak_profit_dist = max(0.0, entry_price - trail_state.peak_price)

        # Check breakeven trigger (bar-close only)
        current_profit_dist = market_event.close - entry_price if is_long else entry_price - market_event.close
        from risk.calculator import should_trigger_be
        if not trail_state.be_done and should_trigger_be(current_profit_dist, atr):
            trail_state.be_done = True
            be_improves = (is_long and entry_price > trail_state.current_sl) or \
                          (not is_long and entry_price < trail_state.current_sl)
            if be_improves:
                trail_state.current_sl = entry_price
                logger.info(f"Breakeven activated for {symbol}: SL moved to entry {entry_price:.2f}")

        # Upgrade trail stage
        from risk.calculator import upgrade_trail_stage, compute_trail_sl
        new_stage = upgrade_trail_stage(trail_state.stage, peak_profit_dist, atr)
        if new_stage > trail_state.stage:
            trail_state.stage = new_stage
            logger.info(f"Trail stage upgraded for {symbol}: S{trail_state.stage}")

        # Compute new trailing SL
        trail_sl = compute_trail_sl(
            trail_state.stage, trail_state.peak_price, peak_profit_dist,
            is_long, atr
        )
        if trail_sl is not None:
            improves = (is_long and trail_sl > trail_state.current_sl) or \
                       (not is_long and trail_sl < trail_state.current_sl)
            if improves:
                trail_state.current_sl = trail_sl
                logger.debug(f"Trail SL updated for {symbol}: {trail_sl:.2f} (stage {trail_state.stage})")

    def _trigger_exit(self, market_event: MarketEvent, symbol: str, reason: str, exit_price: float):
        """Trigger an exit for the position."""
        position = self.portfolio.get_position(symbol)
        if position.side == position.side.FLAT:
            return

        # Cancel any existing SL/TP orders
        self.broker.cancel_all_orders(symbol)

        # Create exit order
        is_long = position.side == position.side.LONG
        exit_order = OrderEvent(
            timestamp=market_event.timestamp,
            symbol=symbol,
            order_id=f"exit_{uuid.uuid4().hex[:8]}",
            side=OrderSide.SELL if is_long else OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=abs(position.quantity),
            metadata={
                'fill_type': FillType.TRAIL_SL.value if 'Trail' in reason else FillType.SL.value,
                'exit_reason': reason,
                'exit_price': exit_price,
            }
        )

        self.broker.submit_order(exit_order)
        self.pending_orders.append(exit_order)

        # Clear trail state
        if symbol in self.trail_states:
            del self.trail_states[symbol]
        if symbol in self.risk_levels:
            del self.risk_levels[symbol]
        if symbol in self.entry_bar_boundaries:
            del self.entry_bar_boundaries[symbol]

        logger.info(f"Exit triggered: {symbol} {reason} @ {exit_price:.2f}")

    def on_fill(self, fill: FillEvent):
        """Handle fill event - update strategy state."""
        symbol = fill.symbol

        if fill.fill_type == FillType.ENTRY:
            self._on_entry_fill(fill)
        elif fill.fill_type in (FillType.SL, FillType.TP, FillType.TRAIL_SL, FillType.BREAKEVEN):
            self._on_exit_fill(fill)

    def _on_entry_fill(self, fill: FillEvent):
        """Handle entry fill - initialize risk levels and trail state."""
        symbol = fill.symbol
        is_long = fill.side == OrderSide.BUY
        entry_price = fill.price
        atr = fill.metadata.get('atr', 0) or self.indicator_snapshot.atr if self.indicator_snapshot else 0

        # Determine if trend or range from signal metadata
        is_trend = fill.metadata.get('signal_type', '').startswith('TREND')

        # Calculate risk levels
        risk = calc_levels(entry_price, atr, is_long, is_trend)

        # Initialize trail state
        trail_state = TrailState(
            stage=0,
            current_sl=risk.sl,
            peak_price=entry_price,
        )

        # Set entry bar boundary (for max SL check - skip on entry bar)
        entry_bar_boundary = self._get_bar_boundary(fill.timestamp)

        self.risk_levels[symbol] = risk
        self.trail_states[symbol] = trail_state
        self.entry_bar_boundaries[symbol] = entry_bar_boundary

        # Create SL/TP orders
        sl_tp_orders = self._create_sl_tp_orders(symbol, is_long, entry_price, fill.quantity, risk.sl, risk.tp, fill.timestamp)
        for order in sl_tp_orders:
            self.broker.submit_order(order)
            self.pending_orders.append(order)

        logger.info(
            f"Entry filled: {symbol} {'LONG' if is_long else 'SHORT'} "
            f"entry={entry_price:.2f} sl={risk.sl:.2f} tp={risk.tp:.2f} "
            f"atr={atr:.2f} qty={fill.quantity}"
        )

    def _on_exit_fill(self, fill: FillEvent):
        """Handle exit fill - clean up state."""
        symbol = fill.symbol

        # Clear state
        if symbol in self.trail_states:
            del self.trail_states[symbol]
        if symbol in self.risk_levels:
            del self.risk_levels[symbol]
        if symbol in self.entry_bar_boundaries:
            del self.entry_bar_boundaries[symbol]

        logger.info(f"Exit filled: {symbol} {fill.fill_type.value} @ {fill.price:.2f}")

    def _create_sl_tp_orders(
        self,
        symbol: str,
        is_long: bool,
        entry_price: float,
        quantity: float,
        sl_price: float,
        tp_price: float,
        timestamp: int,
    ) -> List[OrderEvent]:
        """Create stop loss and take profit orders."""
        # Round prices to tick size to avoid validation errors
        tick_size = self.config.pine_mintick
        sl_price = round(sl_price / tick_size) * tick_size
        tp_price = round(tp_price / tick_size) * tick_size

        orders = []

        # Stop loss
        sl_order = OrderEvent(
            timestamp=timestamp,
            symbol=symbol,
            order_id=f"sl_{uuid.uuid4().hex[:6]}",
            side=OrderSide.SELL if is_long else OrderSide.BUY,
            order_type=OrderType.STOP,
            quantity=quantity,
            stop_price=sl_price,
            metadata={
                'fill_type': FillType.SL.value,
                'parent_fill_type': FillType.ENTRY.value,
            }
        )
        orders.append(sl_order)

        # Take profit
        tp_order = OrderEvent(
            timestamp=timestamp,
            symbol=symbol,
            order_id=f"tp_{uuid.uuid4().hex[:6]}",
            side=OrderSide.SELL if is_long else OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            price=tp_price,
            metadata={
                'fill_type': FillType.TP.value,
                'parent_fill_type': FillType.ENTRY.value,
            }
        )
        orders.append(tp_order)

        return orders

    def _get_bar_boundary(self, timestamp: int) -> int:
        """Get bar boundary timestamp for timeframe."""
        tf = self.config.timeframe
        if tf.endswith('m'):
            minutes = int(tf[:-1])
            ms_per_bar = minutes * 60 * 1000
        elif tf.endswith('h'):
            hours = int(tf[:-1])
            ms_per_bar = hours * 3600 * 1000
        else:
            ms_per_bar = 30 * 60 * 1000  # default 30m

        return (timestamp // ms_per_bar) * ms_per_bar

    def get_state(self) -> Dict[str, Any]:
        """Get current strategy state for monitoring."""
        return {
            'bar_count': self.bar_count,
            'current_bar': self.current_bar.datetime if self.current_bar else None,
            'positions': {
                symbol: {
                    'side': pos.side.value,
                    'quantity': pos.quantity,
                    'entry_price': pos.entry_price,
                    'trail_sl': self.trail_states.get(symbol, TrailState()).current_sl,
                    'trail_stage': self.trail_states.get(symbol, TrailState()).stage,
                    'peak_price': self.trail_states.get(symbol, TrailState()).peak_price,
                    'be_done': self.trail_states.get(symbol, TrailState()).be_done,
                }
                for symbol, pos in self.portfolio.positions.items()
                if pos.side != pos.side.FLAT
            },
            'indicators': self.indicator_snapshot.__dict__ if self.indicator_snapshot else None,
        }


# Convenience function to create strategy from config dict
def create_sanibot_strategy(
    config_dict: Dict,
    portfolio: Portfolio,
    broker: SimulatedBroker,
) -> SanibotStrategy:
    """Factory function to create SanibotStrategy from config dict."""
    config = StrategyConfig(
        mode=StrategyMode(config_dict.get('mode', 'rsi_bounce')),
        symbol=config_dict.get('symbol', 'BTC/USD'),
        timeframe=config_dict.get('timeframe', '30m'),
        risk_per_trade=config_dict.get('risk_per_trade', 0.02),
        max_positions=config_dict.get('max_positions', 1),
        exchange_name=config_dict.get('exchange', 'delta'),
        commission_per_lot=config_dict.get('commission_per_lot', 0.0),
        slippage_ticks=config_dict.get('slippage_ticks', 1.0),
    )
    return SanibotStrategy(config, portfolio, broker)