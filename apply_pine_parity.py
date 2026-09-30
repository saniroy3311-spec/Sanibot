#!/usr/bin/env python3
"""
apply_pine_parity.py — surgical, idempotent patcher for Sanibot.

Run from the bot root (the folder containing main.py):

    cd /root/Sanibot
    python3 apply_pine_parity.py            # patch
    python3 apply_pine_parity.py --check    # report only, change nothing
    python3 apply_pine_parity.py --revert   # restore the .prepine backups

It edits three files that are too large to hand-replace safely:

  config.py            + PINE PARITY block (new tunables, ADX_TREND_TH as float)
  indicators/engine.py + snap.adx_prev  (previous bar's smoothed ADX)
                       + safe min-bars floor
  monitor/trail_loop.py+ arm-only trailing mode (Pine "trail from +200")
                       + PRE_TRAIL_BE_ENABLED gate on breakeven
                       + trail arming from the bar extreme at bar close

Every edit is guarded by a marker string, so re-running is harmless.
Backups are written next to each file as <name>.prepine.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

MARKER = "PINE-PARITY-SETUP-D"

# ─────────────────────────────────────────────────────────────────────────────
# 1. config.py — appended block
# ─────────────────────────────────────────────────────────────────────────────

CONFIG_BLOCK = f'''

# ══════════════════════════════════════════════════════════════════════════
# {MARKER}
# Appended by apply_pine_parity.py. Python evaluates top-to-bottom, so every
# name below intentionally overrides any earlier definition in this file.
# ══════════════════════════════════════════════════════════════════════════

# Pine "ADX threshold (ADX_TREND_TH)" is a float input. config.py previously
# did int(float(...)), so 13.5 silently became 13. Keep it a float.
ADX_TREND_TH = float(os.environ.get("ADX_TREND_TH", "13"))

# Pine "ADX rising check" dropdown:
#   correct -> adx > adx[1]      (previous CONFIRMED bar)   <-- Setup D
#   bot     -> legacy stale-value comparison
#   off     -> no rising requirement
ADX_RISING_MODE = os.environ.get("ADX_RISING_MODE", "correct").strip().lower()
if ADX_RISING_MODE not in {{"correct", "bot", "off"}}:
    raise ValueError(f"ADX_RISING_MODE must be correct|bot|off, got {{ADX_RISING_MODE!r}}")

# Pine "Pullback entries (EMA15 rejection)" checkbox.
USE_PULLBACK_ENTRIES = os.environ.get("USE_PULLBACK_ENTRIES", "true").lower() == "true"
# Pine hard-codes 0.35 in `nearEma`; exposed here for tuning.
PULLBACK_NEAR_EMA_ATR_MULT = float(os.environ.get("PULLBACK_NEAR_EMA_ATR_MULT", "0.35"))

# Extension guard — all three Pine inputs, now genuinely .env-driven.
EXTENSION_MAX_MULT      = float(os.environ.get("EXTENSION_MAX_MULT",      "2.1"))
EXTENSION_TIGHT_MULT    = float(os.environ.get("EXTENSION_TIGHT_MULT",    "1.8"))
EXTENSION_WICK_FRACTION = float(os.environ.get("EXTENSION_WICK_FRACTION", "0.25"))

# ── EXIT MODE ─────────────────────────────────────────────────────────────
# Pine "Exit mode" dropdown:
#   live_bot    -> 50% partial at +PARTIAL_TP_PTS, then runner
#   more_points -> no partial; a single trailing stop that arms at
#                  +TRAIL_START_PTS of MFE and trails
#                  max(TRAIL_MIN_CUSHION_PTS, ATR*TRAIL_CUSHION_ATR_MULT)
#                  behind the best price, with a floor at entry.
EXIT_MODE = os.environ.get("EXIT_MODE", "more_points").strip().lower()
if EXIT_MODE not in {{"live_bot", "more_points"}}:
    raise ValueError(f"EXIT_MODE must be live_bot|more_points, got {{EXIT_MODE!r}}")

TRAIL_START_PTS          = float(os.environ.get("TRAIL_START_PTS",          "70"))
TRAIL_MIN_CUSHION_PTS    = float(os.environ.get("TRAIL_MIN_CUSHION_PTS",    "70"))
TRAIL_CUSHION_ATR_MULT   = float(os.environ.get("TRAIL_CUSHION_ATR_MULT",   "0.01"))
TRAIL_MODE_BE_ENABLED    = os.environ.get("TRAIL_MODE_BE_ENABLED", "false").lower() == "true"

if EXIT_MODE == "more_points":
    # The "more points" profile is implemented by reusing the existing runner
    # engine with a zero-size partial: the trade flips to runner mode at
    # +TRAIL_START_PTS without closing any lots. This keeps ONE tested exit
    # code path instead of introducing a second one.
    PARTIAL_TP_ENABLED      = True
    PARTIAL_TP_PTS          = TRAIL_START_PTS      # Pine trail_price offset
    PARTIAL_TP_RATIO        = 0.0                  # 0 => arm only, close nothing
    PRE_PARTIAL_TRAIL_ENABLED = False
    RUNNER_BE_LOCK_PTS      = float(os.environ.get("RUNNER_BE_LOCK_PTS", "0"))
    RUNNER_WIDE_TRIGGER_PTS = TRAIL_START_PTS      # trail live from the arm point
    RUNNER_MIN_CUSHION_PTS  = TRAIL_MIN_CUSHION_PTS
    RUNNER_ATR_MULT         = TRAIL_CUSHION_ATR_MULT
    PRE_TRAIL_BE_ENABLED    = TRAIL_MODE_BE_ENABLED
else:
    PRE_TRAIL_BE_ENABLED    = os.environ.get("PRE_TRAIL_BE_ENABLED", "true").lower() == "true"

# Arm-only flag consumed by monitor/trail_loop.py.
PARTIAL_ARM_ONLY = PARTIAL_TP_ENABLED and PARTIAL_TP_RATIO <= 0.0
'''


# ─────────────────────────────────────────────────────────────────────────────
# 2. indicators/engine.py
# ─────────────────────────────────────────────────────────────────────────────

ENGINE_EDITS = [
    # a) dataclass field
    (
        "    htf_ema:              float = 0.0\n",
        "    # PINE-PARITY: previous confirmed bar's EMA(5)-smoothed ADX, so the\n"
        "    # rising check can be `adx > adx[1]` instead of a stale stored value.\n"
        "    adx_prev:             float = 0.0\n"
        "    htf_ema:              float = 0.0\n",
        "adx_prev:             float",
    ),
    # b) compute it
    (
        "    adx_smoothed = float(_ema(adx_raw_s, ADX_EMA).iloc[-1])\n",
        "    _adx_sm_s    = _ema(adx_raw_s, ADX_EMA)\n"
        "    adx_smoothed = float(_adx_sm_s.iloc[-1])\n"
        "    # PINE-PARITY: adx[1]\n"
        "    adx_prev_val = float(_adx_sm_s.iloc[-2]) if len(_adx_sm_s) >= 2 else 0.0\n"
        "    if adx_prev_val != adx_prev_val:   # NaN guard\n"
        "        adx_prev_val = 0.0\n",
        "adx_prev_val = float(_adx_sm_s",
    ),
    # c) pass it into the snapshot
    (
        "        htf_ema      = htf_ema,\n",
        "        adx_prev     = adx_prev_val,\n"
        "        htf_ema      = htf_ema,\n",
        "adx_prev     = adx_prev_val,",
    ),
    # d) min-bars floor
    (
        '    min_bars = EMA_TREND_LEN + 10\n'
        '    if len(df) < min_bars:\n'
        '        raise ValueError(f"Need >= {min_bars} bars, got {len(df)}")\n'
        '\n'
        '    high  = df["high"].astype(float)\n',
        '    # PINE-PARITY: a short EMA_TREND_LEN (Setup D uses 3) must not drop the\n'
        '    # requirement below what ATR(14), DMI(14), SMA(volume,20) and the\n'
        '    # 50-bar ATR average actually need, or those come back NaN.\n'
        '    min_bars = max(EMA_TREND_LEN + 10, 120)\n'
        '    if len(df) < min_bars:\n'
        '        raise ValueError(f"Need >= {min_bars} bars, got {len(df)}")\n'
        '\n'
        '    high  = df["high"].astype(float)\n',
        "min_bars = max(EMA_TREND_LEN + 10, 120)",
        True,   # applies to BOTH compute() and compute_full_series()
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# 3. monitor/trail_loop.py
# ─────────────────────────────────────────────────────────────────────────────

TRAIL_EDITS = [
    # a) import the new config names
    (
        "    PRE_PARTIAL_TRAIL_ENABLED, RUNNER_BE_LOCK_PTS,\n",
        "    PRE_PARTIAL_TRAIL_ENABLED, RUNNER_BE_LOCK_PTS,\n"
        "    PARTIAL_ARM_ONLY, PRE_TRAIL_BE_ENABLED, EXIT_MODE,\n",
        "PARTIAL_ARM_ONLY, PRE_TRAIL_BE_ENABLED, EXIT_MODE,",
    ),
    # b) arm-only entry point inside _maybe_partial_tp
    (
        '        if (\n'
        '            not PARTIAL_TP_ENABLED\n'
        '            or self._partial_done\n'
        '            or self._partial_in_flight\n'
        '            or self._risk is None\n'
        '            or self._state is None\n'
        '            or self._qty <= 1\n'
        '            or source != "delta"\n'
        '        ):\n'
        '            return False\n',
        '        # PINE-PARITY: arm-only mode ("More points: trail from +200").\n'
        '        # PARTIAL_TP_RATIO=0 means "flip to runner/trailing mode at\n'
        '        # +PARTIAL_TP_PTS but do not close any lots". No order is sent,\n'
        '        # so the qty>1 and delta-only guards below do not apply: the\n'
        '        # trigger may legitimately come from a bar extreme too, which is\n'
        '        # how Pine measures MFE (mfe := max(mfe, dir*(fav - fillPx))).\n'
        '        if PARTIAL_ARM_ONLY:\n'
        '            return self._arm_trail_only(price, source=source)\n'
        '\n'
        '        if (\n'
        '            not PARTIAL_TP_ENABLED\n'
        '            or self._partial_done\n'
        '            or self._partial_in_flight\n'
        '            or self._risk is None\n'
        '            or self._state is None\n'
        '            or self._qty <= 1\n'
        '            or source != "delta"\n'
        '        ):\n'
        '            return False\n',
        "if PARTIAL_ARM_ONLY:\n            return self._arm_trail_only",
    ),
    # c) the _arm_trail_only helper itself
    (
        '    async def _maybe_partial_tp(self, price: float, source: str) -> bool:\n',
        '    def _arm_trail_only(self, price: float, source: str = "tick") -> bool:\n'
        '        """\n'
        '        PINE-PARITY (Exit mode = "More points: trail from +200").\n'
        '\n'
        '        Flip the trade into runner/trailing mode once MFE reaches\n'
        '        +PARTIAL_TP_PTS, WITHOUT closing any lots. Mirrors Pine:\n'
        '            if mfe >= trailStart\n'
        '                runner := true\n'
        '            mStop = runner ? fillPx : stopLvl\n'
        '            strategy.exit("B", stop=mStop,\n'
        '                          trail_price=fillPx + dir*trailStart,\n'
        '                          trail_offset=max(mMinCush, atr*mCushAtr))\n'
        '\n'
        '        Returns True on the bar/tick that arms it.\n'
        '        """\n'
        '        risk = self._risk\n'
        '        state = self._state\n'
        '        if risk is None or state is None or self._partial_done or self._qty <= 0:\n'
        '            return False\n'
        '\n'
        '        profit_pts = (price - risk.entry_price) if risk.is_long else (risk.entry_price - price)\n'
        '        if profit_pts < PARTIAL_TP_PTS:\n'
        '            return False\n'
        '\n'
        '        self._partial_done = True          # "tranche stage reached"\n'
        '        self._runner_mode  = True\n'
        '        self._partial_closed_qty = 0\n'
        '        self._partial_exit_price = 0.0\n'
        '        self._partial_realized_pl = 0.0\n'
        '\n'
        '        state.trail_armed = True\n'
        '        state.be_done     = True           # floor is now managed by the trail\n'
        '        state.stage       = max(int(getattr(state, "stage", 0)), 1)\n'
        '        state.best_price  = float(price)\n'
        '        state.current_sl  = self._runner_lock_price()\n'
        '        self._trail_ever_armed = True\n'
        '\n'
        '        logger.info(\n'
        '            f"[TRAIL-ARM] Pine trail armed (arm-only, 0 lots closed) | "\n'
        '            f"src={source} price={price:.2f} mfe={profit_pts:.1f}pts "\n'
        '            f"trigger=+{PARTIAL_TP_PTS:.0f} floor={state.current_sl:.2f} "\n'
        '            f"cushion={max(RUNNER_MIN_CUSHION_PTS, self._current_atr * RUNNER_ATR_MULT):.1f}pts"\n'
        '        )\n'
        '\n'
        '        # Re-run the runner SL maths straight away so the trailing stop is\n'
        '        # live from this very tick rather than one loop later.\n'
        '        self._update_runner_sl(price, update_best=False, source="arm_only")\n'
        '        return True\n'
        '\n'
        '    async def _maybe_partial_tp(self, price: float, source: str) -> bool:\n',
        "def _arm_trail_only(self, price: float",
    ),
    # d) BE gate — tick path
    (
        '            profit = (price - entry_price) if is_long else (entry_price - price)\n'
        '            if not state.be_done and profit > atr * BE_MULT:\n'
        '                self._activate_be(state, risk, is_long, atr, source="tick")\n',
        '            profit = (price - entry_price) if is_long else (entry_price - price)\n'
        '            # PINE-PARITY: Pine\'s "More points" mode has mBeOn=false, so no\n'
        '            # breakeven before the trail arms.\n'
        '            if PRE_TRAIL_BE_ENABLED and not state.be_done and profit > atr * BE_MULT:\n'
        '                self._activate_be(state, risk, is_long, atr, source="tick")\n',
        "if PRE_TRAIL_BE_ENABLED and not state.be_done and profit > atr * BE_MULT:",
    ),
    # e) BE gate — bar-close path
    (
        '            if not self._partial_done and not state.be_done and dual_profit > atr * BE_MULT:\n'
        '                self._activate_be(state, risk, is_long, atr, source="bar_close")\n',
        '            if (\n'
        '                PRE_TRAIL_BE_ENABLED\n'
        '                and not self._partial_done\n'
        '                and not state.be_done\n'
        '                and dual_profit > atr * BE_MULT\n'
        '            ):\n'
        '                self._activate_be(state, risk, is_long, atr, source="bar_close")\n',
        "PRE_TRAIL_BE_ENABLED\n                and not self._partial_done",
    ),
    # f) arm from the bar extreme at bar close
    (
        '            bar_extreme = bar_high if is_long else bar_low\n'
        '            if self._partial_done and self._runner_mode:\n'
        '                self._update_runner_sl(bar_extreme, update_best=True, source="runner_bar")\n'
        '            return\n',
        '            bar_extreme = bar_high if is_long else bar_low\n'
        '            # PINE-PARITY: Pine arms the trail from the bar EXTREME\n'
        '            # (mfe uses high/low), not only from live ticks. Without this a\n'
        '            # fast bar that spikes past the trigger and closes back below it\n'
        '            # would never arm, and the move would be given back.\n'
        '            if PARTIAL_ARM_ONLY and not self._partial_done:\n'
        '                self._arm_trail_only(bar_extreme, source="bar_close")\n'
        '            if self._partial_done and self._runner_mode:\n'
        '                self._update_runner_sl(bar_extreme, update_best=True, source="runner_bar")\n'
        '            return\n',
        "if PARTIAL_ARM_ONLY and not self._partial_done:",
    ),
]


# ─────────────────────────────────────────────────────────────────────────────

def _apply(path: Path, edits, check_only: bool) -> tuple[int, int, list[str]]:
    """Returns (applied, already_present, problems)."""
    if not path.exists():
        return 0, 0, [f"MISSING FILE: {path}"]

    text = path.read_text(encoding="utf-8")
    original = text
    applied = present = 0
    problems: list[str] = []

    for edit in edits:
        old, new, marker = edit[0], edit[1], edit[2]
        allow_multi = edit[3] if len(edit) > 3 else False
        if marker in text:
            present += 1
            continue
        n = text.count(old)
        if n == 0:
            problems.append(f"{path.name}: anchor not found -> {old.strip().splitlines()[0][:70]!r}")
            continue
        if n != 1 and not allow_multi:
            problems.append(f"{path.name}: anchor is not unique ({n}x) -> {old.strip().splitlines()[0][:70]!r}")
            continue
        text = text.replace(old, new) if allow_multi else text.replace(old, new, 1)
        applied += 1

    if text != original and not check_only:
        backup = path.with_suffix(path.suffix + ".prepine")
        if not backup.exists():
            shutil.copy2(path, backup)
        path.write_text(text, encoding="utf-8")

    return applied, present, problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    ap.add_argument("--revert", action="store_true", help="restore .prepine backups")
    args = ap.parse_args()

    targets = [ROOT / "config.py", ROOT / "indicators/engine.py", ROOT / "monitor/trail_loop.py"]

    if args.revert:
        n = 0
        for t in targets:
            b = t.with_suffix(t.suffix + ".prepine")
            if b.exists():
                shutil.copy2(b, t)
                print(f"reverted {t}")
                n += 1
        print(f"\n{n} file(s) restored. Restore your previous .env separately.")
        return 0

    all_problems: list[str] = []
    total_applied = total_present = 0

    # config.py — append-only
    cfg = ROOT / "config.py"
    if not cfg.exists():
        all_problems.append("MISSING FILE: config.py")
    else:
        ctext = cfg.read_text(encoding="utf-8")
        if MARKER in ctext:
            print("config.py            : already patched")
            total_present += 1
        elif args.check:
            print("config.py            : WOULD PATCH (append parity block)")
        else:
            backup = cfg.with_suffix(".py.prepine")
            if not backup.exists():
                shutil.copy2(cfg, backup)
            cfg.write_text(ctext.rstrip("\n") + "\n" + CONFIG_BLOCK, encoding="utf-8")
            print("config.py            : PATCHED (parity block appended)")
            total_applied += 1

    for path, edits, label in (
        (ROOT / "indicators/engine.py", ENGINE_EDITS, "indicators/engine.py "),
        (ROOT / "monitor/trail_loop.py", TRAIL_EDITS, "monitor/trail_loop.py"),
    ):
        a, p, probs = _apply(path, edits, args.check)
        all_problems += probs
        total_applied += a
        total_present += p
        verb = "WOULD PATCH" if args.check and a else "PATCHED" if a else "already patched"
        print(f"{label}: {verb}  ({a} edit(s) applied, {p} already present, {len(probs)} problem(s))")

    print()
    if all_problems:
        print("PROBLEMS — nothing was half-written, but review these:")
        for p in all_problems:
            print("  -", p)
        return 1

    if args.check:
        print("Check complete. Re-run without --check to apply.")
    else:
        print(f"Done. {total_applied} edit(s) applied, {total_present} already in place.")
        print("Backups: *.prepine   Revert with: python3 apply_pine_parity.py --revert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
