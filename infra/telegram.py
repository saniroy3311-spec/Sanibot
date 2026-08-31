import aiohttp
import datetime
import logging

from config import TELEGRAM_ENABLED, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class Telegram:
    """
    Async Telegram notifier. Interface required by main.py:
        Telegram()                              — no-arg constructor
        await self._telegram.send(text)         — raw message
        await self._telegram.notify_entry(data) — formatted entry card
        await self._telegram.notify_exit(data)  — formatted exit card
    Also passed into TelegramController(telegram=self._telegram) which
    calls await self._tg.send(text) for command replies — same `send`.
    """

    def __init__(self):
        self.enabled = TELEGRAM_ENABLED
        self.bot_token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID

    async def send(self, text: str):
        if not self.enabled or not self.bot_token or not self.chat_id:
            print(f"\n[Telegram Notification (Simulated)]:\n{text}\n")
            return

        url = _API_URL.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(f"[Telegram] non-200 ({resp.status}): {body[:200]}")
        except Exception as e:
            # Retry once with HTML tags stripped, in case malformed markup caused the failure
            try:
                clean_text = (
                    text.replace("<b>", "").replace("</b>", "")
                        .replace("<code>", "").replace("</code>", "")
                        .replace("<i>", "").replace("</i>", "")
                )
                payload["text"] = clean_text
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        pass
            except Exception as e2:
                logger.error(f"[Telegram Alert Error]: {e2}")

    async def notify_entry(self, data: dict):
        side = str(data.get('side', 'LONG')).upper()
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
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Time:</b> {data.get('time', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S IST'))}\n"
            f"🎯 <b>Strategy:</b> <code>{data.get('strategy', 'P7_MOMENTUM_EXPANSION')}</code>\n\n"
            f"💵 <b>Fill Price:</b> <code>${entry_p:,.2f}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>${sl_p:,.2f}</code> (-{sl_dist:.1f} pts)\n"
            f"🎯 <b>Take Profit:</b> <code>${tp_p:,.2f}</code> (+{tp_dist:.1f} pts | {rr:.2f} R:R)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ <b>Delta Scalper Offer:</b> Active (0% Closing Fee if ≤ 30m)\n"
            f"📊 <b>ATR:</b> {float(data.get('atr', 0)):.1f} | <b>ADX:</b> {float(data.get('adx', 0)):.1f}"
        )
        await self.send(msg)

    async def notify_exit(self, data: dict):
        pts = float(data.get('points_captured', 0.0))
        net_pnl = float(data.get('net_pnl_usd', 0.0))
        net_inr = float(data.get('net_pnl_inr', net_pnl * 84.0))
        side = str(data.get('side', 'LONG')).upper()
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
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Gross P&L:</b> ${float(data.get('gross_pnl_usd', 0)):+,.2f} USD\n"
            f"🎟️ <b>Scalper Status:</b> {scalper_badge}\n"
            f"🧾 <b>Delta Fees:</b> -${float(data.get('fees_usd', 0)):,.4f} USD\n"
            f"💵 <b>Net P&L:</b> <b>${net_pnl:+,.2f} USD</b> (<b>₹{net_inr:+,.2f} INR</b>)\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷️ <b>Exit Reason:</b> <i>{data.get('reason', 'Trail SL')}</i>"
        )
        await self.send(msg)

    async def notify_breakeven(self, side: str, entry_p: float, new_sl: float, stage: int = 0):
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
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📈 <b>Side:</b> {side}\n"
                f"🛑 <b>SL Moved to:</b> <code>${new_sl:,.2f}</code> (Risk Free Trade ✅)"
            )
        await self.send(text)
