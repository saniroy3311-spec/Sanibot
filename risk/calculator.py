from dataclasses import dataclass, field

class RiskLevels:
    def __init__(self, sl=0.0, tp=0.0, be=0.0, trail_trigger=0.0, trail_dist=0.0, **kwargs):
        self.sl = sl
        self.tp = tp
        self.be = be
        self.trail_trigger = trail_trigger
        self.trail_dist = trail_dist
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        return f"RiskLevels(sl={self.sl}, tp={self.tp}, be={self.be})"

class TrailState:
    def __init__(self, highest=0.0, lowest=0.0, stage=0, is_be=False, **kwargs):
        self.highest = highest
        self.lowest = lowest
        self.highest_p = highest
        self.lowest_p = lowest
        self.stage = stage
        self.current_trail_stage = stage
        self.is_be = is_be
        self.is_be_locked = is_be
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __repr__(self):
        return f"TrailState(highest={self.highest}, stage={self.stage})"

class RiskCalculator:
    MAKER_FEE = 0.000236  # 0.02% + 18% GST
    TAKER_FEE = 0.000590  # 0.05% + 18% GST

    @staticmethod
    def get_position_size(consecutive_losses: int = 0, config=None) -> tuple:
        if config is not None and getattr(config, 'CONSECUTIVE_LOSS_SIZE_SCALE', False) and consecutive_losses > 0:
            lots = getattr(config, 'MIN_SCALE_LOTS', 3)
        else:
            lots = getattr(config, 'DEFAULT_LOTS', 6) if config else 6
        lot_size = getattr(config, 'LOT_SIZE_BTC', 0.001) if config else 0.001
        btc_size = round(lots * lot_size, 4)
        return lots, btc_size

    @staticmethod
    def calculate_brackets(entry_price: float, side: str, sl_pts: float, tp_pts: float) -> tuple:
        if side.upper() == 'LONG':
            sl_price = round(entry_price - sl_pts, 2)
            tp_price = round(entry_price + tp_pts, 2)
        else:
            sl_price = round(entry_price + sl_pts, 2)
            tp_price = round(entry_price - tp_pts, 2)
        return sl_price, tp_price

    @staticmethod
    def calculate_trade_fees(entry_p: float, exit_p: float, btc_size: float, hold_duration_mins: float = 15.0, is_entry_maker: bool = True, is_exit_maker: bool = False) -> tuple:
        entry_notional = entry_p * btc_size
        exit_notional = exit_p * btc_size
        entry_rate = RiskCalculator.MAKER_FEE if is_entry_maker else RiskCalculator.TAKER_FEE
        exit_rate = RiskCalculator.MAKER_FEE if is_exit_maker else RiskCalculator.TAKER_FEE

        entry_fee = entry_notional * entry_rate
        standard_exit_fee = exit_notional * exit_rate

        if hold_duration_mins <= 30.0:
            exit_fee = 0.0
            is_scalper_applied = True
            fees_saved_usd = standard_exit_fee
        else:
            exit_fee = standard_exit_fee
            is_scalper_applied = False
            fees_saved_usd = 0.0

        total_fee = entry_fee + exit_fee
        return entry_fee, exit_fee, total_fee, is_scalper_applied, fees_saved_usd

    @staticmethod
    def calculate_pnl(entry_p: float, exit_p: float, side: str, btc_size: float, hold_duration_mins: float = 15.0) -> dict:
        if side.upper() == 'LONG':
            pts = exit_p - entry_p
        else:
            pts = entry_p - exit_p

        gross_usd = pts * btc_size
        e_fee, x_fee, tot_fee, scalper_applied, saved_usd = RiskCalculator.calculate_trade_fees(
            entry_p, exit_p, btc_size, hold_duration_mins
        )
        net_usd = gross_usd - tot_fee
        net_inr = net_usd * 84.0

        return {
            'points_captured': round(pts, 2),
            'gross_pnl_usd': round(gross_usd, 4),
            'fees_usd': round(tot_fee, 4),
            'net_pnl_usd': round(net_usd, 4),
            'net_pnl_inr': round(net_inr, 2),
            'is_scalper_offer_applied': scalper_applied,
            'fees_saved_usd': round(saved_usd, 4),
            'hold_duration_mins': round(hold_duration_mins, 1)
        }
