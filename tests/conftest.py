# r61: the chart-diet flag is an OPERATIONS toggle (Railway diet), not a law.
# The suite verifies chart geometry laws — those tests run with charts ON.
# Settings is a frozen dataclass captured per-module, so the swap is a module
# attribute replace (auto-restored by monkeypatch/finally semantics here).
import dataclasses

import pytest


@pytest.fixture(autouse=True)
def _charts_on_for_law_tests():
    try:
        import bot.messages_v7 as _mv
        _prev = _mv.SETTINGS
        _mv.SETTINGS = dataclasses.replace(_prev, chart_enabled=True)
        yield
        _mv.SETTINGS = _prev
    except Exception:
        yield
