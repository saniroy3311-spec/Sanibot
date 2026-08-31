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


# ─── RECOVERED (verbatim from indicators/engine.py + strategy_logic.py) ────────
# main.py imports these 4 names directly from risk.calculator. They existed
# in the codebase but not in this file. Recovered, not reinvented.

def calc_levels(entry_price: float, atr: float, is_long: bool, is_trend: bool) -> RiskLevels:
    """
    Compute SL/TP from entry price + ATR.
    Ported verbatim from indicators/engine.py (same file main.py already
    imports `compute` from) — argument order (entry, atr, is_long, is_trend)
    matches every call site in main.py exactly.
    """
    from config import TREND_ATR_MULT, RANGE_ATR_MULT, TREND_RR, RANGE_RR, MAX_SL_POINTS

    atr_mult  = TREND_ATR_MULT if is_trend else RANGE_ATR_MULT
    rr        = TREND_RR       if is_trend else RANGE_RR
    stop_dist = min(atr * atr_mult, MAX_SL_POINTS)

    if is_long:
        sl = entry_price - stop_dist
        tp = entry_price + stop_dist * rr
    else:
        sl = entry_price + stop_dist
        tp = entry_price - stop_dist * rr

    return RiskLevels(
        entry_price = entry_price,
        sl          = sl,
        tp          = tp,
        stop_dist   = stop_dist,
        atr         = atr,
        is_long     = is_long,
        is_trend    = is_trend,
    )


def calc_real_pl(entry_price: float, exit_price: float, is_long: bool, qty: int) -> float:
    """
    Ported verbatim from strategy_logic.py. Net P/L after entry-leg commission
    only (Delta bracket/limit exits are maker = 0% fee; charging both legs was
    the old bug this function's comment explicitly calls out).
    """
    from config import COMMISSION_PCT

    raw_pl = (exit_price - entry_price) * qty if is_long else (entry_price - exit_price) * qty
    comm   = entry_price * qty * COMMISSION_PCT
    return raw_pl - comm


def calc_gross_pl(entry_price: float, exit_price: float, is_long: bool, qty: int) -> float:
    """
    INFERRED — not found defined anywhere in the repo (pre-existing gap,
    not something lost tonight). "Gross" = raw P/L before commission,
    i.e. the exact `raw_pl` line inside calc_real_pl above, without the
    commission subtraction. Only used for logging at trail-exit
    (main.py:743) — does not affect actual SL/TP/order placement.
    """
    return (exit_price - entry_price) * qty if is_long else (entry_price - exit_price) * qty


def recalc_levels_from_fill(levels: RiskLevels, actual_fill_price: float) -> RiskLevels:
    """
    INFERRED — not found defined anywhere in the repo (pre-existing gap).
    Used only on the position-recovery path (main.py:448) after a bot
    restart, to re-anchor a freshly computed RiskLevels object onto the
    REAL fill price reported by the exchange (which can differ from the
    signal_close price used to compute `levels`, due to slippage).

    Behavior: shifts sl/tp by the same delta as the entry price, preserving
    the original stop_dist/rr distances. At the current main.py call site,
    entry_price and actual_fill_price are passed as the same value, so this
    is a verified no-op there — it only changes behavior if a future call
    site passes a genuinely different fill price.

    ⚠️ VERIFY ON TESTNET/PAPER BEFORE TRUSTING ON A LIVE RESTART-RECOVERY
    EVENT — this is the one function in this file that was reconstructed
    from call-site logic rather than recovered verbatim.
    """
    delta = actual_fill_price - levels.entry_price
    return RiskLevels(
        entry_price = actual_fill_price,
        sl          = levels.sl + delta,
        tp          = levels.tp + delta,
        stop_dist   = levels.stop_dist,
        atr         = levels.atr,
        is_long     = levels.is_long,
        is_trend    = levels.is_trend,
    )
