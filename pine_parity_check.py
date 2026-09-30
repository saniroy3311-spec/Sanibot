#!/usr/bin/env python3
"""
pine_parity_check.py — prove the bot is loading exactly what TradingView shows.

    cd /root/Sanibot
    python3 pine_parity_check.py

Reads the SAME config.py the bot reads (so it catches .env typos, stale
exports and any value config.py overrides internally) and prints it next to
the "Sanibot Profit D" Inputs panel values.

Exit code 0 = every row matches. Exit code 1 = at least one MISMATCH.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    pass

import config as C

# (Pine input label, config attribute, expected value from your screenshots)
EXPECTED = [
    # ── Entry ──────────────────────────────────────────────────────────────
    ("EMA fast (EMA_FAST_LEN)",               "EMA_FAST_LEN",              2),
    ("EMA trend (EMA_TREND_LEN)",             "EMA_TREND_LEN",             3),
    ("1H EMA filter",                         "OPT_HTF_TREND_ENABLED",     True),
    ("1H EMA length (OPT_HTF_EMA_LEN)",       "OPT_HTF_EMA_LEN",           10),
    ("ATR minimum pts (ATR_MIN)",             "ATR_MIN",                   125.0),
    ("EMA separation x ATR",                  "EMA_SEPARATION_ATR_MULT",   0.08),
    ("ADX threshold (ADX_TREND_TH)",          "ADX_TREND_TH",              13.0),
    ("ADX rising check",                      "ADX_RISING_MODE",           "correct"),
    ("Body min x ATR (FILTER_BODY_MULT)",     "FILTER_BODY_MULT",          0.40),
    ("Volume filter (FILTER_VOL_ENABLED)",    "FILTER_VOL_ENABLED",        True),
    ("Volume x SMA20 (FILTER_VOL_MULT)",      "FILTER_VOL_MULT",           1.00),
    ("Breakout box bars",                     "BREAKOUT_BOX_BARS",         2),
    ("Breakout buffer pts",                   "BREAKOUT_BUFFER_PTS",       2.0),
    ("Structure filter",                      "STRUCTURE_FILTER_ENABLED",  True),
    ("Structure lookback bars",               "STRUCTURE_LOOKBACK_BARS",   3),
    ("Extension max x ATR",                   "EXTENSION_MAX_MULT",        2.1),
    ("Extension tight x ATR",                 "EXTENSION_TIGHT_MULT",      1.8),
    ("Extension close-near-edge fraction",    "EXTENSION_WICK_FRACTION",   0.25),
    ("Pullback entries (EMA15 rejection)",    "USE_PULLBACK_ENTRIES",      True),
    ("Loss cooldown bars",                    "LOSS_COOLDOWN_BARS",        0),
    ("Win cooldown sec",                      "WIN_COOLDOWN_SEC",          30),
    ("Entry slip re-anchor x ATR",            None,                        0.30),
    # ── Risk ───────────────────────────────────────────────────────────────
    ("Initial SL x ATR (TB_SL_ATR_MULT)",     "TB_SL_ATR_MULT",            1.4),
    ("  -> used by calc_levels as",           "TREND_ATR_MULT",            1.4),
    ("Max SL x ATR (MAX_SL_MULT)",            "MAX_SL_MULT",               1.1),
    ("Max SL points cap (MAX_SL_POINTS)",     "MAX_SL_POINTS",             90.0),
    ("Breakeven x ATR (BE_MULT)",             "BE_MULT",                   0.4),
    # ── Exit mode ──────────────────────────────────────────────────────────
    ("Exit mode",                             "EXIT_MODE",                 "more_points"),
    ("Trail start pts",                       "TRAIL_START_PTS",           70.0),
    ("Trail cushion min pts",                 "TRAIL_MIN_CUSHION_PTS",     70.0),
    ("Trail cushion x ATR",                   "TRAIL_CUSHION_ATR_MULT",    0.01),
    ("Breakeven in this mode",                "TRAIL_MODE_BE_ENABLED",     False),
    # ── Derived wiring (these are what the trail engine actually uses) ─────
    ("  -> arm trigger  (PARTIAL_TP_PTS)",    "PARTIAL_TP_PTS",            70.0),
    ("  -> lots closed  (PARTIAL_TP_RATIO)",  "PARTIAL_TP_RATIO",          0.0),
    ("  -> arm-only     (PARTIAL_ARM_ONLY)",  "PARTIAL_ARM_ONLY",          True),
    ("  -> floor        (RUNNER_BE_LOCK_PTS)","RUNNER_BE_LOCK_PTS",        0.0),
    ("  -> trail live   (RUNNER_WIDE_TRIGGER_PTS)", "RUNNER_WIDE_TRIGGER_PTS", 70.0),
    ("  -> cushion min  (RUNNER_MIN_CUSHION_PTS)",  "RUNNER_MIN_CUSHION_PTS",  70.0),
    ("  -> cushion xATR (RUNNER_ATR_MULT)",   "RUNNER_ATR_MULT",           0.01),
    ("  -> pre-trail BE (PRE_TRAIL_BE_ENABLED)", "PRE_TRAIL_BE_ENABLED",   False),
]

MISSING = object()


def _get(attr):
    if attr is None:
        return MISSING
    return getattr(C, attr, MISSING)


def _eq(a, b) -> bool:
    if a is MISSING:
        return False
    if isinstance(b, bool):
        return bool(a) is b
    if isinstance(b, (int, float)) and isinstance(a, (int, float)):
        return abs(float(a) - float(b)) < 1e-9
    return str(a).strip().lower() == str(b).strip().lower()


def main() -> int:
    bad = 0
    skipped = 0
    print()
    print(f"{'Pine input':44}  {'expected':>14}  {'bot':>14}   status")
    print("-" * 88)
    for label, attr, expected in EXPECTED:
        val = _get(attr)
        if attr is None:
            print(f"{label:44}  {expected!s:>14}  {'(main.py)':>14}   -- manual --")
            skipped += 1
            continue
        if val is MISSING:
            print(f"{label:44}  {expected!s:>14}  {'ABSENT':>14}   MISMATCH  <-- config.py not patched?")
            bad += 1
            continue
        ok = _eq(val, expected)
        shown = f"{val:.4g}" if isinstance(val, float) else str(val)
        print(f"{label:44}  {expected!s:>14}  {shown:>14}   {'ok' if ok else 'MISMATCH  <--'}")
        if not ok:
            bad += 1

    print("-" * 88)
    # Sanity notes the table cannot express.
    atr_ref = 200.0
    sl = min(atr_ref * C.TREND_ATR_MULT, C.MAX_SL_POINTS)
    mx = min(atr_ref * C.MAX_SL_MULT, C.MAX_SL_POINTS)
    print(f"At ATR={atr_ref:.0f}: bar-close SL = {sl:.0f} pts from anchor, "
          f"Max SL = {mx:.0f} pts from fill.")
    print(f"ATR_MIN={C.ATR_MIN:.0f}, so both stops are capped at "
          f"{C.MAX_SL_POINTS:.0f} pts on essentially every trade.")
    print(f"Trail: arms at +{C.PARTIAL_TP_PTS:.0f} MFE, then rides "
          f"max({C.RUNNER_MIN_CUSHION_PTS:.0f}, ATR*{C.RUNNER_ATR_MULT}) behind the peak, "
          f"floor = entry +{C.RUNNER_BE_LOCK_PTS:.0f}.")
    print()
    if bad:
        print(f"RESULT: {bad} mismatch(es). Fix .env, then re-run.")
        return 1
    print(f"RESULT: all {len(EXPECTED) - skipped} checked rows match the Pine panel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
