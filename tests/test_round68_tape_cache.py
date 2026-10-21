"""Round-68 TAPE CACHE (Viva 10-11: «اول ۳۰۰ تا بگیر نگه‌دار، هر سایکل فقط
کندل زنده رو سینک کن، قدیمی‌ترین حذف»).

One canonical closed tape per (route, symbol, TF): cold-fetch once, then
≤3-bar syncs; every limit slices the same tape (no more per-limit
re-downloads); monitor lanes (use_cache=False) always sync; venue failure
serves the last good tape instead of blinding the lane.
"""
import pandas as pd
import pytest

from data import fetcher


def _bars(n, start="2026-01-01", freq="15min", close0=100.0):
    stamps = pd.date_range(start, periods=n, freq=freq)
    return pd.DataFrame({"timestamp": stamps,
                         "open": close0, "high": close0 + 1,
                         "low": close0 - 1, "close": close0, "volume": 10.0})


class FakeVenue:
    """Mimics _get_klines_bybit's contract: newest window; closed_only drops
    the forming bar; end_ms bounds the window."""

    def __init__(self, frame):
        self.frame = frame.reset_index(drop=True)
        self.calls = []

    def __call__(self, symbol, interval, limit, closed_only, use_cache, end_ms):
        self.calls.append({"limit": int(limit), "closed_only": bool(closed_only),
                           "end_ms": end_ms})
        df = self.frame
        if end_ms is not None:
            cut = pd.Timestamp(int(end_ms), unit="ms")
            df = df[pd.to_datetime(df["timestamp"]) <= cut]
        df = df.tail(int(limit) + (1 if closed_only and end_ms is None else 0))
        df = df.reset_index(drop=True)
        if closed_only and end_ms is None and len(df) > 1:
            df = df.iloc[:-1].reset_index(drop=True)
        return df.copy()

    def roll(self, n=1):
        """Close n new bars (drop oldest), keep the forming bar forming."""
        last = pd.Timestamp(self.frame["timestamp"].iloc[-1])
        step = pd.Timedelta("15min")
        extra = _bars(n, start=last + step, close0=200.0)
        self.frame = pd.concat([self.frame, extra],
                               ignore_index=True).iloc[-len(self.frame):].reset_index(drop=True)


@pytest.fixture()
def venue(monkeypatch):
    fetcher.clear_market_cache()
    v = FakeVenue(_bars(500))
    monkeypatch.setattr(fetcher, "_get_klines_bybit", v)
    monkeypatch.setattr("data.ourbit.ourbit_listed", lambda s: False)
    return v


def test_cold_once_then_every_limit_slices_without_refetch(venue):
    before = fetcher.cost_counters()["kline_calls"]
    a = fetcher.get_klines("AAAUSDT", "15m", 300, closed_only=True)
    assert a is not None and len(a) == 300
    assert fetcher.cost_counters()["kline_calls"] == before + 1
    # A different limit is a DIFFERENT route-cache key — the old code
    # re-downloaded the whole window; the tape serves it with zero venue hit.
    b = fetcher.get_klines("AAAUSDT", "15m", 140, closed_only=True)
    c = fetcher.get_klines("AAAUSDT", "15m", 200, closed_only=True)
    assert len(b) == 140 and len(c) == 200
    assert fetcher.cost_counters()["kline_calls"] == before + 1
    assert list(b["timestamp"]) == list(a["timestamp"])[-140:]
    assert venue.calls[0]["limit"] >= 300   # cold holds ≥300, his number


def test_sync_appends_new_close_and_caps_at_1000(venue):
    fetcher.get_klines("BBBUSDT", "15m", 300, closed_only=True, use_cache=False)
    venue.roll(2)
    out = fetcher.get_klines("BBBUSDT", "15m", 300, closed_only=True, use_cache=False)
    assert pd.Timestamp(out["timestamp"].iloc[-1]) == pd.Timestamp(
        venue.frame["timestamp"].iloc[-2])   # newest CLOSED bar arrived
    assert venue.calls[-1]["limit"] == 3     # syncs are tiny, never 300
    # Drop-oldest: a 1005-bar venue cold-fetched at 1000 keeps the newest 1000.
    venue.frame = _bars(1005)
    fetcher.clear_market_cache()
    big = fetcher.get_klines("CCCUSDT", "15m", 1000, closed_only=True)
    assert len(big) == 1000
    assert pd.Timestamp(big["timestamp"].iloc[0]) == pd.Timestamp(
        venue.frame["timestamp"].iloc[4])


def test_live_row_anchors_the_forming_candle(venue):
    out = fetcher.get_klines("DDDUSDT", "15m", 140, closed_only=False, use_cache=False)
    assert len(out) == 140
    assert pd.Timestamp(out["timestamp"].iloc[-1]) == pd.Timestamp(
        venue.frame["timestamp"].iloc[-1])   # newest row = forming candle
    assert out["timestamp"].is_unique         # no dup timestamps, ever


def test_use_cache_false_always_syncs_but_true_throttles(venue):
    fetcher.get_klines("EEEUSDT", "15m", 300, closed_only=True, use_cache=False)
    n1 = len(venue.calls)
    fetcher.get_klines("EEEUSDT", "15m", 300, closed_only=True, use_cache=False)
    assert len(venue.calls) == n1 + 1        # monitor lanes: always fresh
    # Same data, shallower limits, cache path: sync at most once per 10s.
    fetcher.get_klines("EEEUSDT", "15m", 299, closed_only=True, use_cache=True)
    fetcher.get_klines("EEEUSDT", "15m", 140, closed_only=True, use_cache=True)
    assert len(venue.calls) == n1 + 1        # throttled: zero new venue hit
    # Growth past the tape depth costs ONE full-window fetch, once.
    g = fetcher.get_klines("EEEUSDT", "15m", 350, closed_only=True, use_cache=True)
    assert len(g) == 350 and len(venue.calls) == n1 + 2
    g2 = fetcher.get_klines("EEEUSDT", "15m", 360, closed_only=True, use_cache=True)
    assert len(g2) == 360 and len(venue.calls) == n1 + 3


def test_gap_backfills_instead_of_gapping(venue):
    fetcher.get_klines("FFFUSDT", "15m", 300, closed_only=True, use_cache=False)
    venue.roll(10)   # nobody called for 10 bars — the 3-bar sync can't span it
    out = fetcher.get_klines("FFFUSDT", "15m", 300, closed_only=True, use_cache=False)
    assert len(out) == 300
    diffs = pd.to_datetime(out["timestamp"]).diff().dropna().unique()
    assert len(diffs) == 1 and diffs[0] == pd.Timedelta("15min")  # contiguous
    assert pd.Timestamp(out["timestamp"].iloc[-1]) == pd.Timestamp(
        venue.frame["timestamp"].iloc[-2])


def test_first_write_wins_on_venue_rewrite(venue):
    a = fetcher.get_klines("GGGUSDT", "15m", 300, closed_only=True, use_cache=False)
    orig_close = float(a["close"].iloc[-1])
    # Venue rewrites the same timestamps with different closes (fallback
    # venue disagrees) — the tape keeps what the detector already read.
    venue.frame.loc[venue.frame.index[-2], "close"] = orig_close + 50.0
    b = fetcher.get_klines("GGGUSDT", "15m", 300, closed_only=True, use_cache=False)
    assert float(b["close"].iloc[-1]) == orig_close


def test_venue_failure_serves_last_good_tape(venue, monkeypatch):
    good = fetcher.get_klines("HHHUSDT", "15m", 300, closed_only=True, use_cache=False)
    monkeypatch.setattr(fetcher, "_get_klines_bybit",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("venue down")))
    stale = fetcher.get_klines("HHHUSDT", "15m", 300, closed_only=True, use_cache=False)
    assert stale is not None and len(stale) == len(good)
    assert list(stale["timestamp"]) == list(good["timestamp"])


def test_end_ms_bypasses_the_tape(venue):
    cut = int(pd.Timestamp(venue.frame["timestamp"].iloc[100]).timestamp() * 1000)
    out = fetcher.get_klines("IIIUSDT", "15m", 50, closed_only=True, end_ms=cut)
    assert out is not None and len(out) == 50
    assert venue.calls[-1]["end_ms"] == cut
    assert all(k[1] != "IIIUSDT" for k in fetcher._TAPE)  # history never tapes


def test_clear_resets_tapes_and_counters_exist(venue):
    fetcher.get_klines("JJJUSDT", "15m", 300, closed_only=True)
    assert any(k[1] == "JJJUSDT" for k in fetcher._TAPE)
    fetcher.clear_market_cache()
    assert not any(k[1] == "JJJUSDT" for k in fetcher._TAPE)
    n = len(venue.calls)
    fetcher.get_klines("JJJUSDT", "15m", 300, closed_only=True)
    assert len(venue.calls) == n + 1   # cold refetch after clear
    c = fetcher.cost_counters()
    assert {"kline_calls", "kline_cache_hits", "tape_serves",
            "tape_syncs", "candles_downloaded"} <= set(c)
