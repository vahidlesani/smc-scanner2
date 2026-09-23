"""Round 16 queue item — free on-chain / flow context (priority ONLY).

Viva's standing rule: «سرویس پولی آنچین نه — فقط مسیرهای رایگان» و «اولویتدهی
رصد، هرگز گیت». These tests pin exactly that contract:

  * the module never raises, never blocks a scan and never returns a veto,
  * no data (dead API, no key, unknown symbol) = neutral, not "bearish",
  * ordering is stable: alert-pinned symbols first, the watchlist head keeps
    its place, only the tail may be re-ordered by turnover,
  * the spot lane gets the ordered list; the futures scan order is untouched,
  * the context line is Persian and one line.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def oc(monkeypatch):
    import importlib
    import analysis.onchain_free as mod
    importlib.reload(mod)
    mod._CACHE.clear()
    mod._ID_CACHE.clear()
    monkeypatch.setenv("ONCHAIN_FREE_ENABLED", "on")
    return mod


# ───────────────────────────── fail-open behaviour ─────────────────────────────
def test_every_provider_failure_is_swallowed(oc, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(oc, "_get_json", boom)
    assert oc.market_snapshot() == {} or "fetched_at" in oc.market_snapshot()
    assert oc.fear_greed() == {}
    assert oc.dex_tide() == {}
    assert oc.symbol_stats(["BTCUSDT"]) == {}
    assert oc.context_line_fa() == ""
    assert oc.priority_bump("BTCUSDT", {}) == 0.0
    assert oc.order_symbols(["A", "B", "C"]) == ["A", "B", "C"]


def test_http_error_or_garbage_json_is_not_fatal(oc, monkeypatch):
    monkeypatch.setattr(oc, "_get_json", lambda *a, **k: {"junk": [1, 2]})
    assert oc.fear_greed() == {}
    assert oc.dex_tide() == {}
    assert oc.symbol_stats(["BTCUSDT"]) == {}
    monkeypatch.setattr(oc, "_get_json", lambda *a, **k: "not-a-dict")
    assert oc.symbol_stats(["BTCUSDT"]) == {}


def test_disabled_switch_makes_the_module_inert(oc, monkeypatch):
    monkeypatch.setenv("ONCHAIN_FREE_ENABLED", "off")
    import importlib
    importlib.reload(oc)
    assert oc.market_snapshot() == {}
    assert oc.symbol_stats(["BTCUSDT"]) == {}
    assert oc.priority_bump("BTCUSDT", {"BTCUSDT": {"turnover": 0.5}}) == 0.0


# ─────────────────────────────── live payloads ───────────────────────────────
def test_fear_greed_and_dex_parse(oc, monkeypatch):
    monkeypatch.setattr(oc, "_get_json", lambda url, *a, **k: {
        "fng": {"data": [{"value": "71", "value_classification": "Greed"},
                         {"value": "78"}]},
        "dex": {"total24h": 11_278_257_432.2, "change_1d": -18.99},
    }.get("fng" if "alternative" in url else "dex"))
    fng = oc.fear_greed()
    assert fng == {"value": 71, "label": "Greed", "prev": 78}
    tide = oc.dex_tide()
    assert tide["change_1d_pct"] == pytest.approx(-18.99)
    assert tide["volume_24h"] > 1e10


def test_symbol_stats_compute_turnover(oc, monkeypatch):
    monkeypatch.setattr(oc, "_get_json", lambda url, *a, **k: [
        {"id": "solana", "total_volume": 5_231_563_753.0,
         "market_cap": 67_232_593_977.0, "price_change_percentage_24h": -3.29},
        {"id": "sui", "total_volume": 1_107_000_531.0,
         "market_cap": 3_937_628_021.0, "price_change_percentage_24h": -4.75},
    ])
    monkeypatch.setitem(oc._KNOWN_IDS, "SOLUSDT", "solana")
    monkeypatch.setitem(oc._KNOWN_IDS, "SUIUSDT", "sui")
    stats = oc.symbol_stats(["SOLUSDT", "SUIUSDT"])
    assert stats["SOLUSDT"]["turnover"] == pytest.approx(0.0778, abs=1e-3)
    assert stats["SUIUSDT"]["turnover"] == pytest.approx(0.2811, abs=1e-3)
    # a hot tape ranks above a sleepy one, and both are > 0
    assert oc.priority_bump("SUIUSDT", stats) > oc.priority_bump("SOLUSDT", stats) > 0


def test_unknown_symbol_is_neutral_not_negative(oc, monkeypatch):
    monkeypatch.setattr(oc, "_get_json", lambda *a, **k: {"coins": []})
    assert oc.priority_bump("NOPEUSDT", {}) == 0.0
    assert oc.symbol_stats(["NOPEUSDT"]) == {}


def test_responses_are_cached(oc, monkeypatch):
    calls = {"n": 0}

    def counting(url, *a, **k):
        calls["n"] += 1
        return [{"id": "bitcoin", "total_volume": 1.0, "market_cap": 10.0,
                 "price_change_percentage_24h": 1.0}]

    monkeypatch.setattr(oc, "_get_json", counting)
    monkeypatch.setitem(oc._KNOWN_IDS, "BTCUSDT", "bitcoin")
    oc.symbol_stats(["BTCUSDT"])
    oc.symbol_stats(["BTCUSDT"])
    assert calls["n"] == 1


# ─────────────────────────────── ordering law ───────────────────────────────
def test_order_keeps_pinned_first_and_head_in_place(oc, monkeypatch):
    universe = [f"S{i}USDT" for i in range(12)]
    monkeypatch.setattr(oc, "symbol_stats",
                        lambda syms, max_calls=25: {s: {"turnover": 0.30} for s in syms})
    ordered = oc.order_symbols(universe, pinned=["S9USDT", "S3USDT"], head=3)
    assert ordered[:2] == ["S9USDT", "S3USDT"]          # open alerts keep their order
    assert ordered[2:5] == universe[:3]                 # the head never moves
    assert sorted(ordered) == sorted(universe)           # pure re-order, no loss


def test_order_is_stable_when_everything_is_hot(oc, monkeypatch):
    universe = [f"S{i}USDT" for i in range(10)]
    monkeypatch.setattr(oc, "symbol_stats", lambda syms, max_calls=25: {s: {"turnover": 1.0} for s in syms})
    assert oc.order_symbols(universe, head=2) == universe


def test_order_survives_a_broken_provider(oc, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(oc, "symbol_stats", boom)
    assert oc.order_symbols(["A", "B", "C"], head=1) == ["A", "B", "C"]


def test_context_line_is_one_persian_line(oc, monkeypatch):
    monkeypatch.setattr(oc, "_get_json", lambda url, *a, **k: (
        {"data": [{"value": "71", "value_classification": "Greed"}]}
        if "alternative" in url else {"total24h": 1e10, "change_1d": -19.0}))
    line = oc.context_line_fa()
    assert line and "\n" not in line
    assert "ترس" in line and "DEX" in line


# ─────────────────────────── scan wiring (never a gate) ───────────────────────────
def _main_src() -> str:
    return open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "main.py"), encoding="utf-8").read()


def test_spot_lane_uses_the_flow_order():
    src = _main_src()
    start = src.index("def run_spot_scan")
    body = src[start:src.index("\ndef ", start + 5)]
    assert "_oc.order_symbols(symbols, head=_head)" in body
    assert "SPOT_FLOW_HEAD" in body
    assert "context only, never a gate" in body


def test_the_futures_scan_order_is_not_re_ordered():
    """Viva's law «سیستم فعلی نریزه»: the discovery queue (alert-first) must
    stay exactly as it was — the flow module may only log there."""
    src = _main_src()
    start = src.index("def run_discovery_scan")
    end = src.index("\ndef ", start + 5)          # the next top-level def
    scan = src[start:end]
    assert "onchain_free" in scan            # context line for the log
    assert "order_symbols" not in scan       # …but no reshuffle of the queue


def test_flow_context_is_reported_once_per_scan():
    src = _main_src()
    assert 'stats["flow_context"] = _ctx_line' in src
    assert "Flow context (context only, never a gate)" in src
