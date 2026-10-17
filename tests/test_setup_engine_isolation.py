"""Behavioral checks for explicit setup routing without deleting ALBROX union lanes."""
from types import SimpleNamespace


def _settings(monkeypatch, setups):
    monkeypatch.setattr(setups, "get_settings",
                        lambda: SimpleNamespace(albrox_enabled=True))


def test_albrox_pattern_lane_is_explicitly_routed_as_albrox(monkeypatch):
    import analysis.setups_experimental as setups
    import analysis.pattern_engine as patterns

    marker = object()
    calls = []

    def pattern_lane(bundle, style, setup_code="TECHCLASSIC"):
        calls.append((bundle.symbol, style, setup_code))
        return marker

    monkeypatch.setattr(patterns, "detect_technoclassic", pattern_lane)
    monkeypatch.setattr(setups, "_albrox_zone_lane",
                        lambda bundle, style: (_ for _ in ()).throw(
                            AssertionError("zone fallback must not run when pattern lane finds a candidate")))
    _settings(monkeypatch, setups)

    result = setups.detect_albrox(SimpleNamespace(symbol="TESTUSDT"), "SWING")
    assert result is marker
    assert calls == [("TESTUSDT", "SWING", "ALBROX")]


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

def test_albrox_pattern_lane_uses_albrox_toggle_not_technoclassic_toggle(monkeypatch):
    from types import SimpleNamespace
    import analysis.pattern_engine as patterns
    import analysis.setups_v7 as setups_v7

    seen = []
    monkeypatch.setattr(patterns, "_s", lambda: SimpleNamespace(
        albrox_enabled=True, technoclassic_enabled=False))
    monkeypatch.setattr(setups_v7, "timeframe_profile",
                        lambda style: ("4h", "1h", "15m"))
    monkeypatch.setattr(setups_v7, "_ensure_frames",
                        lambda bundle, frames: seen.append(tuple(frames)) or False)

    result = patterns.detect_technoclassic(
        SimpleNamespace(symbol="TESTUSDT"), "SWING", setup_code="ALBROX")
    assert result is None
    assert seen == [("4h", "15m")]


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
