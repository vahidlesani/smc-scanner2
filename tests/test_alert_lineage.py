"""Regression tests: Telegram alert cleanup must never be symbol-wide."""
import importlib

from analysis.models import EvidenceItem, SignalCandidate, generate_viva_signal_id, iso_now, utc_now


def _candidate(symbol="BTCUSDT", setup="PINVAL", direction="LONG", zone=100.0, atr=1.0, zone_kind="FVG"):
    return SignalCandidate(
        signal_id=generate_viva_signal_id(symbol, "DAYTRADE", setup), symbol=symbol,
        style="DAYTRADE", setup_code=setup, setup_name=setup, strategy_fa=setup,
        direction=direction, score=8, status="EDUCATIONAL",
        entry_zone_bottom=zone - 0.1, entry_zone_top=zone + 0.1, planned_entry=zone,
        sl=zone - 2 if direction == "LONG" else zone + 2,
        tp1=zone + 2 if direction == "LONG" else zone - 2,
        tp2=zone + 4 if direction == "LONG" else zone - 4,
        rr_tp1=1.0, rr_tp2=2.0, bias="BULLISH" if direction == "LONG" else "BEARISH",
        trigger_timeframe="15m", evidence=[EvidenceItem("x", "x", "x", True, 1)],
        metadata={"atr": atr, "pin_zone_kind": zone_kind},
        created_at=iso_now(), expires_at=(utc_now().replace(year=2027)).isoformat(timespec="seconds"),
    )


def test_independent_same_symbol_alert_is_not_found_or_deleted(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDIDATE_DB_PATH", str(tmp_path / "candidates.sqlite"))
    import database.candidate_store as store
    store = importlib.reload(store)
    store.init_candidate_store()

    older = _candidate(setup="PINVAL", zone=100)
    independent = _candidate(setup="TLBREAK", zone=103)
    assert store.add_candidate(older)
    assert store.find_similar(independent) is None
    assert store.supersede_alert_lineage(independent) == []
    assert [x.signal_id for x in store.get_active_candidates()] == [older.signal_id]


def test_only_same_tight_zone_lineage_is_superseded(tmp_path, monkeypatch):
    monkeypatch.setenv("CANDIDATE_DB_PATH", str(tmp_path / "candidates.sqlite"))
    import database.candidate_store as store
    store = importlib.reload(store)
    store.init_candidate_store()

    original = _candidate(setup="PINVAL", zone=100)
    other_zone = _candidate(setup="PINVAL", zone=101)  # 1 ATR away: separate scenario
    update = _candidate(setup="PINVAL", zone=100.03)   # within 0.08 ATR lineage tolerance
    assert store.add_candidate(original)
    assert store.add_candidate(other_zone)
    assert store.find_similar(update).signal_id == original.signal_id

    removed = store.supersede_alert_lineage(update)
    assert [x.signal_id for x in removed] == [original.signal_id]
    active_ids = {x.signal_id for x in store.get_active_candidates()}
    assert other_zone.signal_id in active_ids
    assert original.signal_id not in active_ids
