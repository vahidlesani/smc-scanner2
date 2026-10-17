"""Behavioral checks that setup-specific candidate engines stay isolated."""
from types import SimpleNamespace

import pytest


def test_albrox_uses_its_own_zone_lane_not_the_techclassic_candidate_builder(monkeypatch):
    import analysis.setups_experimental as setups
    import analysis.pattern_engine as patterns

    marker = object()
    monkeypatch.setattr(setups, "get_settings",
                        lambda: SimpleNamespace(albrox_enabled=True))
    monkeypatch.setattr(setups, "_albrox_zone_lane",
                        lambda bundle, style: marker)

    def forbidden_tc_call(*args, **kwargs):
        pytest.fail("ALBROX must not borrow TECHCLASSIC's candidate/entry engine")

    monkeypatch.setattr(patterns, "detect_technoclassic", forbidden_tc_call)
    result = setups.detect_albrox(SimpleNamespace(symbol="TESTUSDT"), "SWING")
    assert result is marker
