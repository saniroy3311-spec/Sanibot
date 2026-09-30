#!/usr/bin/env python3
"""FIX-BAR-ALIGN: pick the just-closed bar by TIMESTAMP, not by list position.

Bug: at bar close the bot fetched the 3 newest Binance candles and used [-2]
as "the closed bar". If Binance had not yet opened the new candle 1s after the
close, [-2] was the bar BEFORE the one that closed, so a stale bar was
evaluated (seen 19:30:01 IST: identical OHLC to the 19:00 bar).

Run from the repo root:  python3 fix_bar_align.py
"""
import re, sys, pathlib

p = pathlib.Path("feed/ws_feed.py")
s = p.read_text(encoding="utf-8")
if "FIX-BAR-ALIGN" in s:
    print("already patched"); sys.exit(0)
orig = s

# 1) helper method
anchor = "    async def _process_ws_candle(self, data: dict) -> None:"
helper = '''    async def _fetch_closed_bar(self, exchange, symbol, want_ts, tries=8, delay=1.0):
        """FIX-BAR-ALIGN: return the candle whose open time == want_ts, and wait
        (up to tries*delay s) until a NEWER candle exists so it is final."""
        found = None
        for _ in range(tries):
            ohlcv = await asyncio.to_thread(
                exchange.fetch_ohlcv, symbol, CANDLE_TIMEFRAME, None, 4,
            )
            found = None
            newer = False
            for b in ohlcv or []:
                if int(b[0]) == int(want_ts):
                    found = b
                elif int(b[0]) > int(want_ts):
                    newer = True
            if found is not None and newer:
                return found
            await asyncio.sleep(delay)
        return found  # exact bar even if no newer candle yet, else None

'''
assert s.count(anchor) == 1, "helper anchor missing"
s = s.replace(anchor, helper + anchor, 1)

# 2) Binance closed-bar selection (whitespace tolerant)
pat = re.compile(
    r'closed_ohlcv = await asyncio\.to_thread\(\s*self\._binance_exchange\.fetch_ohlcv,\s*'
    r'BINANCE_SYMBOL,\s*CANDLE_TIMEFRAME,\s*None,\s*3,\s*\)\s*'
    r'bar_idx = -2 if len\(closed_ohlcv\) >= 2 else -1\s*feed_name = "Binance"'
)
new = '''_exact = await self._fetch_closed_bar(
                            self._binance_exchange, BINANCE_SYMBOL,
                            self._last_candle_boundary,
                        )
                        if _exact is not None:
                            closed_ohlcv = [_exact, _exact]   # idx -2 = exact closed bar
                            bar_idx = -2
                        else:
                            logger.warning(
                                "[FEED] FIX-BAR-ALIGN: closed Binance bar "
                                f"ts={self._last_candle_boundary} not found - "
                                "falling back to positional -2 (may be stale)"
                            )
                            closed_ohlcv = await asyncio.to_thread(
                                self._binance_exchange.fetch_ohlcv,
                                BINANCE_SYMBOL, CANDLE_TIMEFRAME, None, 3,
                            )
                            bar_idx = -2 if len(closed_ohlcv) >= 2 else -1
                        feed_name = "Binance"'''
s, n = pat.subn(new, s, count=1)
assert n == 1, "binance block anchor missing"

# 3) Delta volume: choose by timestamp, fall back to old [-2]
old = "_delta_vol = float(_dvol[-2][5])"
assert s.count(old) == 1, "delta vol anchor missing"
s = s.replace(
    old,
    "_delta_vol = float(next((b for b in _dvol if int(b[0]) == int(self._last_candle_boundary)), _dvol[-2])[5])",
    1,
)

p.with_suffix(".py.prealign").write_text(orig, encoding="utf-8")
p.write_text(s, encoding="utf-8")
print("patched feed/ws_feed.py (backup: ws_feed.py.prealign)")
