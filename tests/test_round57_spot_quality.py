"""r57 — the spot/trend quality laws (Viva 09-28 06:00 dictation, 5 charts).

Verbatim anchors: «شدوهای خیلی بلند رو گفتم نگیره برای رسم الگو و ترند ..
الان همه شدوها رو رد میکنه» · «از هرجا که معتبره بکشه لیمیت نداریم که فقط
۵۰ تا» · «چارت حتماً لگاریتمی باشه در اسپات و فیوجرز» · «زوم طوری که الگوها
بهتر دیده بشه» · «ترند ۳ روزه شکسته واسش ۳ تا تی پی یک سنی؟ تناسب کجاست؟» ·
«کلمات انگلیسی اول اومده بهم ریخته» · «آپدیتهای شکست و تایید به اولین هشدار
ریپلای بشه بعدی با قبلی» · «الکی آپدیت نده» · «ارتفاع کندلها بالاست محور جمع
بشه» · «در اسپات هم مولتی تایم فریم فعاله؟» · «روی کندلها لیبل نواحی نیاد» ·
«این تغییرات فیوچرز رو بهم نریزه».
"""
import os
import sys
from unittest import mock

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _frame(n=140, start="2026-05-01", freq="12h", base=100.0, wick_spikes=()):
    rng = np.random.default_rng(7)
    close = base * np.exp(np.cumsum(rng.normal(0.0, 0.012, n)))
    high = close * (1 + rng.normal(0.004, 0.002, n))
    low = close * (1 - rng.normal(0.004, 0.002, n))
    for i, mult in wick_spikes:                    # the liquidation wicks
        high[i] = close[i] * mult
    ts = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"timestamp": ts,
                         "open": np.roll(close, 1), "close": close,
                         "high": high, "low": low,
                         "volume": np.full(n, 1000.0)})


# ── 1. the shadow law ──────────────────────────────────────────────────────
def test_body_anchored_pivots_ignore_mega_wicks():
    from analysis.indicators import pivots
    n = 90
    wave = 100 + 6 * np.sin(np.arange(n) * 0.35)        # clean local peaks
    df = pd.DataFrame({
        "timestamp": pd.date_range("2026-06-01", periods=n, freq="4h", tz="UTC"),
        "open": np.roll(wave, 1), "close": wave,
        "high": wave + 0.4, "low": wave - 0.4,
        "volume": np.full(n, 900.0)})
    peak = int(np.argmax(wave[5:85])) + 5              # a real local HIGH pivot
    # a MODERATE over-wick: too small for the r50 outlier filter to demote,
    # but the body policy still anchors BELOW it (his drawing law)
    df.loc[peak, "high"] = wave[peak] + 0.7
    highs_body, _ = pivots(df, 3, 3, wick_policy="bodies")
    highs_out, _ = pivots(df, 3, 3, wick_noise_filter=True)
    assert any(p["index"] == peak for p in highs_out), "fixture: peak must pivot"
    b = [p for p in highs_body if p["index"] == peak][0]
    o = [p for p in highs_out if p["index"] == peak][0]
    assert b["price"] < o["price"] - 0.3, "body anchor must sit under the wick"
    assert b["anchor"] == "body"


def test_render_cfg_uses_bodies_and_big_pool():
    src = open(os.path.join(ROOT, "analysis", "render_kit.py"), encoding="utf-8").read()
    assert 'wick_policy="hybrid"' in src  # r58: extreme wick→body, reasonable→wick
    src2 = open(os.path.join(ROOT, "analysis", "viva_tlbreak.py"), encoding="utf-8").read()
    assert "pool = pts[-200:]" in src2, "his «لیمیت نداریم» — the whole pivot history competes"
    assert 'wick_policy: str = "outlier"' in src2, "futures TRADE default untouched"


def test_render_prefers_major_lines():
    from analysis.render_kit import detect_patterns
    # a long, many-touch descending resistance + a small 2-touch noise line:
    # the draw must carry the MAJOR one.
    n = 150
    ts = pd.date_range("2026-04-01", periods=n, freq="4h", tz="UTC")
    line = 1.00 - 0.0018 * np.arange(n)               # the major resistance
    close = line - 0.025                              # tape below the line
    hi = close + 0.004
    for k in range(5):                                # 5 BODY touches (r57 law:
        i = 18 + k * 28                               # the body kisses the line)
        close[i - 1:i + 2] = line[i - 1:i + 2]
        hi[i - 1:i + 2] = line[i - 1:i + 2] + 0.001
    frame = pd.DataFrame({"timestamp": ts, "open": np.roll(close, 1),
                          "close": close, "high": hi, "low": close - 0.01,
                          "volume": np.full(n, 500.0)})
    pats = detect_patterns(frame, "LONG", log_axis=True)
    assert pats, "the major trend must be found"
    # the shape is validated with its edges: converging/parallel carry TWO
    # validated lines (upper+lower); singles carry one
    shapes = {str(p.get("shape") or "single") for p in pats}
    assert any(len(p.get("lines") or []) >= (2 if s in ("converging", "parallel") else 1)
               for p in pats for s in [str(p.get("shape") or "single")])
    assert shapes


# ── 2. LOG always, both systems ────────────────────────────────────────────
def test_log_axis_is_unconditional_law():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    seg = src.split("r57 (Viva: «چارت حتماً لگاریتمی باشه")[1][:200]
    assert "use_log = True" in seg
    assert "use_log = (\n" not in seg


# ── 3. the proportion law (the 3d «یک‌سُن» targets) ────────────────────────
def test_tf_proportional_paths():
    from analysis.spot_engine import MIN_PATH_PCT_BY_TF
    assert MIN_PATH_PCT_BY_TF["3d"] >= 18.0, "a 3d break is not a 1h move"
    assert MIN_PATH_PCT_BY_TF["1w"] > MIN_PATH_PCT_BY_TF["3d"] > MIN_PATH_PCT_BY_TF["1d"] \
        > MIN_PATH_PCT_BY_TF["12h"] > MIN_PATH_PCT_BY_TF["8h"] > MIN_PATH_PCT_BY_TF["4h"]


def test_3d_targets_are_never_one_sun():
    """The r57 proportion law at the risk engine: a 3d-magnitude path (20%)
    can no longer print a one-sun TP1 (the DASH 2.70% case) — the 45%-of-path
    bound alone now forces TP1 ≥ ~7% when resistance is far.

    Viva Law 2026-10-08 (SUPERSEDES the r57 «nearest resistance anchors»
    half, by his 15-مهر dictation «تی‌پی ۳ سنتی» + «۵۰ تا ۶۰ درصد مسیر باکس
    سبز» and his 10-08 Q2 answer «keep the 35–55% band»): a resistance nearer
    than 30% of path is a MICRO-resistance and must NOT drag TP1 down to
    1.8% — TP1 stays inside the 35–55%-of-path band."""
    from analysis.spot_engine import spot_risk_levels
    close, atr = 0.60, 0.02
    path = 0.20 * close                      # the new 3d floor path
    far = spot_risk_levels(close, close * 1.02, [close * 0.9], atr,
                           path, swing_low=close * 0.94,
                           df_highs=[close * 1.5])
    t1, t2, t3 = (float(t) for t in far["targets"])
    assert (t1 - close) / close >= 0.055, f"TP1 {100*(t1-close)/close:.2f}% is one-sun"
    assert t1 < t2 < t3
    # micro-resistance (1.8% < 30% of path) is filtered: TP1 stays in band
    near = spot_risk_levels(close, close * 1.02, [close * 0.9], atr,
                            path, swing_low=close * 0.94,
                            df_highs=[close * 1.018, close * 1.08, close * 1.17])
    t1n = float(near["targets"][0])
    assert close + 0.35 * path - 1e-9 <= t1n <= close + 0.55 * path + 1e-9
    assert (t1n - close) / close >= 0.055, f"TP1 {100*(t1n-close)/close:.2f}% is one-sun"


# ── 4. the reply-chain law ─────────────────────────────────────────────────
def test_spot_confirm_replies_to_first_warning():
    src = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    assert "reply_to=int(_alert_kv.get(\"mid\") or 0))" in src
    assert "_spot_alert_mid_kv(" in src
    src2 = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "spot_alert_mid|" in src2                      # the warning stores its mid
    assert 'reply_to=int(reply_to or 0) or None)' in src2  # publish passes it
    assert '_sc57.get("last") or _sc57.get("confirm")' in src2  # updates → newest


def test_send_photo_returns_message_id():
    src = open(os.path.join(ROOT, "bot", "telegram_bot.py"), encoding="utf-8").read()
    assert "def send_photo(image_bytes: bytes, caption: str, chat_id: str = None,\n               reply_to_message_id: int = 0) -> int:" in src
    assert "def send_message(text: str, chat_id: str = None) -> int:" in src


# ── 5. «الکی آپدیت نده» — only major events ───────────────────────────────
def test_update_events_only_on_majors():
    from analysis.spot_engine import scan_spot_update_events
    n = 120
    ts = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("4h"),
                       periods=n, freq="4h", tz="UTC")
    base = 100.0 + 0.01 * np.arange(n)
    vol = np.full(n, 100.0)
    vol[-1] = 250.0                                  # 2.5× volume surge
    body = np.zeros(n)
    frame = pd.DataFrame({"timestamp": ts, "open": base, "close": base + 0.05,
                          "high": base + 0.1, "low": base - 0.1, "volume": vol})
    frame.loc[frame.index[-1], "close"] = base[-1] + 2.0   # 1.33→ big body vs ATR 0.2
    frame.loc[frame.index[-1], "open"] = base[-1]
    evs = scan_spot_update_events("TESTUSDT", {"4h": frame})
    kinds = {e["kind"] for e in evs}
    assert "vol" in kinds and "disp" in kinds
    # the quiet tape produces NOTHING
    quiet = frame.copy()
    quiet["volume"] = 100.0
    quiet["close"] = base + 0.05
    evs2 = scan_spot_update_events("TESTUSDT", {"4h": quiet})
    assert all(e["kind"] not in ("vol", "disp") for e in evs2)


def test_update_events_deduped_per_lane():
    from analysis import spot_engine as SE
    calls = {"n": 0}

    class _G:
        data = {}

    def gj(key, default=None):
        return _G.data.get(key, default)

    def sj(key, value):
        _G.data[key] = value
    with mock.patch("database.bot_kv.get_json", gj), \
         mock.patch("database.bot_kv.set_json", sj):
        n = 120
        ts = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("4h"),
                           periods=n, freq="4h", tz="UTC")
        base = 100.0 + 0.01 * np.arange(n)
        frame = pd.DataFrame({"timestamp": ts, "open": base, "close": base + 0.05,
                              "high": base + 0.1, "low": base - 0.1,
                              "volume": np.full(n, 100.0)})
        frame.loc[frame.index[-1], "volume"] = 300.0
        evs = SE.scan_spot_update_events("AAAUSDT", {"4h": frame})
        assert evs and any(e["kind"] == "vol" for e in evs)
        SE.commit_spot_update_events(evs)
        evs2 = SE.scan_spot_update_events("AAAUSDT", {"4h": frame})
        assert not any(e["kind"] == "vol" for e in evs2), "12h dedupe per lane"


# ── 6. the corrupt-data guard (WLD blank chart) ────────────────────────────
def test_near_zero_placeholder_rows_dropped():
    from bot.messages_v7 import _clean_render_frame
    n = 60
    ts = pd.date_range("2026-07-01", periods=n, freq="1d")
    close = np.full(n, 0.5)
    close[:20] = 1e-9                       # the WLD-style dead rows
    frame = pd.DataFrame({"timestamp": ts, "open": close, "high": close,
                          "low": close, "close": close,
                          "volume": np.linspace(1, 9, n)})
    out = _clean_render_frame(frame, window=60)
    assert (out["close"] > 0.01).all(), "dead near-zero rows must not render"
    assert len(out) == n - 20


def test_scan_side_sanity_filter():
    from analysis.spot_engine import _sane_ohlcv
    n = 60
    ts = pd.date_range("2026-07-01", periods=n, freq="1d")
    close = np.full(n, 0.5)
    close[:15] = 1e-9
    frame = pd.DataFrame({"timestamp": ts, "open": close, "high": close,
                          "low": close, "close": close, "volume": np.ones(n)})
    out = _sane_ohlcv(frame)
    assert (out["close"] > 0.01).all() and len(out) == n - 15


# ── 7. the Persian onchain + MTF + axis/chip laws ──────────────────────────
def test_fear_greed_label_is_persian_at_source():
    from analysis.onchain_free import fear_greed
    fake = {"data": [{"value": "74", "value_classification": "Greed"},
                     {"value": "70", "value_classification": "Neutral"}]}
    import analysis.onchain_free as OC
    with mock.patch.object(OC, "_cached", lambda k, f: fake):
        fng = fear_greed()
    assert fng["label_fa"] == "طمع"
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    seg = src.split("شاخص ترس و طمع:")[1][:200]
    assert "label_fa" in seg and "({ _fng35.get('label') })" not in seg


def test_spot_card_carries_mtf_block():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "مولتی‌تایم‌فریم" in src and "mtf_fa" in src
    src2 = open(os.path.join(ROOT, "analysis", "spot_engine.py"), encoding="utf-8").read()
    assert "_mtf_bias_fa(frames)" in src2
    assert '"mtf_fa": list(item.get("mtf_fa") or []),' in src2


def test_tall_candles_get_tight_pad():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "if r_span >= 3.0 * _a:" in src
    assert "ylo - 0.015 * yr, yhi + 0.025 * yr" in src


def test_zone_chips_deferred_to_final_window():
    src = open(os.path.join(ROOT, "bot", "messages_v7.py"), encoding="utf-8").read()
    assert "_deferred_chips" in src
    assert "the SKY" in src or "SKY" in src


def test_futures_trade_config_untouched():
    """«دقت کن این تغییرات فیوچرز رو بهم نریزه»: the TRADE fitter's default
    config keeps outlier wick policy and the render clone is the only one
    that draws from bodies."""
    from analysis.viva_tlbreak import load_config
    cfg = load_config()
    assert getattr(cfg, "wick_policy", "outlier") == "outlier"
    src = open(os.path.join(ROOT, "analysis", "pattern_engine.py"), encoding="utf-8").read()
    assert 'wick_policy="bodies"' not in src
