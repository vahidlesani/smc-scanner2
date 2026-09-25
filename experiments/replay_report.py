"""Aggregate replay_live_setups.py outputs into a markdown report + compact CSV.

  python experiments/replay_report.py --in replay_out --md report.md --csv trades.csv
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
from collections import defaultdict
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

R = "r_net"          # production settlement: gross − round-trip fee
R2 = "r_net_slip"    # conservative: fee + slippage both legs


def load(indir: str):
    rows = []
    for p in glob.glob(os.path.join(indir, "**", "trades__*.jsonl"), recursive=True):
        with open(p) as fh:
            rows += [json.loads(x) for x in fh if x.strip()]
    fun = []
    for p in glob.glob(os.path.join(indir, "**", "funnel__*.json"), recursive=True):
        with open(p) as fh:
            fun.append(json.load(fh))
    return pd.DataFrame(rows), fun


def load_fates(indir: str) -> pd.DataFrame:
    rows = []
    for p in glob.glob(os.path.join(indir, "**", "fates__*.jsonl"), recursive=True):
        with open(p) as fh:
            rows += [json.loads(x) for x in fh if x.strip()]
    return pd.DataFrame(rows)


def _codes(series) -> str:
    tot: Dict[str, int] = defaultdict(int)
    for d in series:
        for k, v in (d or {}).items():
            tot[k] += int(v)
    s = sum(tot.values()) or 1
    return ", ".join(f"{k} {100*v/s:.0f}%" for k, v in sorted(tot.items(), key=lambda x: -x[1])[:4])


def _fate_row(key: str, g: pd.DataFrame, total: int) -> str:
    tch = g[g["sh_touched"].astype(bool)]
    dec = tch[tch["sh_outcome"].astype(int) != 0]
    wr = 100.0 * (dec["sh_outcome"].astype(int) > 0).mean() if len(dec) else float("nan")
    avg = tch["sh_r"].astype(float).mean() if len(tch) else float("nan")
    dist = g["dist_atr"].astype(float).median() if "dist_atr" in g and g["dist_atr"].notna().any() else float("nan")
    return (f"| {key} | {len(g)} | {100*len(g)/max(total,1):.0f}% | {g['alive_h'].astype(float).median():.1f} | "
            f"{g['n_eval'].astype(float).median():.0f} | {dist:.1f} | {100*len(tch)/max(len(g),1):.0f}% | "
            f"{wr:.0f}% | {avg:+.3f} | {_codes(g['rej'])} |")


FHDR = ("| slice | n | share | alive h (med) | evals (med) | dist ATR (med) | shadow touched | "
        "shadow TP1-first | shadow avgR | top reject codes |\n|---|---|---|---|---|---|---|---|---|---|")


def fates_report(fd: pd.DataFrame) -> str:
    """Why tracked scenarios die + what the unconfirmed plan would have done
    (shadow = entry touched → TP1 before stop inside the expiry window; looks
    ahead, diagnostic only)."""
    L = ["# Candidate fates (R31.6 diagnostic)\n",
         "shadow: after detection, was the planned entry touched within the expiry window, and did TP1 print "
         "before the stop (same bar = stop)? shadow R = +TP1/R or −1, minus fee; 0 if neither. It ignores the "
         "ladder, so it is a proxy for the quality of the plan, not a PnL.\n"]
    for arm, a in fd.groupby("arm"):
        a = a.copy()
        a["key"] = a["setup"] + "|" + a["tf"]
        L.append(f"\n## arm `{arm}`\n")
        L.append("### setup|tf × fate\n")
        L.append(FHDR)
        for key, g in a.groupby("key"):
            tot = len(g)
            L.append(_fate_row(f"**{key}** all", g, tot))
            for fz, h in g.groupby("fate"):
                L.append(_fate_row(f"{key} · {fz}", h, tot))
        tc = a[a["setup"] == "TECHCLASSIC"]
        if not tc.empty:
            L.append("\n### TECHCLASSIC kind × fate\n")
            L.append(FHDR)
            for (tf, kind), g in tc.groupby(["tf", "kind"]):
                tot = len(g)
                for fz, h in g.groupby("fate"):
                    L.append(_fate_row(f"{tf} {kind} · {fz}", h, tot))
            L.append("\n### TECHCLASSIC pattern (all TFs)\n")
            L.append(FHDR)
            for pt, g in tc.groupby("pattern"):
                L.append(_fate_row(pt or "?", g, len(tc)))
            L.append("\n### TECHCLASSIC confirm-edge source / major line TF\n")
            L.append(FHDR)
            for (es, mt), g in tc.groupby(["edge_src", "major_tf"]):
                L.append(_fate_row(f"edge={es or 'tool'} major={mt or '-'}", g, len(tc)))
    return "\n".join(L) + "\n"


def stats(d: pd.DataFrame, col: str = R) -> Dict:
    d = d[d["state"] == "CLOSED"]
    n = len(d)
    if n == 0:
        return {"n": 0}
    r = d[col].astype(float)
    pos, neg = r[r > 0].sum(), -r[r < 0].sum()
    eq = r.loc[d.sort_values("closed_at").index].cumsum()
    dd = float((eq.cummax() - eq).max()) if n else 0.0
    return {"n": n, "wr": 100.0 * (r > 0).mean(), "avg": r.mean(), "sum": r.sum(),
            "pf": (pos / neg) if neg > 0 else float("inf"), "dd": dd,
            "tp1": 100.0 * (d["hit"].astype(int) >= 1).mean(),
            "risk": d["risk_pct"].astype(float).mean(),
            "tp1r": d["tp1_r"].astype(float).mean()}


def boot_ci(r: np.ndarray, n_boot: int = 2000, seed: int = 1):
    if len(r) < 8:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = rng.choice(r, (n_boot, len(r)), replace=True).mean(axis=1)
    return float(np.percentile(means, 5)), float(np.percentile(means, 95))


def fmt(s: Dict) -> str:
    if not s or s.get("n", 0) == 0:
        return "| 0 | – | – | – | – | – | – | – | – |"
    pf = "∞" if math.isinf(s["pf"]) else f"{s['pf']:.2f}"
    return (f"| {s['n']} | {s['wr']:.0f}% | {s['avg']:+.3f} | {s['sum']:+.1f} | {pf} | "
            f"{s['dd']:.1f} | {s['tp1']:.0f}% | {s['risk']:.2f}% | {s['tp1r']:.2f} |")


HDR = ("| n | WR | avgR | ΣR | PF | maxDD(R) | TP1% | stop% | TP1/R |\n"
       "|---|---|---|---|---|---|---|---|---|")


def table(title: str, groups: Dict[str, pd.DataFrame], col: str = R) -> List[str]:
    out = [f"\n### {title}\n", "| slice " + HDR.split("\n")[0], "|---" + HDR.split("\n")[1]]
    for k, g in groups.items():
        out.append(f"| {k} " + fmt(stats(g, col)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", default="replay_out")
    ap.add_argument("--md", default="replay_report.md")
    ap.add_argument("--csv", default="replay_trades.csv")
    ap.add_argument("--is-frac", type=float, default=0.70)
    ap.add_argument("--fates-md", default="fates.md")
    a = ap.parse_args()
    df, fun = load(a.indir)
    L: List[str] = ["# Replay report (R31.5)\n"]
    if fun:
        f0 = fun[0]
        syms = sorted({f["symbol"] for f in fun})
        arms = sorted({f["arm"] for f in fun})
        L.append(f"window {f0['start']} → {f0['end']} · symbols {len(syms)}: {', '.join(syms)} · arms: {', '.join(arms)}")
        L.append(f"scan time total {sum(f['scan_sec'] for f in fun)/60:.0f} min · scans {sum(f['scans'] for f in fun)}")
        errs = defaultdict(int)
        for f in fun:
            for k, v in (f["funnel"].get("_errors") or {}).items():
                errs[k] += v
        if errs:
            L.append(f"scan errors: {dict(errs)}")
    if df.empty:
        L.append("\n**no trades**")
    else:
        df["confirmed_at"] = pd.to_datetime(df["confirmed_at"])
        t0, t1 = df["confirmed_at"].min(), df["confirmed_at"].max()
        cut = t0 + (t1 - t0) * a.is_frac
        df["period"] = np.where(df["confirmed_at"] <= cut, "IS", "OOS")
        df["key"] = df["setup"] + "|" + df["tf"]
        L.append(f"IS/OOS cut at {cut:%Y-%m-%d %H:%M} ({a.is_frac:.0%} of the confirmation span)")
        L.append("\nR = realized ladder R − round-trip fee (production settlement). "
                 "R′ also deducts slippage on both legs.")

        L.append("\n## 1. Arms (all setups)\n")
        L.append("| arm | confirmed | filled | no-fill | ambiguous | open@end |" + HDR.split("\n")[0][1:])
        L.append("|---|---|---|---|---|---" + HDR.split("\n")[1])
        for arm, g in df.groupby("arm"):
            L.append(f"| {arm} | {len(g)} | {int(g['filled_at'].astype(str).str.len().gt(0).sum())} | "
                     f"{int((g['state']=='NO_FILL').sum())} | {int((g['state']=='AMBIGUOUS').sum())} | "
                     f"{int(g['state'].isin(['OPEN','AWAIT_FILL']).sum())} " + fmt(stats(g)))
        for arm, g in df.groupby("arm"):
            L.append(f"\n## 2. Arm `{arm}` — per setup / trigger TF\n")
            L += table("setup|tf (R)", {k: x for k, x in g.groupby("key")})
            L += table("setup|tf (R′ incl. slippage)", {k: x for k, x in g.groupby("key")}, R2)
            L += table("setup|direction", {k: x for k, x in g.groupby(g["setup"] + "|" + g["dir"])})
            L += table("setup|period (IS vs OOS)", {k: x for k, x in g.groupby(g["key"] + "|" + g["period"])})
            L += table("symbol", {k: x for k, x in g.groupby("symbol")})
            L += table("exit reason", {k: x for k, x in g.groupby("reason")})
            c = g[g["state"] == "CLOSED"]
            L.append("\n### bootstrap 90% CI of avgR\n")
            L.append("| slice | n | avgR | CI90 |\n|---|---|---|---|")
            for k, x in [("ALL", c)] + [(k, x) for k, x in c.groupby("key") if len(x) >= 8]:
                lo, hi = boot_ci(x[R].astype(float).values)
                L.append(f"| {k} | {len(x)} | {x[R].mean():+.3f} | [{lo:+.3f}, {hi:+.3f}] |")

        base = df[df["arm"] == "base"] if (df["arm"] == "base").any() else df
        L.append("\n## 3. What-if filters on arm `base` (post-hoc, same trades)\n")
        filt: Dict[str, Callable[[pd.DataFrame], pd.Series]] = {
            "none": lambda d: pd.Series(True, index=d.index),
            "B2 TP1 ≥ 0.5R": lambda d: d["tp1_r"].astype(float) >= 0.5,
            "B2 TP1 ≥ 0.8R": lambda d: d["tp1_r"].astype(float) >= 0.8,
            "B2 TP1 ≥ 1.0R": lambda d: d["tp1_r"].astype(float) >= 1.0,
            "B3 stop not clamped": lambda d: ~d.get("stop_clamped", pd.Series(False, index=d.index)).fillna(False).astype(bool),
            "B4 conf body≥0.3ATR & beyond prev": lambda d: (d.get("conf_body_atr", pd.Series(0, index=d.index)).fillna(0).astype(float) >= 0.3)
                & d.get("conf_beyond_prev", pd.Series(False, index=d.index)).fillna(False).astype(bool),
            "B5 with 4h trend (EMA50)": lambda d: d.get("trend_4h", pd.Series(0, index=d.index)).fillna(0).astype(int) == 1,
            "B5 with 1d trend (EMA20)": lambda d: d.get("trend_1d", pd.Series(0, index=d.index)).fillna(0).astype(int) == 1,
            "B5 against 4h trend": lambda d: d.get("trend_4h", pd.Series(0, index=d.index)).fillna(0).astype(int) == -1,
            "B7 trigger-bar vol ≥ 1.1×": lambda d: d.get("det_vr", pd.Series(0, index=d.index)).fillna(0).astype(float) >= 1.1,
            "B7 trigger-bar vol ≥ 1.5×": lambda d: d.get("det_vr", pd.Series(0, index=d.index)).fillna(0).astype(float) >= 1.5,
            "ADX(trigger) ≥ 20": lambda d: d.get("det_adx", pd.Series(0, index=d.index)).fillna(0).astype(float) >= 20,
            "lane INTERNAL": lambda d: d["lane"].astype(str) == "INTERNAL",
            "lane not INTERNAL": lambda d: d["lane"].astype(str) != "INTERNAL",
        }
        if "p1_signal_bar" in base:
            filt["B6 ALBROX P1 signal bar"] = lambda d: (d["setup"] != "ALBROX") | d["p1_signal_bar"].fillna(False).astype(bool)
        L.append("| filter | " + HDR.split("\n")[0][2:] + " OOS n | OOS avgR |")
        L.append("|---" + HDR.split("\n")[1] + "---|---|")
        for name, fn in filt.items():
            try:
                m = fn(base).fillna(False).astype(bool)
            except Exception:
                continue
            sub = base[m]
            so = stats(sub[sub["period"] == "OOS"])
            L.append(f"| {name} " + fmt(stats(sub)) + f" {so.get('n', 0)} | "
                     f"{so.get('avg', float('nan')):+.3f} |")
        for key, g in base.groupby("key"):
            if (g["state"] == "CLOSED").sum() < 15:
                continue
            L.append(f"\n#### filters inside {key}\n")
            L.append("| filter " + HDR.split("\n")[0])
            L.append("|---" + HDR.split("\n")[1])
            for name, fn in filt.items():
                try:
                    m = fn(g).fillna(False).astype(bool)
                except Exception:
                    continue
                L.append(f"| {name} " + fmt(stats(g[m])))

    L.append("\n## 4. Funnel (sum over symbols)\n")
    for arm in sorted({f["arm"] for f in fun}):
        agg: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for f in fun:
            if f["arm"] != arm:
                continue
            for k, v in f["funnel"].items():
                if k.startswith("_"):
                    continue
                for kk, vv in v.items():
                    agg[k][kk] += vv
        keys = ["seen", "low_score", "dead_gate", "chain_absorbed", "license_cap", "same_zone_quiet",
                "sep2pct", "pre_tp1_open", "tracked", "superseded", "expired", "invalidated",
                "out_of_reach", "geo_dup", "confirmed"]
        L.append(f"\n### arm `{arm}`\n")
        L.append("| setup|tf | " + " | ".join(keys) + " | top dead gates |")
        L.append("|---" * (len(keys) + 2) + "|")
        for k in sorted(agg):
            v = agg[k]
            gates = sorted(((kk[5:], vv) for kk, vv in v.items() if kk.startswith("gate:")), key=lambda x: -x[1])[:3]
            L.append(f"| {k} | " + " | ".join(str(v.get(x, 0)) for x in keys)
                     + " | " + ", ".join(f"{g}:{n}" for g, n in gates) + " |")
    md = "\n".join(L) + "\n"
    with open(a.md, "w") as fh:
        fh.write(md)
    fd = load_fates(a.indir)
    if not fd.empty:
        with open(a.fates_md, "w") as fh:
            fh.write(fates_report(fd))
    if not df.empty:
        keep = ["arm", "symbol", "setup", "tf", "style", "dir", "lane", "score", "confirmed_at", "filled_at",
                "closed_at", "state", "reason", "risk_pct", "tp1_pct", "tp1_r", "hit", "r_gross", "r_net",
                "r_net_slip", "mfe_r", "mae_r", "det_vr", "det_adx", "p1_signal_bar", "stop_clamped",
                "conf_body_atr", "conf_beyond_prev", "conf_vr", "trend_4h", "trend_1d", "entry_type",
                "fast_break", "variant", "det_t"]
        df[[c for c in keep if c in df.columns]].to_csv(a.csv, index=False)
    print(md[:3000])


if __name__ == "__main__":
    main()
