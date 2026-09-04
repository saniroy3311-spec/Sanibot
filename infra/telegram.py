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

    async def notify_entry(
        self,
        signal_type: str = "",
        entry_price: float = 0.0,
        sl: float = 0.0,
        tp: float = 0.0,
        atr: float = 0.0,
        qty: float = 0,
        **_ignored,
    ):
        """
        Matches main.py's call site exactly:
            await self._telegram.notify_entry(
                signal_type=..., entry_price=..., sl=..., tp=..., atr=..., qty=...
            )
        `side` is derived from signal_type (e.g. "Trend Long" / "Range Short")
        since main.py doesn't pass is_long here.
        """
        side = "LONG" if "long" in str(signal_type).lower() else "SHORT"
        emoji = "🟢" if side == "LONG" else "🔴"
        entry_p = float(entry_price)
        sl_p = float(sl)
        tp_p = float(tp)

        if side == "LONG":
            sl_dist = abs(entry_p - sl_p)
            tp_dist = abs(tp_p - entry_p)
        else:
            sl_dist = abs(sl_p - entry_p)
            tp_dist = abs(entry_p - tp_p)

        rr = tp_dist / sl_dist if sl_dist > 0 else 3.0

        msg = (
            f"{emoji} <b>[BTCUSD] {side} ENTRY</b> | <code>{qty} Lots</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}\n"
            f"🎯 <b>Signal:</b> <code>{signal_type}</code>\n\n"
            f"💵 <b>Fill Price:</b> <code>${entry_p:,.2f}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>${sl_p:,.2f}</code> (-{sl_dist:.1f} pts)\n"
            f"🎯 <b>Take Profit:</b> <code>${tp_p:,.2f}</code> (+{tp_dist:.1f} pts | {rr:.2f} R:R)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>ATR:</b> {float(atr):.1f}"
        )
        await self.send(msg)

    async def notify_exit(
        self,
        reason: str = "Trail SL",
        entry_price: float = 0.0,
        exit_price: float = 0.0,
        real_pl: float = 0.0,
        is_long: bool = True,
        qty: float = 0,
        **_ignored,
    ):
        """
        Matches main.py's call site exactly:
            await self._telegram.notify_exit(
                reason=..., entry_price=..., exit_price=..., real_pl=...,
                is_long=..., qty=...
            )
        """
        side = "LONG" if is_long else "SHORT"
        entry_p = float(entry_price)
        exit_p = float(exit_price)
        pts = (exit_p - entry_p) if is_long else (entry_p - exit_p)
        pl_usd = float(real_pl)
        pl_inr = pl_usd * 84.0

        if pts > 200:
            header = f"🚀 <b>[BTCUSD] MEGA RUNNER EXIT — {side}</b>"
        elif pl_usd > 0:
            header = f"🏆 <b>[BTCUSD] PROFIT TARGET HIT — {side}</b>"
        elif abs(pts) <= 15:
            header = f"🛡️ <b>[BTCUSD] BREAKEVEN EXIT — {side}</b>"
        else:
            header = f"🛑 <b>[BTCUSD] STOP LOSS EXIT — {side}</b>"

        msg = (
            f"{header} | <code>{qty} Lots</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Exit Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}\n\n"
            f"📥 <b>Entry:</b> <code>${entry_p:,.2f}</code>\n"
            f"📤 <b>Exit:</b> <code>${exit_p:,.2f}</code>\n"
            f"📈 <b>Points Captured:</b> <code>{pts:+,.2f} pts</code>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>P&L:</b> <b>${pl_usd:+,.2f} USD</b> (<b>₹{pl_inr:+,.2f} INR</b>)\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"🏷️ <b>Exit Reason:</b> <i>{reason}</i>"
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
