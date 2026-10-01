#!/usr/bin/env python3
"""
fix_boot_entry.py — Sanibot

PROBLEM
    main.py throws away ANY entry signal found on the first bar-close
    callback after a restart ("[STARTUP GUARD]"). The guard exists to stop
    the bot entering on ancient downloaded history, but it fires even when
    the bar in question closed two seconds ago. A `pm2 restart` anywhere in
    the 30 minutes before a signal bar therefore silently forfeits that
    trade, while Pine takes it.

FIX
    Keep the guard, but let the signal through when the just-closed bar
    closed less than BOOT_ENTRY_MAX_AGE_SEC ago (default 120s). At that age
    the live price is still within a few points of the bar close, so the
    fill is comparable to Pine's next-bar-open fill. Older than that, the
    signal is still discarded — entering 15 minutes late is NOT parity.

USAGE
    python3 fix_boot_entry.py --check     # report, change nothing
    python3 fix_boot_entry.py             # apply (idempotent)
    python3 fix_boot_entry.py --revert    # restore main.py.prebootentry

OPTIONAL .env KEY
    BOOT_ENTRY_MAX_AGE_SEC=120
"""
from __future__ import annotations
import shutil
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parent / "main.py"
BACKUP = TARGET.with_suffix(".py.prebootentry")
MARKER = "BOOT-ENTRY-AGE"

ANCHOR = """        # NEW GUARD LOGIC: Ignore signals printed on the startup bar payload
        if is_historical_boot:
            logger.info(
                f"[STARTUP GUARD] Strategy math detected {sig.signal_type.value} on the downloaded history. "
                f"Ignoring past signal to ensure Pine Parity. Bot will only enter on new live candles."
            )
            return
"""

REPLACEMENT = '''        # NEW GUARD LOGIC: Ignore signals printed on the startup bar payload
        # BOOT-ENTRY-AGE: ...unless that bar closed only moments ago, in which
        # case this is a genuine live signal that Pine is acting on right now
        # and skipping it forfeits the trade. Age is measured from the close of
        # the signal bar; beyond the limit the price has moved too far from the
        # bar close for a late market entry to resemble Pine's next-bar-open
        # fill, so the original skip still applies.
        if is_historical_boot:
            _boot_max_age = float(os.environ.get("BOOT_ENTRY_MAX_AGE_SEC", "120"))
            try:
                _u   = CANDLE_TIMEFRAME[-1]
                _n   = int(CANDLE_TIMEFRAME[:-1])
                _pms = _n * {"m": 60_000, "h": 3_600_000, "d": 86_400_000}.get(_u, 60_000)
                _bar_age_s = time.time() - (int(snap.timestamp) + _pms) / 1000.0
            except Exception:
                _bar_age_s = 1e9

            if _bar_age_s > _boot_max_age or _bar_age_s < 0:
                logger.info(
                    f"[STARTUP GUARD] Strategy math detected {sig.signal_type.value} on the downloaded history. "
                    f"Signal bar closed {_bar_age_s:.0f}s ago (limit {_boot_max_age:.0f}s) — "
                    f"too late for a Pine-comparable fill. Ignoring past signal."
                )
                return

            logger.warning(
                f"[STARTUP GUARD] BOOT-ENTRY-AGE: {sig.signal_type.value} on the boot bar, "
                f"but it closed only {_bar_age_s:.0f}s ago (limit {_boot_max_age:.0f}s) — "
                f"treating as live and allowing entry. Fill may differ slightly from Pine."
            )
'''


def main() -> int:
    check = "--check" in sys.argv
    revert = "--revert" in sys.argv

    if not TARGET.exists():
        print(f"ERROR: {TARGET} not found. Run this from the Sanibot folder.")
        return 2

    src = TARGET.read_text()

    if revert:
        if not BACKUP.exists():
            print(f"ERROR: no backup at {BACKUP}")
            return 2
        shutil.copy2(BACKUP, TARGET)
        print(f"Reverted {TARGET.name} from {BACKUP.name}")
        return 0

    if MARKER in src:
        print("Already patched — nothing to do (idempotent).")
        return 0

    if ANCHOR not in src:
        print("ERROR: anchor block not found in main.py.")
        print("       main.py has drifted from the expected version.")
        print("       Look for 'NEW GUARD LOGIC' and patch by hand.")
        return 2

    if check:
        print("OK: anchor found, patch would apply cleanly. 0 problems.")
        return 0

    shutil.copy2(TARGET, BACKUP)
    TARGET.write_text(src.replace(ANCHOR, REPLACEMENT, 1))
    print(f"Backup written : {BACKUP.name}")
    print(f"Patched        : {TARGET.name}  (+{REPLACEMENT.count(chr(10)) - ANCHOR.count(chr(10))} lines)")
    print("Next: python3 -c 'import ast,sys; ast.parse(open(\"main.py\").read())' && pm2 restart sanibot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
