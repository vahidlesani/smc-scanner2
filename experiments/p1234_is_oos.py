"""IS/OOS + regime attribution for P1234 trade-level CSVs."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

RESULTS = Path(__file__).parent / "results"


def stats(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    pnls = df["pnl_pct"].to_numpy(dtype=float)
    wins = int((pnls > 0).sum())
    gp = float(pnls[pnls > 0].sum())
    gl = abs(float(pnls[pnls <= 0].sum()))
    equity = np.cumsum(pnls)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))
    dd = float((peak - np.concatenate([[0.0], equity])).max())
    # max consecutive losses
    streak = mx = 0
    for x in pnls:
        streak = streak + 1 if x <= 0 else 0
        mx = max(mx, streak)
    return {
        "n": int(len(pnls)),
        "wr": round(100 * wins / len(pnls), 1),
        "exp": round(float(pnls.mean()), 4),
        "pf": round(gp / gl, 2) if gl > 0 else (999.0 if gp > 0 else 0.0),
        "sum": round(float(pnls.sum()), 2),
        "max_dd": round(dd, 2),
        "max_consec_loss": mx,
    }


def analyze(path: Path) -> dict:
    df = pd.read_csv(path)
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, format="mixed")
    df = df.sort_values("created_at").reset_index(drop=True)
    cut = int(len(df) * 0.6)
    is_df, oos_df = df.iloc[:cut], df.iloc[cut:]
    out = {
        "file": path.name,
        "span": [str(df["created_at"].min()), str(df["created_at"].max())],
        "all": stats(df),
        "is_60": stats(is_df),
        "oos_40": stats(oos_df),
        "oos_span": [str(oos_df["created_at"].min()), str(oos_df["created_at"].max())] if not oos_df.empty else None,
        "by_direction": {d: stats(g) for d, g in df.groupby("direction")},
        "by_month": {m: stats(g) for m, g in df.groupby(df["created_at"].dt.to_period("M").astype(str))},
        "trades_oos": oos_df[["created_at", "direction", "result", "pnl_pct"]].assign(
            created_at=oos_df["created_at"].astype(str)).to_dict("records"),
    }
    return out


def main() -> None:
    report = {}
    for path in sorted(RESULTS.glob("p1234_trades_*.csv")):
        key = path.stem.replace("p1234_trades_", "")
        report[key] = analyze(path)
    out = RESULTS / "p1234_is_oos.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    for key, r in report.items():
        print(f"== {key} ==  span {r['span'][0][:10]}..{r['span'][1][:10]}")
        for label in ("all", "is_60", "oos_40"):
            print(f"  {label:7s} {json.dumps(r[label])}")
        print(f"  by_dir  {json.dumps(r['by_direction'])}")
        print(f"  by_mon  {json.dumps(r['by_month'])}")
    print(f"saved -> {out}")


if __name__ == "__main__":
    main()
