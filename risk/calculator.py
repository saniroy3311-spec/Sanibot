class RiskCalculator:
    MAKER_FEE = 0.000236  # 0.02% + 18% GST
    TAKER_FEE = 0.000590  # 0.05% + 18% GST

    @staticmethod
    def calculate_trade_fees(entry_p: float, exit_p: float, btc_size: float, hold_duration_mins: float, is_entry_maker: bool = True, is_exit_maker: bool = False) -> tuple:
        """
        Delta Exchange India Scalper Offer Logic:
        - 0% exit fee if hold_duration_mins <= 30.0 minutes on BTCUSD
        - Standard exit fee if hold_duration_mins > 30.0 minutes
        """
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
    def calculate_pnl(entry_p: float, exit_p: float, side: str, btc_size: float, hold_duration_mins: float) -> dict:
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
