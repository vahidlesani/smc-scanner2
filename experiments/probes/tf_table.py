"""Pattern/trigger/confirm/TOHOM timeframe table, READ FROM THE LIVE CODE.

Viva 10-02: «اصلا تایم الگو رو در تایم‌فریم‌ها بگو ببینم درسته یا غلطه … هم در
اسپات و هم در ستاپ‌ها … بصورت جدول بده».  This script prints the tables; the
docs page `docs/R65_TF_TABLE.md` carries the same numbers.

    python experiments/probes/tf_table.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import analysis.spot_engine as SPOT  # noqa: E402
from analysis.confirm_r62 import CONFIRM_LADDER, TOHOM_SUB_OF_CONFIRM  # noqa: E402
import analysis.setups_experimental as EXP  # noqa: E402,F401  (registers setups)
from analysis.setups_v7 import (CONFIRM_TF_BY_TRIGGER, TIMEFRAME_PROFILES,  # noqa: E402
                                EXPIRY_HOURS_BY_TRIGGER)


def one_step_below(tf: str) -> str:
    return CONFIRM_LADDER.get(str(tf).lower(), "—")


def tohom_of(confirm_tf: str) -> str:
    return TOHOM_SUB_OF_CONFIRM.get(str(confirm_tf).lower(), "—")


# the product's raw TF ladder, finest → coarsest
ORDER = ("1m", "5m", "15m", "30m", "1h", "2h", "4h", "8h", "12h", "1d", "3d", "1w")
# the confirm TF the one-step law asks for (the nearest lower confirm-grade TF)
EXPECT_CONFIRM = {"4h": "1h", "8h": "4h", "12h": "4h", "1d": "4h",
                  "3d": "1d", "1w": "1d"}


def spot_table():
    print("\n### SPOT (per TF)")
    print(f"{'TF':>4s} {'horizon':>8s} {'confirm':>8s} {'TOHOM reads':>12s} "
          f"{'path floor':>10s} {'verdict':>16s}")
    for tf in SPOT.SPOT_TRIGGERS:
        ctf = SPOT.SPOT_CONFIRM_TF.get(tf, "—")
        sub = SPOT.spot_tohom_tf(tf)
        floor = SPOT.MIN_PATH_PCT_BY_TF.get(tf, 0.0)
        horizon = ("SHORT" if tf in SPOT.SPOT_SHORT_TFS
                   else "MID" if tf in SPOT.SPOT_MID_TFS else "LONG")
        # the verdict against the stated law («هر تایم‌فریم باید از تایم
        # پایین‌تر تایید بگیره»): the nearest lower confirm-grade TF is the
        # reference; anything finer is EARLIER on purpose.
        expected = EXPECT_CONFIRM.get(tf, ctf)
        verdict = "OK" if ctf == expected else f"earlier ({expected})"
        print(f"{tf:>4s} {horizon:>8s} {str(ctf):>8s} {str(sub):>12s} "
              f"{floor:>9.1f}% {verdict:>16s}")


def futures_table():
    print("\n### FUTURES / PERPETUAL (per style and per setup)")
    print("style      scan stream        structure  refine  trigger  confirm  TOHOM")
    streams = [("DAYTRADE", TIMEFRAME_PROFILES["DAYTRADE"])]
    for trig, prof in (("30m", ("2h", "1h", "30m")),
                       ("1h", ("1d", "4h", "1h")),
                       ("2h", ("1d", "4h", "2h")),
                       ("4h", ("1d", "4h", "4h"))):
        streams.append((f"SWING {trig}", prof))
    streams.append(("GRAND", TIMEFRAME_PROFILES["GRAND"]))
    for name, prof in streams:
        structure, refine, trigger = prof
        ctf = CONFIRM_TF_BY_TRIGGER.get(trigger) or CONFIRM_LADDER.get(trigger, "—")
        print(f"{name:<10s} {str(prof):<18s} {structure:>9s} {refine:>7s} "
              f"{trigger:>8s} {str(ctf):>8s} {str(tohom_of(ctf)):>6s}")
    print("\nsetup      pattern TF                                   trigger TF"
          "          confirm TF")
    print(f"TLBREAK    profile structure ({'/'.join(t[1][0] for t in streams[1:])})"
          "   profile trigger       1 step below trigger")
    print("P1234      profile context/middle                     profile trigger"
          "       1 step below trigger")
    print("TECHCLASSIC profile structure                          profile trigger"
          "       1 step below trigger")
    print("ALBROX     lane A = TECHCLASSIC engine; lanes B/C = zones on the"
          " profile trigger")
    print("\n### PIN family (the pin's own TF)")
    for style, tfs in EXP.PINVAL_TF_BY_STYLE.items():
        for tf in tfs:
            print(f"PINVAL/PINWALLQ {style:<9s} pin TF {tf:>3s} → confirm "
                  f"{str(CONFIRM_TF_BY_TRIGGER.get(tf) or CONFIRM_LADDER.get(tf, '—')):>4s} "
                  f"→ TOHOM {str(tohom_of(CONFIRM_LADDER.get(tf, ''))):>4s} "
                  f"| expiry {EXPIRY_HOURS_BY_TRIGGER.get(tf, '—')}h")


if __name__ == "__main__":
    spot_table()
    futures_table()
