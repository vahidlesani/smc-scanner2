"""ماتریس رندر مرحلهٔ ۱ — اسپات (سبک CryptoCove بدون مارک) + پرپچوآل (سفید).
داده: experiments/sample_klines واقعی. خروجی: /home/user/renders_stage1/
"""
import gzip
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis import engine_spot, engine_perp
from tools import render_spot_cryptocove as rs
from tools import render_perp_white as rp

OUT = Path("/home/user/renders_stage1")
OUT.mkdir(parents=True, exist_ok=True)
KL = ROOT / "experiments" / "sample_klines"


def load(sym, tf):
    name = f"{sym}USDT_{tf}_*.csv.gz"
    hits = sorted(KL.glob(name))
    if not hits:
        return None
    with gzip.open(hits[0], "rt") as f:
        df = pd.read_csv(f)
    return df


def resample(df, rule):
    d = df.copy()
    d["ts"] = pd.to_datetime(d["timestamp"])
    d = d.set_index("ts").resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last",
         "volume": "sum"}).dropna().reset_index()
    d["timestamp"] = d["ts"].dt.strftime("%Y-%m-%d %H:%M:%S")
    return d.drop(columns=["ts"])


summary = []


def run_spot(sym, tf, df, tag):
    a = engine_spot.analyze(df, tf)
    if not a:
        summary.append({"tag": tag, "engine": "SPOT", "pattern": None})
        return
    p = rs.render(df, a, str(OUT / f"spot_{tag}.png"), symbol=f"{sym}USDT")
    summary.append({"tag": tag, "engine": "SPOT", "pattern": a["slug"],
                    "tf": tf, "bars": a["view"]["bars"], "fill": round(a["view"]["fill"], 2),
                    "break": a["breakout"]["status"], "actionable": a["actionable_long"],
                    "target_pct": round((a["target"] / a["level"] - 1) * 100, 1) if a["level"] else None})


def run_perp(sym, tf, brand, df, tag):
    a = engine_perp.analyze(df, tf, brand)
    if not a:
        summary.append({"tag": tag, "engine": "PERP", "pattern": None})
        return
    rp.render(df, a, str(OUT / f"perp_{tag}.png"), symbol=f"{sym}USDT")
    summary.append({"tag": tag, "engine": "PERP", "brand": brand, "pattern": a["slug"],
                    "tf": tf, "side": a["side"], "bars": a["view"]["bars"],
                    "fill": round(a["view"]["fill"], 2), "break": a["breakout"]["status"]})


btc4h = load("BTC", "4h")
btc1d = load("BTC", "1d")
eth4h = load("ETH", "4h")
eth15m = load("ETH", "15m")
sol4h = load("SOL", "4h")
sol1d = load("SOL", "1d")
sui1d = load("SUI", "1d")
sui4h = load("SUI", "4h")

run_spot("BTC", "4h", btc4h, "BTC_4h")
run_spot("BTC", "1d", btc1d, "BTC_1d")
run_spot("ETH", "4h", eth4h, "ETH_4h")
run_spot("SOL", "1d", sol1d, "SOL_1d")
run_spot("SUI", "1d", sui1d, "SUI_1d")
run_spot("BTC", "3d", resample(btc1d, "3D"), "BTC_3d")
# زوم/تعداد کندل متفاوت — هندسه باید بماند
run_spot("BTC", "4h", btc4h.tail(300).reset_index(drop=True), "BTC_4h_zoom300")
run_spot("BTC", "4h", btc4h.tail(240).reset_index(drop=True), "BTC_4h_zoom240")

run_perp("BTC", "4h", "ALBROX", btc4h, "BTC_4h_albrox")
run_perp("ETH", "15m", "PINVAL", eth15m.tail(1500).reset_index(drop=True), "ETH_15m_pinval")
run_perp("ETH", "15m", "PINVAL", eth15m.tail(1000).reset_index(drop=True), "ETH_15m_pinval_z1000")
run_perp("SOL", "4h", "TECHCLASSIC", sol4h, "SOL_4h_tc")
run_perp("SUI", "4h", "ALBROX", sui4h, "SUI_4h_albrox")

print(json.dumps(summary, ensure_ascii=False, indent=1))
