import urllib.request
import urllib.parse
import json
import datetime

class TelegramNotifier:
    def __init__(self, config=None):
        if config is None:
            import os
            self.enabled = os.environ.get('TELEGRAM_ENABLED', 'true').lower() == 'true'
            self.bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
            self.chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')
        else:
            self.enabled = getattr(config, 'TELEGRAM_ENABLED', True)
            self.bot_token = getattr(config, 'TELEGRAM_BOT_TOKEN', '')
            self.chat_id = getattr(config, 'TELEGRAM_CHAT_ID', '')

    def send_message(self, text: str):
        if not self.enabled or not self.bot_token or not self.chat_id:
            print(f"\n[Telegram Notification (Simulated)]:\n{text}\n")
            return

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = json.dumps({
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as response:
                pass
        except Exception as e:
            try:
                clean_text = text.replace("<b>", "").replace("</b>", "").replace("<code>", "").replace("</code>", "").replace("<i>", "").replace("</i>", "")
                payload = json.dumps({"chat_id": self.chat_id, "text": clean_text}).encode("utf-8")
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=5) as response:
                    pass
            except Exception as e2:
                print(f"[Telegram Alert Error]: {e2}")

    def notify_entry(self, data: dict):
        side = data.get('side', 'LONG').upper()
        emoji = "🟢" if side == "LONG" else "🔴"
        entry_p = float(data.get('entry_price', 0.0))
        sl_p = float(data.get('sl_price', 0.0))
        tp_p = float(data.get('tp_price', 0.0))
        
        if side == "LONG":
            sl_dist = abs(entry_p - sl_p)
            tp_dist = abs(tp_p - entry_p)
        else:
            sl_dist = abs(sl_p - entry_p)
            tp_dist = abs(entry_p - tp_p)

        rr = tp_dist / sl_dist if sl_dist > 0 else 3.0

        msg = (
            f"{emoji} <b>[BTCUSD] {side} ENTRY</b> | <code>{data.get('lots', 6)} Lots</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Time:</b> {data.get('time', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S IST'))}\n"
            f"🎯 <b>Strategy:</b> <code>{data.get('strategy', 'P7_MOMENTUM_EXPANSION')}</code>\n\n"
            f"💵 <b>Fill Price:</b> <code>${entry_p:,.2f}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>${sl_p:,.2f}</code> (-{sl_dist:.1f} pts)\n"
            f"🎯 <b>Take Profit:</b> <code>${tp_p:,.2f}</code> (+{tp_dist:.1f} pts | {rr:.2f} R:R)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <b>Delta Scalper Offer:</b> Active (0% Closing Fee if ≤ 30m)\n"
            f"📊 <b>ATR:</b> {data.get('atr', 0):.1f} | <b>ADX:</b> {data.get('adx', 0):.1f}"
        )
        self.send_message(msg)

    def notify_exit(self, data: dict):
        pts = float(data.get('points_captured', 0.0))
        net_pnl = float(data.get('net_pnl_usd', 0.0))
        net_inr = float(data.get('net_pnl_inr', net_pnl * 84.0))
        side = data.get('side', 'LONG').upper()
        hold_mins = float(data.get('hold_duration_mins', 15.0))

        if pts > 200:
            header = f"🚀 <b>[BTCUSD] MEGA RUNNER EXIT — {side}</b>"
        elif pts > 0:
            header = f"🏆 <b>[BTCUSD] PROFIT TARGET HIT — {side}</b>"
        elif abs(pts) <= 15:
            header = f"🛡️ <b>[BTCUSD] BREAKEVEN EXIT — {side}</b>"
        else:
            header = f"🛑 <b>[BTCUSD] STOP LOSS EXIT — {side}</b>"

        if hold_mins <= 30.0:
            scalper_badge = f"✅ <b>0% Exit Fee Applied</b> (Held {hold_mins:.1f}m ≤ 30m)"
        else:
            scalper_badge = f"⏱️ Standard Fee (Held {hold_mins:.1f}m > 30m)"

        msg = (
            f"{header} | <code>{data.get('lots', 6)} Lots</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Exit Time:</b> {data.get('time', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S IST'))}\n"
            f"⏱️ <b>Trade Duration:</b> {hold_mins:.1f} min\n\n"
            f"📥 <b>Entry:</b> <code>${float(data.get('entry_price', 0)):,.2f}</code>\n"
            f"📤 <b>Exit:</b> <code>${float(data.get('exit_price', 0)):,.2f}</code>\n"
            f"📈 <b>Points Captured:</b> <code>{pts:+,.2f} pts</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Gross P&L:</b> ${float(data.get('gross_pnl_usd', 0)):+,.2f} USD\n"
            f"🎟️ <b>Scalper Status:</b> {scalper_badge}\n"
            f"🧾 <b>Delta Fees:</b> -${float(data.get('fees_usd', 0)):,.4f} USD\n"
            f"💵 <b>Net P&L:</b> <b>${net_pnl:+,.2f} USD</b> (<b>₹{net_inr:+,.2f} INR</b>)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷️ <b>Exit Reason:</b> <i>{data.get('reason', 'Trail SL')}</i>"
        )
        self.send_message(msg)

    def notify_breakeven(self, side: str, entry_p: float, new_sl: float, stage: int = 0):
        if stage > 0:
            text = (
                f"🔒 <b>[TRAIL LOCK STAGE {stage} ACTIVATED]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📈 <b>Side:</b> {side}\n"
                f"🛡️ <b>New Trailing SL:</b> <code>${new_sl:,.2f}</code>\n"
                f"💰 <b>Guaranteed Profit:</b> Locked above entry <code>${entry_p:,.2f}</code>"
            )
        else:
            text = (
                f"🛡️ <b>[BREAKEVEN PROFIT LOCKED]</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📈 <b>Side:</b> {side}\n"
                f"🛑 <b>SL Moved to:</b> <code>${new_sl:,.2f}</code> (Risk Free Trade ✅)"
            )
        self.send_message(text)
