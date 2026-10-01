#!/usr/bin/env python3
"""
fix_ghost_paper.py — stops the ghost-trail guard from killing paper trades.

Bug: in paper mode OrderManager.fetch_open_position() always returns None,
and monitor/trail_loop.py reads that None as "the exchange bracket fired",
so every paper trade is closed ~2 seconds after entry. It also fetched the
exit price from the LIVE Delta account, producing the 83140.00 / 935-pt
slippage line.

Patches (idempotent, backups written as *.preghost):
  monitor/trail_loop.py
    1. import PAPER_MODE, DRY_RUN from config
    2. skip the position poll entirely in paper / dry-run
    3. live mode: wait until the fill is actually visible, and require
       2 consecutive flat polls before declaring the bracket fired
  orders/manager.py
    4. fetch_bracket_fill_price() returns None in paper / dry-run

Usage:
    python3 fix_ghost_paper.py --check
    python3 fix_ghost_paper.py
    python3 fix_ghost_paper.py --revert
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TRAIL = ROOT / "monitor" / "trail_loop.py"
MGR = ROOT / "orders" / "manager.py"

EDITS = [
    # ── 1. imports ────────────────────────────────────────────────────────
    (TRAIL, "import-flags",
     "    LOT_SIZE_BTC,\n)",
     "    LOT_SIZE_BTC,\n    PAPER_MODE, DRY_RUN,\n)"),

    # ── 2. never poll the exchange for a position in paper mode ───────────
    (TRAIL, "paper-gate",
     "                if self._risk is not None and self._pos_poll_ticks  >= POSITION_POLL_TICKS:",
     "                if (not PAPER_MODE and not DRY_RUN\n"
     "                        and self._risk is not None\n"
     "                        and self._pos_poll_ticks >= POSITION_POLL_TICKS):"),

    # ── 3. live mode: grace period + 2 confirmed flat polls ───────────────
    (TRAIL, "flat-confirm",
     "                        pos = await self._order_mgr.fetch_open_position()\n"
     "                        if pos is None:",
     "                        pos = await self._order_mgr.fetch_open_position()\n"
     "                        if pos is not None:\n"
     "                            self._pos_seen_live   = True\n"
     "                            self._pos_flat_streak = 0\n"
     "                        else:\n"
     "                            self._pos_flat_streak += 1\n"
     "                        if pos is None and not self._pos_seen_live:\n"
     "                            logger.info(\n"
     "                                '[TRAIL] FIX-10b: fill not visible on Delta yet '\n"
     "                                '- holding the trail'\n"
     "                            )\n"
     "                        elif pos is None and self._pos_flat_streak < 2:\n"
     "                            logger.warning(\n"
     "                                '[TRAIL] FIX-10b: flat poll 1/2 - confirming before exit'\n"
     "                            )\n"
     "                        elif pos is None:"),

    # ── 3b. per-trade reset of the two new counters ───────────────────────
    (TRAIL, "reset-state",
     "        # FIX-10: Reset position poll counter for the new trade\n"
     "        self._pos_poll_ticks = 0",
     "        # FIX-10: Reset position poll counter for the new trade\n"
     "        self._pos_poll_ticks = 0\n"
     "        # FIX-10b: fill not yet confirmed on the exchange for this trade\n"
     "        self._pos_seen_live   = False\n"
     "        self._pos_flat_streak = 0"),

    # ── 3c. attribute defaults ────────────────────────────────────────────
    (TRAIL, "init-state",
     "        self._pos_poll_ticks   : int = 0",
     "        self._pos_poll_ticks   : int = 0\n"
     "        self._pos_seen_live    : bool = False\n"
     "        self._pos_flat_streak  : int = 0"),

    # ── 4. never read the live account's fills in paper mode ──────────────
    (MGR, "paper-fill-guard",
     '        """Return fill price of the most recent trade on SYMBOL."""\n'
     "        try:",
     '        """Return fill price of the most recent trade on SYMBOL."""\n'
     "        if PAPER_MODE or DRY_RUN:\n"
     "            return None\n"
     "        try:"),
]


def run(mode: str) -> int:
    if mode == "revert":
        n = 0
        for path in (TRAIL, MGR):
            bak = path.with_suffix(path.suffix + ".preghost")
            if bak.exists():
                shutil.copy2(bak, path)
                print(f"reverted {path.relative_to(ROOT)}")
                n += 1
        print("nothing to revert" if not n else "done")
        return 0

    texts = {p: p.read_text() for p in (TRAIL, MGR)}
    todo, done, missing = [], [], []

    for path, name, old, new in EDITS:
        t = texts[path]
        if new in t:
            done.append(name)
        elif old in t:
            todo.append(name)
            texts[path] = t.replace(old, new, 1)
        else:
            missing.append(name)

    for name in done:
        print(f"  already applied : {name}")
    for name in todo:
        print(f"  will apply      : {name}")
    for name in missing:
        print(f"  ANCHOR MISSING  : {name}")

    if missing:
        print("\nSome anchors were not found — the file has drifted. "
              "Nothing was written.")
        return 1
    if mode == "check":
        print("\n--check only, nothing written.")
        return 0
    if not todo:
        print("\nAlready fully patched.")
        return 0

    for path in (TRAIL, MGR):
        bak = path.with_suffix(path.suffix + ".preghost")
        if not bak.exists():
            shutil.copy2(path, bak)
        path.write_text(texts[path])
        print(f"patched {path.relative_to(ROOT)}  (backup {bak.name})")

    import py_compile
    for path in (TRAIL, MGR):
        py_compile.compile(str(path), doraise=True)
    print("both files compile ✅")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "apply"
    sys.exit(run({"--check": "check", "--revert": "revert"}.get(arg, "apply")))
