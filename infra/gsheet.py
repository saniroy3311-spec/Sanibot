import os
import json
import datetime

class GSheet:
    def __init__(self, config=None, *args, **kwargs):
        if config is None:
            self.enabled = os.environ.get('GSHEET_ENABLED', 'true').lower() == 'true'
            self.spreadsheet_id = os.environ.get('GSHEET_SPREADSHEET_ID', '1kpXpRuGYeScm7DtNUT5ctDeR60ssj0aqcfRWjCpBFME')
            self.sheet_name = os.environ.get('GSHEET_SHEET_NAME', 'Sanibot (30m Swing)')
            self.creds_file = os.environ.get('GSHEET_CREDENTIALS_PATH', '/root/Sanibot/credentials.json')
        else:
            self.enabled = getattr(config, 'GSHEET_ENABLED', True)
            self.spreadsheet_id = getattr(config, 'GSHEET_SPREADSHEET_ID', '1kpXpRuGYeScm7DtNUT5ctDeR60ssj0aqcfRWjCpBFME')
            self.sheet_name = getattr(config, 'GSHEET_SHEET_NAME', 'Sanibot (30m Swing)')
            self.creds_file = getattr(config, 'GSHEET_CREDENTIALS_PATH', '/root/Sanibot/credentials.json')

        self.client = None
        if self.enabled:
            self._init_client()

    def _init_client(self):
        try:
            import gspread
            from google.oauth2.service_account import Credentials
            if os.path.exists(self.creds_file):
                scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
                creds = Credentials.from_service_account_file(self.creds_file, scopes=scopes)
                self.client = gspread.authorize(creds)
                print(f"[GoogleSheets] Authorized for sheet: {self.spreadsheet_id} -> Tab: {self.sheet_name}")
        except Exception as e:
            print(f"[GoogleSheets] Init error: {e}")

    def append_trade(self, trade_data: dict, *args, **kwargs):
        if not self.enabled or not self.client:
            return

        entry_p = float(trade_data.get('entry_price', trade_data.get('entry_p', 0.0)))
        exit_p = float(trade_data.get('exit_price', trade_data.get('exit_p', 0.0)))
        pts = float(trade_data.get('points_captured', trade_data.get('points', trade_data.get('pts', 0.0))))
        lots = int(trade_data.get('lots', trade_data.get('qty', 6)))
        btc_size = float(trade_data.get('size_btc', trade_data.get('pos_size', lots * 0.001)))
        gross_usd = float(trade_data.get('gross_pnl_usd', trade_data.get('gross_pnl', pts * btc_size)))
        fees_usd = float(trade_data.get('fees_usd', trade_data.get('fees_gst', 0.0)))
        net_usd = float(trade_data.get('net_pnl_usd', trade_data.get('real_pl', gross_usd - fees_usd)))
        net_inr = float(trade_data.get('net_pnl_inr', net_usd * 84.0))
        balance_usd = float(trade_data.get('equity', trade_data.get('balance_usd', 3000.0 + net_usd)))
        balance_inr = float(balance_usd * 84.0)
        status = 'WIN' if net_usd > 0 else ('LOSS' if net_usd < 0 else 'BREAKEVEN')
        hold_mins = float(trade_data.get('hold_duration_mins', trade_data.get('hold_mins', 15.0)))
        scalper_status = '0% Exit Fee (Scalper)' if hold_mins <= 30 else 'Std Fee'
        notes = f"{trade_data.get('reason', trade_data.get('exit_reason', 'Trail SL'))} | {scalper_status}"

        # Exact 18 columns matching your Dashboard Row 6 headers
        row = [
            trade_data.get('trade_id', trade_data.get('id', 'T-001')),
            trade_data.get('time', trade_data.get('ts', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))),
            trade_data.get('symbol', 'BTCUSD'),
            trade_data.get('strategy', trade_data.get('signal_type', 'P7_MOMENTUM_EXPANSION')),
            str(trade_data.get('side', 'LONG')).upper(),
            entry_p,
            exit_p,
            pts,
            lots,
            btc_size,
            gross_usd,
            fees_usd,
            net_usd,
            net_inr,
            balance_usd,
            balance_inr,
            status,
            notes
        ]

        try:
            sheet = self.client.open_by_key(self.spreadsheet_id).worksheet(self.sheet_name)
            sheet.append_row(row, value_input_option='USER_ENTERED')
            print(f"[GoogleSheets] Appended trade {trade_data.get('trade_id', 'T-001')} to {self.sheet_name}")
        except Exception as e:
            print(f"[GoogleSheets] Error appending row: {e}")

    def log_trade(self, trade_data: dict, *args, **kwargs):
        self.append_trade(trade_data, *args, **kwargs)

# Compatibility Alias
GoogleSheetsLogger = GSheet
