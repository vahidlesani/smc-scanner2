"""Dump every drawn artist (lines/patches) + axes state at savefig."""
import sys
TREE = sys.argv[1]
sys.path.insert(0, TREE)
print("TREE:", TREE)
import matplotlib.figure as MF

orig = MF.Figure.savefig
def logged_savefig(self, *a, **k):
    for i, ax in enumerate(self.axes):
        try:
            print(f"AX{i} xlim={ax.get_xlim()} ylim={ax.get_ylim()} yscale={ax.get_yscale()}")
        except Exception as e:
            print(f"AX{i} ERR {e}")
        for ln in ax.lines:
            try:
                xd, yd = ln.get_xdata(), ln.get_ydata()
                import numpy as np
                print(f"  LINE c={ln.get_color()} w={ln.get_linewidth()} a={ln.get_alpha()} "
                      f"vis={ln.get_visible()} z={ln.get_zorder()} "
                      f"x=[{np.min(xd):.1f},{np.max(xd):.1f}] y=[{np.min(yd):.1f},{np.max(yd):.1f}] n={len(xd)}")
            except Exception as e:
                print("  LINE ERR", e)
    return orig(self, *a, **k)
MF.Figure.savefig = logged_savefig

import bot.messages_v7 as M  # noqa
import analysis.render_kit  # noqa
import analysis.models  # noqa
import analysis.snapshot_lock  # noqa
import importlib.util
spec = importlib.util.spec_from_file_location("aero", "/home/user/probe_setups_AERO.py")
aero = importlib.util.module_from_spec(spec)
spec.loader.exec_module(aero)
aero.main()
