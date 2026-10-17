"""Behavioral checks for explicit setup routing without deleting ALBROX union lanes."""
from types import SimpleNamespace


def _settings(monkeypatch, setups):
    monkeypatch.setattr(setups, "get_settings",
                        lambda: SimpleNamespace(albrox_enabled=True))


def test_albrox_pattern_lane_is_explicitly_routed_and_precedes_zone_lane(monkeypatch):
    import analysis.setups_experimental as setups

    marker = object()
    calls = []
    monkeypatch.setattr(setups, "_albrox_pattern_lane",
                        lambda bundle, style: calls.append((bundle.symbol, style)) or marker)
    monkeypatch.setattr(setups, "_albrox_zone_lane",
                        lambda bundle, style: (_ for _ in ()).throw(
                            AssertionError("zone fallback must not run when pattern lane finds a candidate")))
    _settings(monkeypatch, setups)

    result = setups.detect_albrox(SimpleNamespace(symbol="TESTUSDT"), "SWING")
    assert result is marker
    assert calls == [("TESTUSDT", "SWING")]


def test_albrox_falls_back_to_its_zone_lane_when_pattern_lane_has_no_candidate(monkeypatch):
    import analysis.setups_experimental as setups
    import analysis.pattern_engine as patterns

    marker = object()
    monkeypatch.setattr(patterns, "detect_technoclassic",
                        lambda bundle, style, setup_code="TECHCLASSIC": None)
    monkeypatch.setattr(setups, "_albrox_zone_lane", lambda bundle, style: marker)
    _settings(monkeypatch, setups)

    result = setups.detect_albrox(SimpleNamespace(symbol="TESTUSDT"), "SWING")
    assert result is marker

def test_albrox_pattern_lane_uses_shared_geometry_not_techclassic_candidate_builder():
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / "analysis" / "setups_experimental.py"
    text = source.read_text(encoding="utf-8")
    start = text.index("def _albrox_pattern_lane(")
    end = text.index("\ndef detect_albrox(", start)
    body = text[start:end]
    assert "scan_edges" in body
    assert "SignalCandidate(" in body
    assert "_build_candidate" not in body
    assert "detect_technoclassic" not in body


def test_technoclassic_toggle_still_controls_technoclassic_lane(monkeypatch):
    from types import SimpleNamespace
    import analysis.pattern_engine as patterns
    import analysis.setups_v7 as setups_v7

    def unexpected(*args, **kwargs):
        raise AssertionError("disabled TECHCLASSIC should return before frame access")

    monkeypatch.setattr(patterns, "_s", lambda: SimpleNamespace(
        albrox_enabled=True, technoclassic_enabled=False))
    monkeypatch.setattr(setups_v7, "_ensure_frames", unexpected)

    result = patterns.detect_technoclassic(
        SimpleNamespace(symbol="TESTUSDT"), "SWING", setup_code="TECHCLASSIC")
    assert result is None


def test_shared_pattern_geometry_has_setup_scoped_mint_guards():
    import analysis.pattern_engine as patterns

    bundle = SimpleNamespace(symbol="ETHUSDT")
    event = {
        "pattern_tf": "4h",
        "pattern": "WEDGE_FALLING",
        "side": "UPPER",
        "edge_points": [
            {"timestamp": "2026-10-16T00:00:00Z", "price": 100.0},
            {"timestamp": "2026-10-17T00:00:00Z", "price": 105.0},
        ],
    }
    tc = patterns._mint_guard_key(bundle, event, "TECHCLASSIC")
    albrox = patterns._mint_guard_key(bundle, event, "ALBROX")
    assert tc.startswith("TCMINT|ETHUSDT|")
    assert albrox.startswith("ALBROXMINT|ETHUSDT|")
    assert tc != albrox
    assert tc == patterns._mint_guard_key(bundle, event, "TECHCLASSIC")

def test_albrox_pattern_lane_mints_candidate_without_techclassic_builder(monkeypatch):
    import pandas as pd
    from types import SimpleNamespace
    import analysis.pattern_engine as patterns
    import analysis.setups_experimental as setups
    import analysis.trade_management as tm
    import analysis.render_kit as render
    import analysis.pattern_law as law

    ts = pd.date_range("2026-10-16", periods=70, freq="4h")
    frame = pd.DataFrame({
        "timestamp": ts,
        "open": [100.0] * 70,
        "high": [103.0] * 70,
        "low": [99.0] * 70,
        "close": [101.0] * 70,
        "volume": [1000.0] * 70,
    })
    event = {
        "state": "BREAK_CLOSED", "direction": "LONG", "line_price": 100.0,
        "side": "upper", "pattern": "WEDGE_FALLING", "pattern_tf": "4h",
        "structure_score": 7, "touches": 3, "fit_error_atr": 0.2,
        "measured": {"to": 110.0}, "edge_points": [
            {"timestamp": "2026-10-16T00:00:00Z", "price": 98.0},
            {"timestamp": "2026-10-16T12:00:00Z", "price": 100.0},
        ],
    }
    bundle = SimpleNamespace(symbol="ETHUSDT", ticker={"last_price": 101.0},
                              get=lambda tf: frame)
    monkeypatch.setattr(setups, "timeframe_profile", lambda style: ("4h", "1h", "15m"))
    monkeypatch.setattr(setups, "_ensure_frames", lambda bundle, frames: True)
    monkeypatch.setattr(patterns, "scan_edges", lambda *a, **k: [event])
    monkeypatch.setattr(tm, "structural_buffer", lambda entry: 0.1)
    monkeypatch.setattr(tm, "clamp_stop_price", lambda entry, direction, stop, tf: (stop, False))
    monkeypatch.setattr(tm, "clamp_path_to_band", lambda entry, tf, desired: (desired, "TEST"))
    monkeypatch.setattr(tm, "sane_zone_geometry_ok", lambda *a, **k: True)
    monkeypatch.setattr(render, "enrich_render", lambda *a, **k: None)
    monkeypatch.setattr(law, "engine_stamp", lambda *a, **k: {})
    monkeypatch.setattr(patterns, "detect_technoclassic",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("ALBROX must not call TECHCLASSIC candidate builder")))

    cand = setups._albrox_pattern_lane(bundle, "DAYTRADE")
    assert cand is not None
    assert cand.setup_code == "ALBROX"
    assert cand.direction == "LONG"
    assert cand.metadata["strategy_variant"] == "ALBROX_PATTERN_BREAK"
    assert cand.metadata["selected_pattern_slug"] == "WEDGE_FALLING"
