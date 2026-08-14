#!/usr/bin/env python3
"""
Main backtesting engine for Sanibot framework.

Event-driven architecture using queue.Queue for event loop processing.
Coordinates data feed, strategy, portfolio, and execution.
"""

from __future__ import annotations

import json
import logging
import queue
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
import csv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Import framework modules
from events import (
    MarketEvent, SignalEvent, OrderEvent, FillEvent,
    SignalType, OrderSide, OrderType, OrderStatus, FillType,
)
from data import UniversalCSVHandler, CSVConfig, load_csv_data
from portfolio import Portfolio, create_portfolio_from_config
from execution import (
    SimulatedBroker, ExchangeConfig, DEFAULT_EXCHANGES,
    FeeConfig, SlippageConfig, SlippageModel, FeeModel,
    create_order_from_signal, create_sl_tp_orders,
)
from strategy.sanibot_strategy import (
    SanibotStrategy, StrategyConfig, StrategyMode, create_sanibot_strategy,
)


class BacktestEngine:
    """
    Main backtesting engine using event-driven architecture.

    Event flow:
    MarketEvent -> Strategy -> SignalEvent -> OrderEvent -> Broker -> FillEvent -> Portfolio
                                    \-> Broker (SL/TP) -> FillEvent -> Portfolio

    Uses queue.Queue for deterministic event processing order.
    """

    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self.config = self._load_config()

        # Event queue - the heart of the event-driven system
        self.event_queue: queue.Queue = queue.Queue()

        # Components (initialized in setup)
        self.data_handler: Optional[UniversalCSVHandler] = None
        self.portfolio: Optional[Portfolio] = None
        self.broker: Optional[SimulatedBroker] = None
        self.strategy: Optional[SanibotStrategy] = None

        # Statistics
        self.stats = {
            'bars_processed': 0,
            'signals_generated': 0,
            'orders_submitted': 0,
            'fills_received': 0,
            'start_time': None,
            'end_time': None,
        }

        # Results storage
        self.signals_history: List[SignalEvent] = []
        self.orders_history: List[OrderEvent] = []
        self.fills_history: List[FillEvent] = []

    def _load_config(self) -> dict:
        """Load configuration from JSON file."""
        if not self.config_path.exists():
            logger.warning(f"Config file not found: {self.config_path}, using defaults")
            return {}

        with open(self.config_path, 'r') as f:
            return json.load(f)

    def setup(self):
        """Initialize all components."""
        logger.info("Setting up backtest engine...")

        # 1. Data handler
        data_cfg = self.config.get('data', {})
        csv_config = CSVConfig(
            timestamp_col=data_cfg.get('timestamp_col', 'timestamp'),
            open_col=data_cfg.get('open_col', 'open'),
            high_col=data_cfg.get('high_col', 'high'),
            low_col=data_cfg.get('low_col', 'low'),
            close_col=data_cfg.get('close_col', 'close'),
            volume_col=data_cfg.get('volume_col', 'volume'),
            timestamp_format=data_cfg.get('timestamp_format', 'ms'),
            symbol=self.config.get('general', {}).get('symbol', 'BTC/USD'),
            timeframe=self.config.get('general', {}).get('timeframe', '30m'),
            skip_rows=data_cfg.get('skip_rows', 0),
            delimiter=data_cfg.get('delimiter', ','),
        )

        csv_path = data_cfg.get('csv_path', 'data/btc_usd_30m.csv')
        start_date = self.config.get('general', {}).get('start_date')
        end_date = self.config.get('general', {}).get('end_date')
        max_bars = self.config.get('general', {}).get('max_bars')

        self.data_handler = UniversalCSVHandler(
            csv_path, csv_config, start_date, end_date, max_bars
        )

        # 2. Portfolio
        portfolio_cfg = {
            'initial_cash': self.config.get('general', {}).get('initial_cash', 100_000),
            'point_value': self.config.get('execution', {}).get('point_value', 0.001),
            'commission_per_lot': self.config.get('execution', {}).get('maker_fee', 0.0),
            'slippage_ticks': self.config.get('execution', {}).get('slippage_ticks', 0),
            'tick_size': self.config.get('execution', {}).get('tick_size', 0.5),
            'max_position_lots': self.config.get('execution', {}).get('max_order_lots', 1000),
        }
        self.portfolio = create_portfolio_from_config(portfolio_cfg)

        # 3. Exchange config
        exec_cfg = self.config.get('execution', {})
        exchange_name = exec_cfg.get('exchange', 'delta')
        fee_cfg = FeeConfig(
            maker_fee=exec_cfg.get('maker_fee', 0.0002),
            taker_fee=exec_cfg.get('taker_fee', 0.0005),
            fee_model=FeeModel.MAKER_TAKER,
        )
        slippage_cfg = SlippageConfig(
            model=SlippageModel(exec_cfg.get('slippage_model', 'fixed_ticks')),
            fixed_ticks=exec_cfg.get('slippage_ticks', 1.0),
            percentage=exec_cfg.get('slippage_percentage', 0.0),
            max_slippage_ticks=exec_cfg.get('max_slippage_ticks', 10.0),
            tick_size=exec_cfg.get('tick_size', 0.5),
        )
        exchange_config = ExchangeConfig(
            name=exchange_name,
            fee_config=fee_cfg,
            slippage_config=slippage_cfg,
            tick_size=exec_cfg.get('tick_size', 0.5),
            lot_size=exec_cfg.get('lot_size', 0.001),
            min_order_lots=exec_cfg.get('min_order_lots', 1.0),
            max_order_lots=exec_cfg.get('max_order_lots', 1_000_000),
            maker_fee_pct=exec_cfg.get('maker_fee', 0.0002),
            taker_fee_pct=exec_cfg.get('taker_fee', 0.0005),
            point_value=exec_cfg.get('point_value', 0.001),
        )

        # 4. Broker
        self.broker = SimulatedBroker(
            portfolio=self.portfolio,
            exchange_config=exchange_config,
            fill_callback=self._on_fill,
            latency_ms=exec_cfg.get('latency_ms', 100),
            partial_fill_pct=exec_cfg.get('partial_fill_pct', 0.1),
            reject_probability=exec_cfg.get('reject_probability', 0.001),
        )

        # 5. Strategy
        strategy_cfg = StrategyConfig(
            mode=StrategyMode(self.config.get('strategy', {}).get('entry_strategy', 'rsi_bounce')),
            symbol=self.config.get('general', {}).get('symbol', 'BTC/USD'),
            timeframe=self.config.get('general', {}).get('timeframe', '30m'),
            risk_per_trade=self.config.get('general', {}).get('risk_per_trade', 0.02),
            max_positions=self.config.get('general', {}).get('max_positions', 1),
            trail_stages=self.config.get('risk', {}).get('trail_stages', []),
            pine_mintick=self.config.get('risk', {}).get('pine_mintick', 0.5),
            bar_close_sl_eval=self.config.get('risk', {}).get('bar_close_sl_eval', True),
            max_delta_tick_jump=self.config.get('wick_filters', {}).get('max_delta_tick_jump', 3.0),
            streak_recovery=self.config.get('wick_filters', {}).get('streak_recovery', 3),
            stale_timeout=self.config.get('wick_filters', {}).get('stale_timeout', 30),
            exchange_name=exchange_name,
            commission_per_lot=exec_cfg.get('maker_fee', 0.0),
            slippage_ticks=exec_cfg.get('slippage_ticks', 1.0),
        )
        self.strategy = SanibotStrategy(strategy_cfg, self.portfolio, self.broker)

        logger.info("Backtest engine setup complete")

    def _on_fill(self, fill: FillEvent):
        """Callback for fill events from broker."""
        self.fills_history.append(fill)
        self.stats['fills_received'] += 1

        # Update portfolio
        self.portfolio.on_fill(fill, self._get_current_price(fill.symbol))

        # Notify strategy
        if self.strategy:
            self.strategy.on_fill(fill)

        logger.debug(f"Fill processed: {fill.symbol} {fill.fill_type.value} {fill.quantity}@{fill.price:.2f}")

    def _get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol from latest bar."""
        if self.data_handler and hasattr(self.data_handler, '_prev_bar') and self.data_handler._prev_bar:
            return self.data_handler._prev_bar.close
        return 0.0

    def run(self) -> Dict[str, Any]:
        """Run the backtest event loop - process bars sequentially for correct fill timing."""
        logger.info("Starting backtest...")
        self.stats['start_time'] = time.time()

        # Process each bar sequentially:
        # 1. Broker processes market event (fills pending orders)
        # 2. Strategy processes market event (generates signals)
        # 3. Signals create orders submitted to broker
        # 4. Next bar
        for market_event in self.data_handler:
            self.stats['bars_processed'] += 1

            # Update portfolio equity
            if self.portfolio:
                self.portfolio.update_equity(
                    market_event.timestamp,
                    {market_event.symbol: market_event.close}
                )

            # 1. Broker processes this bar's market data (fills pending orders from PREVIOUS bars)
            self.broker.process_market_event(market_event)

            # 2. Strategy processes this bar (generates signals)
            if self.strategy:
                signals = self.strategy.on_market_event(market_event)
                for signal in signals:
                    self.stats['signals_generated'] += 1
                    self.signals_history.append(signal)

                    # 3. Create and submit orders from signal
                    order = create_order_from_signal(
                        signal=signal,
                        portfolio=self.portfolio,
                        exchange_config=self.broker.exchange_config,
                        risk_per_trade=self.strategy.config.risk_per_trade,
                        atr=signal.atr,
                    )

                    self.broker.submit_order(order)
                    self.stats['orders_submitted'] += 1
                    self.orders_history.append(order)

                    # Also create SL/TP orders
                    risk = self.strategy.risk_levels.get(signal.symbol)
                    if risk:
                        sl_tp_orders = create_sl_tp_orders(
                            position_symbol=signal.symbol,
                            is_long=signal.is_long,
                            entry_price=signal.price,
                            quantity=order.quantity,
                            sl_price=risk.sl,
                            tp_price=risk.tp,
                            timestamp=signal.timestamp,
                        )
                        for sltp_order in sl_tp_orders:
                            self.broker.submit_order(sltp_order)
                            self.stats['orders_submitted'] += 1
                            self.orders_history.append(sltp_order)

            # Progress logging
            if self.stats['bars_processed'] % 500 == 0:
                logger.info(f"Processed {self.stats['bars_processed']} bars...")

        self.stats['end_time'] = time.time()
        duration = self.stats['end_time'] - self.stats['start_time']

        logger.info(f"Backtest completed in {duration:.2f}s")
        logger.info(f"Bars: {self.stats['bars_processed']}, Signals: {self.stats['signals_generated']}, "
                   f"Orders: {self.stats['orders_submitted']}, Fills: {self.stats['fills_received']}")

        # Generate results
        results = self._generate_results()
        return results

    def _load_market_data(self):
        """Load market data into event queue."""
        logger.info("Loading market data...")

        for market_event in self.data_handler:
            self.event_queue.put(('market', market_event))
            self.stats['bars_processed'] += 1

            # Update portfolio equity on each bar
            if self.portfolio:
                self.portfolio.update_equity(
                    market_event.timestamp,
                    {market_event.symbol: market_event.close}
                )

        logger.info(f"Loaded {self.stats['bars_processed']} bars into event queue")

    def _process_event_queue(self):
        """Main event processing loop."""
        while not self.event_queue.empty():
            try:
                event_type, event = self.event_queue.get_nowait()
            except queue.Empty:
                break

            if event_type == 'market':
                self._process_market_event(event)
            elif event_type == 'signal':
                self._process_signal_event(event)
            elif event_type == 'order':
                self._process_order_event(event)
            elif event_type == 'fill':
                self._process_fill_event(event)

    def _process_market_event(self, market_event: MarketEvent):
        """Process market event - drive strategy and broker."""
        # Update broker with new market data (fills pending orders)
        self.broker.process_market_event(market_event)

        # Process through strategy
        if self.strategy:
            signals = self.strategy.on_market_event(market_event)
            for signal in signals:
                self.event_queue.put(('signal', signal))
                self.stats['signals_generated'] += 1
                self.signals_history.append(signal)

    def _process_signal_event(self, signal: SignalEvent):
        """Process signal event - create and submit order."""
        # Create order from signal
        order = create_order_from_signal(
            signal=signal,
            portfolio=self.portfolio,
            exchange_config=self.broker.exchange_config,
            risk_per_trade=self.strategy.config.risk_per_trade,
            atr=signal.atr,
        )

        # Submit to broker
        self.broker.submit_order(order)
        self.stats['orders_submitted'] += 1
        self.orders_history.append(order)

        # Also create SL/TP orders
        if self.strategy:
            # Get risk levels from strategy
            risk = self.strategy.risk_levels.get(signal.symbol)
            if risk:
                sl_tp_orders = create_sl_tp_orders(
                    position_symbol=signal.symbol,
                    is_long=signal.is_long,
                    entry_price=signal.price,
                    quantity=order.quantity,
                    sl_price=risk.sl,
                    tp_price=risk.tp,
                    timestamp=signal.timestamp,
                )
                for sltp_order in sl_tp_orders:
                    self.broker.submit_order(sltp_order)
                    self.stats['orders_submitted'] += 1
                    self.orders_history.append(sltp_order)

    def _process_order_event(self, order: OrderEvent):
        """Process order event (if needed for complex order management)."""
        # Orders are handled directly by broker
        pass

    def _process_fill_event(self, fill: FillEvent):
        """Process fill event (handled via broker callback)."""
        pass

    def _generate_results(self) -> Dict[str, Any]:
        """Generate backtest results and metrics."""
        logger.info("Generating results...")

        # Portfolio metrics
        portfolio_metrics = self.portfolio.get_metrics() if self.portfolio else {}

        # Trade analysis
        trade_analysis = self.portfolio.get_trade_analysis() if self.portfolio else {}

        # Broker stats
        broker_stats = self.broker.get_stats() if self.broker else {}

        # Strategy state
        strategy_state = self.strategy.get_state() if self.strategy else {}

        results = {
            'config': self.config,
            'summary': {
                'total_bars': self.stats['bars_processed'],
                'signals_generated': self.stats['signals_generated'],
                'orders_submitted': self.stats['orders_submitted'],
                'fills_received': self.stats['fills_received'],
                'duration_seconds': (
                    self.stats['end_time'] - self.stats['start_time']
                    if self.stats['start_time'] and self.stats['end_time'] else 0
                ),
            },
            'portfolio': portfolio_metrics,
            'trade_analysis': trade_analysis,
            'broker': broker_stats,
            'strategy_state': strategy_state,
            'equity_curve': [
                {
                    'timestamp': p.timestamp,
                    'datetime': datetime.fromtimestamp(p.timestamp / 1000).isoformat(),
                    'equity': p.equity,
                    'cash': p.cash,
                    'position_value': p.position_value,
                    'unrealized_pnl': p.unrealized_pnl,
                    'drawdown': p.drawdown,
                    'drawdown_pct': p.drawdown_pct,
                }
                for p in (self.portfolio.equity_curve if self.portfolio else [])
            ],
            'trades': [
                {
                    'symbol': t.symbol,
                    'side': t.side.value,
                    'entry_time': t.entry_time,
                    'exit_time': t.exit_time,
                    'entry_price': t.entry_price,
                    'exit_price': t.exit_price,
                    'quantity': t.quantity,
                    'pnl': t.pnl,
                    'commission': t.commission,
                    'net_pnl': t.net_pnl,
                    'pnl_points': t.pnl_points,
                    'fill_type': t.fill_type.value,
                    'duration_ms': t.duration_ms,
                    'max_favorable': t.max_favorable,
                    'max_adverse': t.max_adverse,
                }
                for t in (self.portfolio.trades if self.portfolio else [])
            ],
        }

        return results

    def save_results(self, results: Dict, output_dir: str = "backtest_results"):
        """Save results to files."""
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # Save full results as JSON
        results_file = output_path / f"backtest_results_{timestamp}.json"
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"Results saved to {results_file}")

        # Save trades CSV
        if results.get('trades'):
            trades_file = output_path / f"trades_{timestamp}.csv"
            with open(trades_file, 'w', newline='') as f:
                if results['trades']:
                    writer = csv.DictWriter(f, fieldnames=results['trades'][0].keys())
                    writer.writeheader()
                    writer.writerows(results['trades'])
            logger.info(f"Trades saved to {trades_file}")

        # Save equity curve CSV
        if results.get('equity_curve'):
            equity_file = output_path / f"equity_curve_{timestamp}.csv"
            with open(equity_file, 'w', newline='') as f:
                if results['equity_curve']:
                    writer = csv.DictWriter(f, fieldnames=results['equity_curve'][0].keys())
                    writer.writeheader()
                    writer.writerows(results['equity_curve'])
            logger.info(f"Equity curve saved to {equity_file}")

        return results_file


def run_backtest(config_path: str = "config.json") -> Dict[str, Any]:
    """Convenience function to run a complete backtest."""
    engine = BacktestEngine(config_path)
    engine.setup()
    results = engine.run()
    engine.save_results(results)
    return results


def create_sample_data(csv_path: str = "data/btc_usd_30m.csv", num_bars: int = 2000):
    """Create sample CSV data for testing."""
    from data import create_sample_csv
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    create_sample_csv(csv_path, num_bars)
    logger.info(f"Sample data created at {csv_path}")


if __name__ == "__main__":
    # Allow config path as command line argument
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"

    # Check for --create-sample flag
    if "--create-sample" in sys.argv:
        csv_path = "data/btc_usd_30m.csv"
        for arg in sys.argv:
            if arg.startswith("--csv-path="):
                csv_path = arg.split("=")[1]
        create_sample_data(csv_path)
        sys.exit(0)

    logger.info(f"Starting Sanibot Backtest with config: {config_path}")

    try:
        results = run_backtest(config_path)

        # Print summary
        summary = results['summary']
        portfolio = results['portfolio']

        print("\n" + "="*60)
        print("BACKTEST RESULTS SUMMARY")
        print("="*60)
        print(f"Bars Processed:    {summary['total_bars']}")
        print(f"Signals Generated: {summary['signals_generated']}")
        print(f"Orders Submitted:  {summary['orders_submitted']}")
        print(f"Fills Received:    {summary['fills_received']}")
        print(f"Duration:          {summary['duration_seconds']:.2f}s")
        print("-"*60)
        print(f"Initial Capital:   ${portfolio.get('initial_cash', 0):,.2f}")
        print(f"Final Equity:      ${portfolio.get('final_equity', 0):,.2f}")
        print(f"Total Return:      ${portfolio.get('total_return', 0):,.2f} ({portfolio.get('total_return_pct', 0):.2f}%)")
        print(f"Total Trades:      {portfolio.get('num_trades', 0)}")
        print(f"Win Rate:          {portfolio.get('win_rate', 0):.2f}%")
        print(f"Profit Factor:     {portfolio.get('profit_factor', 0):.2f}")
        print(f"Max Drawdown:      ${portfolio.get('max_drawdown', 0):,.2f} ({portfolio.get('max_drawdown_pct', 0):.2f}%)")
        print(f"Sharpe Ratio:      {portfolio.get('sharpe_ratio', 0):.2f}")
        print(f"Total Commission:  ${portfolio.get('total_commission', 0):,.2f}")
        print(f"Total Slippage:    ${portfolio.get('total_slippage', 0):,.2f}")
        print("="*60)

    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        sys.exit(1)