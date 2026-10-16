"""R99q22 reference sheets — ONE real sample per pattern, with its engine reference.

Viva 10-17: «در پایان رفرنس‌های پترن‌ها رو با داده واقعی هر کدام یک نمونه از
ستاپ‌ها یا اسپات بساز تا تایید بکنم». For every live pattern of the law
(analysis/pattern_law.PATTERN_LAW) this tool finds a REAL occurrence — first in
the production signal rows (the setup engines), otherwise by scanning the live
market — renders the chart exactly as a lane would, and staples a reference
band under it: the pattern's international reference (Edwards & Magee /
Bulkowski / Brooks), its Persian rule, the numeric conditions the classifier
tests, and where this sample stands in the selection law (INSIDE / AT_EDGE /
FRESH_BREAK / RETEST_UPPER / RETEST_LOWER / FAILED_BREAK / STALE).

usage: python3 ops/diag/_q22_refs.py [--only WEDGE_FALLING,FLAG_BULL] [--no-db]
       [--out /home/user/refs]
Writes q22ref_<SLUG>.png (chart + band) and q22refs_index.png (contact sheet).
"""
import dataclasses
import os
import sys

sys.path.insert(0, "/home/user/.fresh")
os.chdir("/home/user/.fresh")
os.environ.setdefault("VIVA_NO_FREEZE_WRITE", "1")

from PIL import Image, ImageDraw, ImageFont          # noqa: E402

OUT = "/home/user/refs"
for i, a in enumerate(sys.argv):
    if a == "--out" and i + 1 < len(sys.argv):
        OUT = sys.argv[i + 1]
ONLY = []
for i, a in enumerate(sys.argv):
    if a == "--only" and i + 1 < len(sys.argv):
        ONLY = [x.strip().upper() for x in sys.argv[i + 1].split(",") if x.strip()]
NO_DB = "--no-db" in sys.argv
os.makedirs(OUT, exist_ok=True)

import matplotlib                                   # noqa: E402
matplotlib.use("Agg")
from analysis.fa_text import fa, FONT_BOLD, FONT_REGULAR   # noqa: E402
import bot.messages_v7 as B7                        # noqa: E402
from analysis.candle_counts import fetch_limits     # noqa: E402
from data.fetcher import get_market_bundle, get_klines      # noqa: E402
from analysis.render_kit import detect_patterns, enrich_render   # noqa: E402
from analysis.pattern_law import PATTERN_LAW        # noqa: E402
from analysis.spot_engine import build_spot_alert_candidate  # noqa: E402

TFS = ("15m", "30m", "1h", "4h", "12h", "1d", "3d")
BASKET = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT",
          "ADAUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "ATOMUSDT", "NEARUSDT",
          "APTUSDT", "SUIUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TIAUSDT",
          "SEIUSDT", "LTCUSDT", "BCHUSDT", "DASHUSDT", "ZECUSDT", "XMRUSDT",
          "STXUSDT", "ICPUSDT", "AAVEUSDT", "UNIUSDT", "LDOUSDT", "CRVUSDT",
          "WLDUSDT", "FETUSDT", "RENDERUSDT", "ENAUSDT", "JUPUSDT", "PYTHUSDT",
          "TIAUSDT", "ZROUSDT", "HYPEUSDT", "AEROUSDT")


def slug_of(p: dict) -> str:
    return str(p.get("law_slug") or p.get("type") or "").upper()


def state_rank(s: str) -> int:
    return {"RETEST_UPPER": 0, "RETEST_LOWER": 0, "AT_EDGE": 1, "FRESH_BREAK": 2,
            "FAILED_BREAK": 3, "INSIDE": 4, "TOUCH": 5, "NEAR": 6}.get(str(s), 9)


# ───────────────────────── sample sources ─────────────────────────
def db_samples(target: str):
    """(candidate, df, tag) from a real published row that carries the pattern."""
    if NO_DB:
        return []
    import psycopg2
    from analysis.models import SignalCandidate
    DSN = ("postgresql://postgres.nmndchflpeigorkmqcwi:Viva2026%21.%21@"
           "aws-0-eu-central-1.pooler.supabase.com:5432/postgres")
    cn = psycopg2.connect(DSN, connect_timeout=25)
    cu = cn.cursor()
    cu.execute("""select signal_id, symbol, trigger_tf, setup_code, payload::jsonb
                  from signal_candidates where payload::text like %s
                  order by created_at desc limit 12""", (f"%{target}%",))
    rows = cu.fetchall()
    cn.close()
    found = []
    known = {f.name for f in dataclasses.fields(SignalCandidate)}
    for sid, sym, tf, setup, pl in rows:
        md = dict((pl or {}).get("metadata") or {})
        blob = str(md.get("render_patterns") or []) + str(md.get("pattern_law_all") or [])
        if target not in blob:
            continue
        try:
            cand = SignalCandidate(**{k: v for k, v in pl.items() if k in known})
        except Exception:
            continue
        cand.metadata = md
        md["render_patterns"] = []
        try:
            bundle = get_market_bundle(sym, ("5m", "15m", "30m", "1h", "2h", "4h", "1d"),
                                       limits=fetch_limits())
            trig = bundle.get(str(tf).lower())
            if trig is None or not len(trig):
                trig = get_klines(sym, tf, 400)
            enrich_render(cand, trig)
            if str(setup).upper() == "TECHCLASSIC":
                from analysis.techclassic import tc_refine_geometry
                tc_refine_geometry(cand, bundle)
            elif str(setup).upper() == "ALBROX":
                try:
                    from analysis.albrox import albrox_refine_geometry
                    albrox_refine_geometry(cand, bundle)
                except Exception:
                    pass
        except Exception as exc:
            print(f"    db row {sid[:28]} failed: {exc}")
            continue
        all_slugs = {slug_of(p) for p in (md.get("pattern_law_all") or md.get("render_patterns") or [])}
        if target not in all_slugs:
            continue
        chart_tf = str(md.get("chart_view_tf") or tf).lower()
        df = get_klines(sym, chart_tf, 400)
        found.append((cand, df, f"{sym} {chart_tf} · {setup} · row {str(sid)[-4:]}"))
        if len(found) >= 1:
            break
    return found


def live_sample(target: str):
    """(candidate, df, tag) from a live scan of the market — spot-style render."""
    best = None
    for sym in BASKET:
        try:
            bundle = get_market_bundle(sym, TFS, limits=fetch_limits())
        except Exception:
            continue
        for tf in TFS:
            try:
                df = bundle.get(tf)
            except Exception:
                df = None
            if df is None or len(df) < 60:
                continue
            try:
                pats = detect_patterns(df, "LONG", log_axis=True,
                                       include_past_market=True)
            except Exception:
                continue
            for p in pats:
                if slug_of(p) != target:
                    continue
                st = str(p.get("break_state") or "")
                score = (state_rank(st), 0 if p.get("lines_extended") else 1)
                if best is None or score < best[0]:
                    best = (score, sym, tf, df, dict(p), st)
    if best is None:
        return []
    _score, sym, tf, df, pat, st = best
    try:
        atr = float(df["high"].tail(14).mean() - df["low"].tail(14).mean())
    except Exception:
        atr = float(df["close"].iloc[-1]) * 0.02
    close = float(df["close"].iloc[-1])
    e_up = pat.get("lines") or []
    edge = 0.0
    try:
        from analysis.render_kit import line_y
        if e_up:
            edge = float(line_y(e_up[0], len(df) - 1))
    except Exception:
        edge = close
    if not edge:
        edge = close
    d = PATTERN_LAW.get(target) or {}
    item = {
        "symbol": sym, "tf": tf, "stage": {"AT_EDGE": "NEAR_BREAK",
                                           "RETEST_UPPER": "RETEST",
                                           "RETEST_LOWER": "RETEST",
                                           "INSIDE": "TOUCH"}.get(st, "TOUCH"),
        "close": close, "edge": edge, "atr": atr, "box_top": 0.0,
        "pattern": target, "pattern_fa": d.get("fa") or "",
        "rule_fa": d.get("rule") or "", "side": pat.get("break_side") or "",
        "pattern_commands": [pat],
        "bar_ts": str(df["timestamp"].iloc[-1]) if "timestamp" in df else "",
        "detected_at": "",
    }
    cand = build_spot_alert_candidate(item)
    cand.metadata["select_state"] = st
    cand.metadata["pattern_law_state"] = st
    return [(cand, df, f"{sym} {tf} · live scan · state={st}")]


# ───────────────────────── reference band ─────────────────────────
def band(height=300, width=1568):
    img = Image.new("RGB", (width, height), (17, 20, 24))
    dr = ImageDraw.Draw(img)
    f_big = ImageFont.truetype(FONT_BOLD, 30)
    f_mid = ImageFont.truetype(FONT_BOLD, 21)
    f_sm = ImageFont.truetype(FONT_REGULAR, 18)
    f_fa = ImageFont.truetype(FONT_BOLD, 24)
    f_fa2 = ImageFont.truetype(FONT_REGULAR, 20)
    return img, dr, (f_big, f_mid, f_sm, f_fa, f_fa2)


def compose(chart_png: bytes, slug: str, sample_tag: str, extra: dict) -> str:
    from io import BytesIO
    img = Image.open(BytesIO(chart_png)).convert("RGB")
    W = 1568
    img = img.resize((W, int(img.height * W / img.width)))
    b, dr, (f_big, f_mid, f_sm, f_fa, f_fa2) = band(width=W)
    d = PATTERN_LAW.get(slug) or {}
    dr.rectangle([0, 0, W, 5], fill=(212, 175, 55))
    dr.text((26, 20), f"PATTERN REFERENCE · {slug}", font=f_big, fill=(240, 240, 240))
    dr.text((26, 68), f"ENGINE REF · {d.get('ref') or '-'}", font=f_sm, fill=(150, 200, 255))
    dr.text((26, 100), f"BIAS {d.get('bias')} · BREAK {d.get('break')} · "
                       f"FAMILY {d.get('family')}", font=f_sm, fill=(190, 190, 190))
    dr.text((26, 132), f"NUMERIC CONDITIONS · {d.get('need') or '{}'}", font=f_sm,
            fill=(190, 190, 190))
    dr.text((26, 168), f"SAMPLE · {sample_tag}", font=f_mid, fill=(240, 220, 150))
    st = extra.get("state")
    dr.text((26, 206), f"SELECTION LAW · state={st} · dist={extra.get('dist')} ATR",
            font=f_sm, fill=(150, 230, 190))
    dr.text((26, 236), f"{(extra.get('why') or '')[:120]}", font=f_sm,
            fill=(150, 230, 190))
    # Persian side (RTL), right-aligned
    try:
        dr.text((W - 26, 16), fa(d.get("fa") or ""), font=f_fa, fill=(240, 240, 240),
                anchor="ra")
        lines, cur = [], ""
        for w in str(d.get("rule") or "").split(" "):
            if len(cur) + len(w) > 62:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            lines.append(cur)
        y = 62
        for ln in lines[:4]:
            dr.text((W - 26, y), fa(ln), font=f_fa2, fill=(205, 205, 205), anchor="ra")
            y += 38
        dr.text((W - 26, 236), fa("نمونهٔ واقعی از بازار برای تأییدِ همین رفرنس"),
                font=f_fa2, fill=(170, 170, 170), anchor="ra")
    except Exception as exc:
        print(f"    band persian warning: {exc}")
    out = Image.new("RGB", (W, img.height + b.height), (255, 255, 255))
    out.paste(img, (0, 0))
    out.paste(b, (0, img.height))
    path = os.path.join(OUT, f"q22ref_{slug}.png")
    out.save(path)
    return path


def main():
    targets = ONLY or [k for k in PATTERN_LAW
                       if k not in ("NONE", "TRENDLINE")][:14]
    made = []
    for slug in targets:
        print(f"── {slug}")
        got = db_samples(slug) or live_sample(slug)
        if not got:
            print("   no real sample found")
            continue
        cand, df, tag = got[0]
        md = cand.metadata or {}
        pats = md.get("pattern_law_all") or md.get("render_patterns") or []
        hit = next((p for p in pats if slug_of(p) == slug), {})
        try:
            png = B7.generate_chart(df, cand, confirmed=False)
        except Exception as exc:
            print(f"   render failed: {exc}")
            continue
        if not png:
            print("   render returned nothing")
            continue
        path = compose(png, slug, tag,
                       {"state": hit.get("select_state") or hit.get("break_state"),
                        "dist": hit.get("dist_atr"),
                        "why": (hit.get("select_why") or "")[:90]})
        print(f"   -> {os.path.basename(path)}")
        made.append(path)
    if len(made) > 2:
        cols = 3
        thumbs = [Image.open(p) for p in made]
        tw = 520
        scaled = [t.resize((tw, int(t.height * tw / t.width))) for t in thumbs]
        th = max(s.height for s in scaled)
        rows = (len(scaled) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * (tw + 10) + 10, rows * (th + 10) + 10),
                          (245, 245, 245))
        for i, s in enumerate(scaled):
            sheet.paste(s, (10 + (i % cols) * (tw + 10), 10 + (i // cols) * (th + 10)))
        idx = os.path.join(OUT, "q22refs_index.png")
        sheet.save(idx)
        print(f"index -> {idx} ({len(made)} sheets)")


if __name__ == "__main__":
    main()
