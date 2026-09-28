import aiohttp
import datetime
import logging

from config import (
    TELEGRAM_ENABLED,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    LOT_SIZE_BTC,
    PARTIAL_TP_ENABLED,
    PARTIAL_TP_PTS,
    PARTIAL_TP_RATIO,
)

logger = logging.getLogger(__name__)
_API_URL = "https://api.telegram.org/bot{token}/sendMessage"


class Telegram:
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
        except Exception:
            try:
                clean_text = (
                    text.replace("<b>", "").replace("</b>", "")
                        .replace("<code>", "").replace("</code>", "")
                        .replace("<i>", "").replace("</i>", "")
                )
                payload["text"] = clean_text
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=5)):
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
        side = "LONG" if "long" in str(signal_type).lower() else "SHORT"
        emoji = "🟢" if side == "LONG" else "🔴"
        entry_p = float(entry_price)
        sl_p = float(sl)
        tp_p = float(tp)
        sl_dist = abs(entry_p - sl_p)
        tp_dist = abs(tp_p - entry_p)
        rr = tp_dist / sl_dist if sl_dist > 0 else 0.0

        partial_line = ""
        if PARTIAL_TP_ENABLED:
            close_qty = max(1, int(round(float(qty) * PARTIAL_TP_RATIO)))
            runner_qty = max(0, int(round(float(qty))) - close_qty)
            partial_line = (
                f"\n💰 <b>50% Plan:</b> close <code>{close_qty}</code> lots at "
                f"<code>+{PARTIAL_TP_PTS:.0f} pts</code>; "
                f"runner <code>{runner_qty}</code> lots"
            )

        msg = (
            f"{emoji} <b>[BTCUSD] {side} ENTRY</b> | <code>{qty} Lots</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}\n"
            f"🎯 <b>Signal:</b> <code>{signal_type}</code>\n\n"
            f"💵 <b>Fill Price:</b> <code>${entry_p:,.2f}</code>\n"
            f"🛑 <b>Stop Loss:</b> <code>${sl_p:,.2f}</code> (-{sl_dist:.1f} pts)\n"
            f"📍 <b>Reference Target:</b> <code>${tp_p:,.2f}</code> (+{tp_dist:.1f} pts | {rr:.2f} R:R)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 <b>ATR:</b> {float(atr):.1f}"
            f"{partial_line}"
        )
        await self.send(msg)

    async def notify_partial(
        self,
        entry_price: float,
        exit_price: float,
        is_long: bool,
        closed_qty: int,
        remaining_qty: int,
        points: float,
        real_pl: float,
        runner_sl: float,
        **_ignored,
    ):
        side = "LONG" if is_long else "SHORT"
        msg = (
            f"💰 <b>[BTCUSD] 50% PARTIAL PROFIT — {side}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📥 <b>Entry:</b> <code>${float(entry_price):,.2f}</code>\n"
            f"📤 <b>Partial Fill:</b> <code>${float(exit_price):,.2f}</code>\n"
            f"✅ <b>Closed:</b> <code>{closed_qty} lots</code> at <code>{points:+.1f} pts</code>\n"
            f"💵 <b>Banked:</b> <b>${float(real_pl):+,.2f} USD</b>\n"
            f"🏃 <b>Runner:</b> <code>{remaining_qty} lots</code>\n"
            f"🛡️ <b>Runner Floor:</b> <code>${float(runner_sl):,.2f}</code>"
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
        total_qty: float = 0,
        partial_qty: float = 0,
        partial_exit_price: float = 0.0,
        partial_realized_pl: float = 0.0,
        **_ignored,
    ):
        side = "LONG" if is_long else "SHORT"
        entry_p = float(entry_price)
        exit_p = float(exit_price)
        runner_qty = float(qty)
        pts = (exit_p - entry_p) if is_long else (entry_p - exit_p)
        runner_pl = pts * runner_qty * LOT_SIZE_BTC
        total_pl = float(real_pl)
        total_inr = total_pl * 84.0

        r = str(reason).lower()
        if "runner" in r:
            header = f"🚀 <b>[BTCUSD] RUNNER EXIT — {side}</b>"
        elif "breakeven" in r:
            header = f"🛡️ <b>[BTCUSD] BREAKEVEN EXIT — {side}</b>"
        elif "tp" in r and "trail" not in r:
            header = f"🎯 <b>[BTCUSD] TAKE PROFIT HIT — {side}</b>"
        elif total_pl > 0:
            header = f"💰 <b>[BTCUSD] PROFIT EXIT — {side}</b>"
        else:
            header = f"🛑 <b>[BTCUSD] STOP LOSS EXIT — {side}</b>"

        partial_block = ""
        if float(partial_qty) > 0:
            partial_block = (
                f"\n💰 <b>Earlier Partial:</b> <code>{int(partial_qty)} lots</code> "
                f"@ <code>${float(partial_exit_price):,.2f}</code> "
                f"(${float(partial_realized_pl):+,.2f})\n"
                f"🏃 <b>Runner Leg P&L:</b> <code>${runner_pl:+,.2f}</code>"
            )

        shown_qty = int(total_qty or runner_qty)
        msg = (
            f"{header} | <code>{int(runner_qty)} runner lots</code>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 <b>Exit Time:</b> {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}\n\n"
            f"📥 <b>Entry:</b> <code>${entry_p:,.2f}</code>\n"
            f"📤 <b>Final Exit:</b> <code>${exit_p:,.2f}</code>\n"
            f"📈 <b>Runner Points:</b> <code>{pts:+,.2f} pts</code>"
            f"{partial_block}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"💵 <b>Total Trade P&L ({shown_qty} lots):</b> <b>${total_pl:+,.2f} USD</b> "
            f"(<b>₹{total_inr:+,.2f} INR</b>)\n"
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
