"""
Portfolio management for the Sanibot backtesting framework.

Handles capital management, position tracking, equity curve generation,
and state updates from FillEvents.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum
from collections import defaultdict

from events import FillEvent, OrderSide, FillType, SignalType

logger = logging.getLogger(__name__)


class PositionSide(Enum):
    """Current position side."""
    FLAT = "flat"
    LONG = "long"
    SHORT = "short"


@dataclass
class Position:
    """Represents an open position."""
    symbol: str
    side: PositionSide
    quantity: float = 0.0          # Position size in lots
    entry_price: float = 0.0       # Average entry price
    entry_timestamp: int = 0       # Entry timestamp (ms)
    unrealized_pnl: float = 0.0    # Current unrealized P&L
    realized_pnl: float = 0.0      # Realized P&L from partial closes
    commission_paid: float = 0.0   # Total commission paid
    max_favorable: float = 0.0     # Max favorable excursion
    max_adverse: float = 0.0       # Max adverse excursion
    trail_sl: Optional[float] = None      # Current trailing stop
    initial_sl: Optional[float] = None    # Initial stop loss
    tp_price: Optional[float] = None      # Take profit price
    trail_activated: bool = False         # Whether trail is armed
    best_price: Optional[float] = None    # Best price since trail armed
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.side == PositionSide.LONG and self.quantity < 0:
            self.quantity = abs(self.quantity)
        elif self.side == PositionSide.SHORT and self.quantity > 0:
            self.quantity = -abs(self.quantity)

    @property
    def is_long(self) -> bool:
        return self.side == PositionSide.LONG

    @property
    def is_short(self) -> bool:
        return self.side == PositionSide.SHORT

    @property
    def notional_value(self) -> float:
        """Current notional value of position."""
        return abs(self.quantity) * self.entry_price

    def update_unrealized_pnl(self, current_price: float, point_value: float = 0.001):
        """Update unrealized P&L based on current price."""
        if self.is_long:
            points = current_price - self.entry_price
        else:
            points = self.entry_price - current_price
        self.unrealized_pnl = points * abs(self.quantity) * point_value

        # Update max favorable/adverse
        if self.unrealized_pnl > self.max_favorable:
            self.max_favorable = self.unrealized_pnl
        if self.unrealized_pnl < self.max_adverse:
            self.max_adverse = self.unrealized_pnl

    def check_sl_tp(self, current_price: float) -> Optional[str]:
        """Check if stop loss or take profit is hit. Returns hit type or None."""
        if self.is_long:
            if self.trail_sl and current_price <= self.trail_sl:
                return "trail_sl"
            if self.initial_sl and current_price <= self.initial_sl:
                return "initial_sl"
            if self.tp_price and current_price >= self.tp_price:
                return "tp"
        else:  # SHORT
            if self.trail_sl and current_price >= self.trail_sl:
                return "trail_sl"
            if self.initial_sl and current_price >= self.initial_sl:
                return "initial_sl"
            if self.tp_price and current_price <= self.tp_price:
                return "tp"
        return None


@dataclass
class EquityPoint:
    """Single point on the equity curve."""
    timestamp: int
    equity: float
    cash: float
    position_value: float
    unrealized_pnl: float
    drawdown: float
    drawdown_pct: float


@dataclass
class Trade:
    """Completed trade record for analysis."""
    symbol: str
    side: PositionSide
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    commission: float
    net_pnl: float
    pnl_points: float
    fill_type: FillType
    duration_ms: int
    max_favorable: float
    max_adverse: float
    bars_held: int = 0


class Portfolio:
    """
    Portfolio manager for backtesting.

    Tracks:
    - Cash balance and equity
    - Open positions per symbol
    - Trade history
    - Equity curve
    - Performance metrics
    """

    def __init__(
        self,
        initial_cash: float = 100_000.0,
        point_value: float = 0.001,       # USD per point per lot (Delta spec)
        commission_per_lot: float = 0.0,  # Commission per lot per side
        slippage_ticks: float = 0.0,      # Slippage in ticks per fill
        tick_size: float = 0.5,           # Minimum tick size
        max_position_lots: float = 1000.0,
    ):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.point_value = point_value
        self.commission_per_lot = commission_per_lot
        self.slippage_ticks = slippage_ticks
        self.tick_size = tick_size
        self.max_position_lots = max_position_lots

        # Positions: symbol -> Position
        self.positions: Dict[str, Position] = {}

        # Trade history
        self.trades: List[Trade] = []

        # Equity curve
        self.equity_curve: List[EquityPoint] = []
        self._peak_equity = initial_cash

        # Performance tracking
        self.total_commission = 0.0
        self.total_slippage = 0.0
        self.total_realized_pnl = 0.0
        self.num_trades = 0
        self.num_wins = 0
        self.num_losses = 0
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0

        # Per-symbol stats
        self.symbol_stats: Dict[str, Dict] = defaultdict(lambda: {
            'trades': 0, 'wins': 0, 'losses': 0,
            'total_pnl': 0.0, 'total_commission': 0.0
        })

    def get_position(self, symbol: str) -> Position:
        """Get or create position for symbol."""
        if symbol not in self.positions:
            self.positions[symbol] = Position(symbol=symbol, side=PositionSide.FLAT)
        return self.positions[symbol]

    def get_equity(self, current_prices: Dict[str, float]) -> float:
        """Calculate total equity (cash + position values)."""
        equity = self.cash
        for symbol, position in self.positions.items():
            if position.side != PositionSide.FLAT and position.quantity != 0:
                price = current_prices.get(symbol, position.entry_price)
                if position.is_long:
                    equity += position.quantity * price * self.point_value
                else:
                    equity += position.quantity * price * self.point_value  # negative for short
        return equity

    def update_equity(self, timestamp: int, current_prices: Dict[str, float]):
        """Update equity curve with current prices."""
        # Update unrealized P&L for all positions
        position_value = 0.0
        total_unrealized = 0.0

        for symbol, position in self.positions.items():
            if position.side != PositionSide.FLAT and position.quantity != 0:
                price = current_prices.get(symbol, position.entry_price)
                position.update_unrealized_pnl(price, self.point_value)
                total_unrealized += position.unrealized_pnl
                position_value += abs(position.quantity) * price * self.point_value

        equity = self.cash + total_unrealized

        # Track drawdown
        if equity > self._peak_equity:
            self._peak_equity = equity

        drawdown = self._peak_equity - equity
        drawdown_pct = (drawdown / self._peak_equity * 100) if self._peak_equity > 0 else 0.0

        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        if drawdown_pct > self.max_drawdown_pct:
            self.max_drawdown_pct = drawdown_pct

        # Record equity point
        self.equity_curve.append(EquityPoint(
            timestamp=timestamp,
            equity=equity,
            cash=self.cash,
            position_value=position_value,
            unrealized_pnl=total_unrealized,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
        ))

    def on_fill(self, fill: FillEvent, current_price: Optional[float] = None):
        """
        Process a fill event and update portfolio state.

        This is called by the broker after order execution.
        """
        symbol = fill.symbol
        position = self.get_position(symbol)

        is_buy = fill.side == OrderSide.BUY
        qty = fill.quantity
        price = fill.price
        commission = fill.commission
        fill_type = fill.fill_type

        # Apply slippage cost
        slippage_cost = fill.slippage * qty * self.point_value
        total_cost = commission + slippage_cost

        # Update cash for commission and slippage
        self.cash -= total_cost
        self.total_commission += commission
        self.total_slippage += slippage_cost

        if fill_type == FillType.ENTRY:
            self._handle_entry(position, is_buy, qty, price, fill.timestamp, commission, fill_type)
        else:
            self._handle_exit(position, is_buy, qty, price, fill.timestamp, commission, fill_type, fill.metadata, current_price)

        # Clean up flat positions
        if position.side == PositionSide.FLAT or position.quantity == 0:
            if symbol in self.positions:
                del self.positions[symbol]

        logger.debug(f"Fill processed: {fill_type.value} {symbol} {'BUY' if is_buy else 'SELL'} {qty}@{price:.2f}, cash={self.cash:.2f}")

    def _handle_entry(
        self,
        position: Position,
        is_buy: bool,
        qty: float,
        price: float,
        timestamp: int,
        commission: float,
        fill_type: FillType
    ):
        """Handle entry fill."""
        new_side = PositionSide.LONG if is_buy else PositionSide.SHORT

        if position.side == PositionSide.FLAT:
            # New position
            position.side = new_side
            position.quantity = qty if is_buy else -qty
            position.entry_price = price
            position.entry_timestamp = timestamp
            position.commission_paid = commission
        else:
            # Adding to position (pyramiding) - average entry price
            total_qty = position.quantity + (qty if is_buy else -qty)
            if total_qty == 0:
                # Closing position
                position.side = PositionSide.FLAT
                position.quantity = 0
            else:
                # Weighted average entry price
                position.entry_price = (
                    (position.entry_price * abs(position.quantity)) + (price * qty)
                ) / abs(total_qty)
                position.quantity = total_qty
                position.side = new_side if total_qty > 0 else (PositionSide.SHORT if new_side == PositionSide.LONG else PositionSide.LONG)
                position.commission_paid += commission

    def _handle_exit(
        self,
        position: Position,
        is_buy: bool,
        qty: float,
        price: float,
        timestamp: int,
        commission: float,
        fill_type: FillType,
        metadata: dict,
        current_price: Optional[float] = None
    ):
        """Handle exit fill and record completed trade."""
        if position.side == PositionSide.FLAT:
            logger.warning(f"Exit fill but no position for {position.symbol}")
            return

        # Determine exit side
        exit_side = PositionSide.LONG if is_buy else PositionSide.SHORT

        # For long position, exit is SELL; for short, exit is BUY
        is_closing_long = position.is_long and not is_buy
        is_closing_short = position.is_short and is_buy

        if not (is_closing_long or is_closing_short):
            logger.warning(f"Exit direction doesn't match position: pos={position.side}, fill={'BUY' if is_buy else 'SELL'}")
            return

        # Calculate P&L
        pnl_points = price - position.entry_price if position.is_long else position.entry_price - price
        pnl_usd = pnl_points * qty * self.point_value
        net_pnl = pnl_usd - commission

        # Record trade
        trade = Trade(
            symbol=position.symbol,
            side=position.side,
            entry_time=position.entry_timestamp,
            exit_time=timestamp,
            entry_price=position.entry_price,
            exit_price=price,
            quantity=qty,
            pnl=pnl_usd,
            commission=commission,
            net_pnl=net_pnl,
            pnl_points=pnl_points,
            fill_type=fill_type,
            duration_ms=timestamp - position.entry_timestamp,
            max_favorable=position.max_favorable,
            max_adverse=position.max_adverse,
        )
        self.trades.append(trade)

        # Update stats
        self.num_trades += 1
        self.total_realized_pnl += net_pnl
        if net_pnl > 0:
            self.num_wins += 1
        else:
            self.num_losses += 1

        # Symbol stats
        stats = self.symbol_stats[position.symbol]
        stats['trades'] += 1
        stats['total_pnl'] += net_pnl
        stats['total_commission'] += commission
        if net_pnl > 0:
            stats['wins'] += 1
        else:
            stats['losses'] += 1

        # Update position
        remaining_qty = abs(position.quantity) - qty
        if remaining_qty <= 1e-8:
            # Fully closed
            position.side = PositionSide.FLAT
            position.quantity = 0
            position.realized_pnl += net_pnl
        else:
            # Partial close
            position.quantity = remaining_qty if position.is_long else -remaining_qty
            position.realized_pnl += net_pnl
            position.commission_paid += commission

        # Add commission to position
        position.commission_paid += commission

        logger.info(
            f"Trade closed: {position.symbol} {'LONG' if position.is_long else 'SHORT'} "
            f"entry={position.entry_price:.2f} exit={price:.2f} qty={qty} "
            f"pnl={pnl_usd:.2f} net={net_pnl:.2f} type={fill_type.value}"
        )

    def get_metrics(self) -> Dict:
        """Calculate portfolio performance metrics."""
        if not self.trades:
            return {
                'total_return': 0.0,
                'total_return_pct': 0.0,
                'num_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'max_drawdown': self.max_drawdown,
                'max_drawdown_pct': self.max_drawdown_pct,
                'sharpe_ratio': 0.0,
                'total_commission': self.total_commission,
                'total_slippage': self.total_slippage,
            }

        # Calculate returns
        final_equity = self.equity_curve[-1].equity if self.equity_curve else self.initial_cash + self.total_realized_pnl
        total_return = final_equity - self.initial_cash
        total_return_pct = (total_return / self.initial_cash) * 100

        # Win/loss stats
        wins = [t for t in self.trades if t.net_pnl > 0]
        losses = [t for t in self.trades if t.net_pnl <= 0]

        win_rate = (len(wins) / len(self.trades) * 100) if self.trades else 0
        avg_win = sum(t.net_pnl for t in wins) / len(wins) if wins else 0
        avg_loss = sum(t.net_pnl for t in losses) / len(losses) if losses else 0

        # Profit factor
        gross_profit = sum(t.net_pnl for t in wins)
        gross_loss = abs(sum(t.net_pnl for t in losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Sharpe ratio (simplified - using daily returns from equity curve)
        sharpe = 0.0
        if len(self.equity_curve) > 1:
            returns = []
            for i in range(1, len(self.equity_curve)):
                prev = self.equity_curve[i-1].equity
                curr = self.equity_curve[i].equity
                if prev > 0:
                    returns.append((curr - prev) / prev)
            if returns:
                import statistics
                mean_ret = statistics.mean(returns)
                std_ret = statistics.stdev(returns) if len(returns) > 1 else 0.001
                sharpe = (mean_ret / std_ret) * (252 ** 0.5) if std_ret > 0 else 0  # Annualized

        return {
            'initial_cash': self.initial_cash,
            'final_equity': final_equity,
            'total_return': total_return,
            'total_return_pct': total_return_pct,
            'num_trades': self.num_trades,
            'num_wins': self.num_wins,
            'num_losses': self.num_losses,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_drawdown': self.max_drawdown,
            'max_drawdown_pct': self.max_drawdown_pct,
            'sharpe_ratio': sharpe,
            'total_commission': self.total_commission,
            'total_slippage': self.total_slippage,
            'avg_bars_held': sum(t.bars_held for t in self.trades) / len(self.trades) if self.trades else 0,
        }

    def get_trade_analysis(self) -> Dict:
        """Detailed trade analysis by type and symbol."""
        analysis = {
            'by_type': defaultdict(lambda: {'count': 0, 'wins': 0, 'total_pnl': 0.0}),
            'by_symbol': defaultdict(lambda: {'count': 0, 'wins': 0, 'total_pnl': 0.0}),
            'by_duration': [],
        }

        for trade in self.trades:
            # By fill type
            ft = trade.fill_type.value
            analysis['by_type'][ft]['count'] += 1
            analysis['by_type'][ft]['total_pnl'] += trade.net_pnl
            if trade.net_pnl > 0:
                analysis['by_type'][ft]['wins'] += 1

            # By symbol
            sym = trade.symbol
            analysis['by_symbol'][sym]['count'] += 1
            analysis['by_symbol'][sym]['total_pnl'] += trade.net_pnl
            if trade.net_pnl > 0:
                analysis['by_symbol'][sym]['wins'] += 1

            # Duration buckets
            minutes = trade.duration_ms / 60000
            if minutes < 60:
                bucket = '<1h'
            elif minutes < 240:
                bucket = '1-4h'
            elif minutes < 1440:
                bucket = '4-24h'
            else:
                bucket = '>1d'
            analysis['by_duration'].append({
                'bucket': bucket,
                'pnl': trade.net_pnl,
                'duration': minutes,
            })

        # Convert defaultdicts to regular dicts
        analysis['by_type'] = dict(analysis['by_type'])
        analysis['by_symbol'] = dict(analysis['by_symbol'])

        return analysis

    def reset(self):
        """Reset portfolio to initial state."""
        self.cash = self.initial_cash
        self.positions.clear()
        self.trades.clear()
        self.equity_curve.clear()
        self._peak_equity = self.initial_cash
        self.total_commission = 0.0
        self.total_slippage = 0.0
        self.total_realized_pnl = 0.0
        self.num_trades = 0
        self.num_wins = 0
        self.num_losses = 0
        self.max_drawdown = 0.0
        self.max_drawdown_pct = 0.0
        self.symbol_stats.clear()


def create_portfolio_from_config(config: dict) -> Portfolio:
    """Factory function to create portfolio from config dict."""
    return Portfolio(
        initial_cash=config.get('initial_cash', 100_000.0),
        point_value=config.get('point_value', 0.001),
        commission_per_lot=config.get('commission_per_lot', 0.0),
        slippage_ticks=config.get('slippage_ticks', 0.0),
        tick_size=config.get('tick_size', 0.5),
        max_position_lots=config.get('max_position_lots', 1000.0),
    )