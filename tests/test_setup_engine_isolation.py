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
