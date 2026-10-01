import shutil, py_compile
T = "monitor/trail_loop.py"
M = "orders/manager.py"
E = [
 (T, "    LOT_SIZE_BTC,\n)",
     "    LOT_SIZE_BTC,\n    PAPER_MODE, DRY_RUN,\n)"),
 (T, "                if self._risk is not None and self._pos_poll_ticks  >= POSITION_POLL_TICKS:",
     "                if (not PAPER_MODE and not DRY_RUN\n"
     "                        and self._risk is not None\n"
     "                        and self._pos_poll_ticks >= POSITION_POLL_TICKS):"),
 (T, "                        pos = await self._order_mgr.fetch_open_position()\n                        if pos is None:",
     "                        pos = await self._order_mgr.fetch_open_position()\n"
     "                        if pos is not None:\n"
     "                            self._pos_seen_live = True\n"
     "                            self._pos_flat_streak = 0\n"
     "                        else:\n"
     "                            self._pos_flat_streak += 1\n"
     "                        if pos is None and not self._pos_seen_live:\n"
     "                            logger.info('[TRAIL] FIX-10b: fill not visible yet - holding')\n"
     "                        elif pos is None and self._pos_flat_streak < 2:\n"
     "                            logger.warning('[TRAIL] FIX-10b: flat poll 1/2 - confirming')\n"
     "                        elif pos is None:"),
 (T, "        self._pos_poll_ticks = 0",
     "        self._pos_poll_ticks = 0\n"
     "        self._pos_seen_live = False\n"
     "        self._pos_flat_streak = 0"),
 (T, "        self._pos_poll_ticks   : int = 0",
     "        self._pos_poll_ticks   : int = 0\n"
     "        self._pos_seen_live    : bool = False\n"
     "        self._pos_flat_streak  : int = 0"),
 (M, '        """Return fill price of the most recent trade on SYMBOL."""\n        try:',
     '        """Return fill price of the most recent trade on SYMBOL."""\n'
     "        if PAPER_MODE or DRY_RUN:\n            return None\n        try:"),
]
txt = {p: open(p).read() for p in (T, M)}
ok = True
for i, (p, old, new) in enumerate(E, 1):
    if new in txt[p]:
        print(f"{i}: already applied")
    elif old in txt[p]:
        txt[p] = txt[p].replace(old, new, 1)
        print(f"{i}: patched")
    else:
        print(f"{i}: ANCHOR MISSING")
        ok = False
if not ok:
    raise SystemExit("anchors missing - nothing written")
for p in (T, M):
    shutil.copy2(p, p + ".preghost")
    open(p, "w").write(txt[p])
    py_compile.compile(p, doraise=True)
print("DONE - both files compile")
