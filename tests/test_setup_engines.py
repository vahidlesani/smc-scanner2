"""R99a — registry tests: per-setup engine ownership declarations."""
import importlib

from analysis.setup_engines import (
    SETUP_ENGINES, SHARED_ENGINES, get_setup_engine,
    setup_line_keys, setup_has_zones,
)


def test_registry_has_four_setups():
    assert sorted(SETUP_ENGINES) == [
        "ALBROX", "PINVAL", "TECHCLASSIC", "TLBREAK"]


def test_registry_detectors_resolve():
    for code, entry in SETUP_ENGINES.items():
        assert entry["detectors"], code
        for dotted in entry["detectors"]:
            mod_name, attr = dotted.rsplit(".", 1)
            mod = importlib.import_module(mod_name)
            obj = getattr(mod, attr)
            if isinstance(obj, (list, tuple)):
                assert all(callable(f) for f in obj), (code, dotted)
            else:
                assert callable(obj), (code, dotted)


def test_registry_line_keys_nonempty_and_unique_per_setup():
    for code, entry in SETUP_ENGINES.items():
        keys = entry["line_keys"]
        assert keys, code
        assert len(keys) == len(set(keys)), code


def test_zones_only_albrox():
    assert setup_has_zones("ALBROX") is True
    assert setup_has_zones("PINWALL") is False  # R99j: retired (r40)
    assert setup_has_zones("TECHCLASSIC") is False
    assert setup_has_zones("TLBREAK") is False
    assert setup_has_zones("PINVAL") is False
    assert setup_has_zones("NOPE") is False


def test_helpers_unknown_setup_safe():
    assert get_setup_engine("NOPE") is None
    assert get_setup_engine("") is None
    assert setup_line_keys("NOPE") == []


def test_shared_engines_declared():
    assert "analysis.render_kit" in SHARED_ENGINES
    assert "analysis.snapshot_lock" in SHARED_ENGINES
    assert len(SHARED_ENGINES) >= 4
