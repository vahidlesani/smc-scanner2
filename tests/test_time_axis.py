"""Viva 09-20 time-axis law — regression guards.

The tool (entry / stop / TP ladder / trendline) must NEVER slide along the
time axis. The alerts and confirmation charts stay pinned to the trigger TF;
the lifecycle renders (TP hits, live charts, final results) step the SAME
anchored tool up to a higher TF once candles have outrun it, and the message
carries the one/two-line Persian explanation he ordered.
"""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from analysis.models import SignalCandidate, iso_now
from analysis.render_kit import detect_zones, enrich_render
from bot.messages_v7 import (_event_chart_candidate, _lifecycle_view_plan,
                             LIFECYCLE_SWITCH_AFTER_BARS)


def _frame(periods=90, freq="15min", start="2026-01-01 00:00"):
    ts = pd.date_range(start, periods=periods, freq=freq)
    closes = [100.0 + (i % 7) * 0.12 - (i % 5) * 0.09 for i in range(periods)]
    return pd.DataFrame({
        "timestamp": ts,
        "open": [c - 0.05 for c in closes],
        "high": [c + 0.25 for c in closes],
        "low": [c - 0.24 for c in closes],
        "close": closes,
        "volume": [1000 + (i % 11) * 40 for i in range(periods)],
        "turnover": [1e5 + i for i in range(periods)],
    })


_NOW_REF = pd.Timestamp("2026-09-20 12:00:00")


def _candidate(tf="15m", anchor_min_ago=20.0, entry_min_ago=20.0):
    now = _NOW_REF
    cand = SignalCandidate(
        signal_id="viva-BTC-SC-LSR-0920-TEST", symbol="BTCUSDT", style="DAYTRADE",
        setup_code="LSR", setup_name="LSR", strategy_fa="جمع‌آوری نقدینگی",
        direction="LONG", score=8, status="CONFIRMED",
        entry_zone_bottom=99.0, entry_zone_top=100.0, planned_entry=99.5,
        sl=98.0, tp1=106.0, tp2=110.0, rr_tp1=2.0, rr_tp2=3.0,
        bias="BULLISH", trigger_timeframe=tf,
    )
    cand.confirmed_at = now.isoformat(sep=" ")
    cand.metadata = {
        "tool_anchor_ts": str(now - pd.Timedelta(minutes=anchor_min_ago)),
        "tool_entry_ts": str(now - pd.Timedelta(minutes=entry_min_ago)),
    }
    return cand


class ViewPlanTests(unittest.TestCase):
    def test_young_tool_stays_on_trigger_tf(self):
        view, escaped, note = _lifecycle_view_plan(
            _candidate(entry_min_ago=15 * 20), now=_NOW_REF)
        self.assertEqual(view, "15m")
        self.assertLessEqual(escaped, LIFECYCLE_SWITCH_AFTER_BARS)
        self.assertEqual(note, "")

    def test_exactly_40_candles_is_still_the_trigger_tf(self):
        view, escaped, note = _lifecycle_view_plan(
            _candidate(anchor_min_ago=95 * 15, entry_min_ago=40 * 15),
            now=_NOW_REF)
        self.assertEqual(view, "15m")
        self.assertEqual(note, "")

    def test_41_escaped_candles_step_up_to_1h_with_note(self):
        view, escaped, note = _lifecycle_view_plan(
            _candidate(anchor_min_ago=96 * 15, entry_min_ago=41 * 15),
            now=_NOW_REF)
        self.assertEqual(view, "1h")
        self.assertEqual(escaped, 41)
        self.assertIn("۴۱ کندل ۱۵ دقیقه", note)
        self.assertIn("تایم فریم ۱ ساعته", note)
        self.assertIn("جابه‌جا نشده", note)

    def test_very_old_tool_steps_all_the_way_to_4h(self):
        view, _escaped, note = _lifecycle_view_plan(
            _candidate(anchor_min_ago=900 * 15, entry_min_ago=700 * 15),
            now=_NOW_REF)
        self.assertEqual(view, "4h")
        self.assertIn("۴ ساعته", note)

    def test_1d_tool_has_nowhere_to_step(self):
        view, _escaped, note = _lifecycle_view_plan(
            _candidate(tf="1d", anchor_min_ago=200 * 1440,
                       entry_min_ago=120 * 1440), now=_NOW_REF)
        self.assertEqual(view, "1d")
        self.assertEqual(note, "")

    def test_missing_anchors_fail_safe_to_trigger_tf(self):
        cand = _candidate()
        cand.metadata = {}
        cand.confirmed_at = ""
        cand.created_at = ""
        view, escaped, note = _lifecycle_view_plan(cand, now=_NOW_REF)
        self.assertEqual(view, "15m")
        self.assertEqual((escaped, note), (0, ""))


class RenderCommandAnchorTests(unittest.TestCase):
    def test_enrich_render_stamps_tool_anchor_once(self):
        cand = _candidate()
        cand.metadata = {}
        frame = _frame(90)
        enrich_render(cand, frame)
        expected = str(frame["timestamp"].iloc[90 - 55])
        self.assertEqual(cand.metadata["tool_anchor_ts"], expected)
        # a later call must NOT move the anchor (no sliding)
        enrich_render(cand, _frame(90, start="2026-01-01 12:00"))
        self.assertEqual(cand.metadata["tool_anchor_ts"], expected)

    def test_zones_and_lines_carry_origin_timestamps(self):
        cand = _candidate()
        cand.metadata = {}
        frame = _frame(90)
        enrich_render(cand, frame)
        for zone in (cand.metadata.get("render_zones") or []):
            self.assertIn("ts0", zone)
            self.assertIsInstance(zone["ts0"], str)
        for watch in (cand.metadata.get("render_line_watch") or []):
            self.assertIn("ts0", watch)

    def test_zone_ts0_matches_its_origin_bar(self):
        frame = _frame(90)
        zones = detect_zones(frame, "LONG", 0.0, 0.0)
        for zone in zones:
            if zone["ts0"]:
                self.assertEqual(zone["ts0"], str(frame["timestamp"].iloc[zone["x0"]]))


class EventAnchorTests(unittest.TestCase):
    def test_event_candidate_carries_fill_time_as_tool_entry(self):
        cand = _event_chart_candidate({
            "signal_id": "viva-BTC-SC-LSR-0920-TEST", "symbol": "BTCUSDT",
            "direction": "LONG", "entry": 99.5, "original_sl": 98.0,
            "targets": [106.0, 110.0, 113.0], "style": "DAYTRADE",
            "source": "LSR", "trigger_timeframe": "15m",
            "confirmed_at": "2026-09-20 10:00:00",
            "entry_filled_at": "2026-09-20 10:15:00",
        })
        self.assertEqual(cand.metadata["tool_entry_ts"], "2026-09-20 10:15:00")
        self.assertEqual(cand.metadata["tool_anchor_ts"], "2026-09-20 10:00:00")

    def test_event_candidate_falls_back_to_confirmed_at(self):
        cand = _event_chart_candidate({
            "signal_id": "viva-BTC-SC-LSR-0920-TEST2", "symbol": "BTCUSDT",
            "direction": "SHORT", "entry": 99.5, "original_sl": 101.0,
            "targets": [96.0, 93.0], "style": "DAYTRADE", "source": "LSR",
            "trigger_timeframe": "1h", "confirmed_at": "2026-09-20 10:00:00",
        })
        self.assertEqual(cand.metadata["tool_entry_ts"], "2026-09-20 10:00:00")


class LifecycleFrameFallbackTests(unittest.TestCase):
    def test_venue_without_higher_frame_falls_back_without_note(self):
        from bot.messages_v7 import _lifecycle_chart_frame
        cand = _candidate(anchor_min_ago=200 * 15, entry_min_ago=120 * 15)
        cand.confirmed_at = _NOW_REF.isoformat(sep=" ")
        narrow = _frame(60, "15min")
        with patch("data.fetcher.get_klines",
                   side_effect=lambda _s, tf, *_a, **_k: narrow if tf == "15m" else None):
            frame = _lifecycle_chart_frame(cand, [], now=_NOW_REF)
        self.assertIs(frame, narrow)
        self.assertEqual(cand.metadata["chart_view_tf"], "15m")
        self.assertEqual(cand.metadata["chart_view_note"], "")
        self.assertEqual(cand.metadata["chart_tf_scale"], 1.0)

    def test_confirmed_chart_renders_on_the_stepped_up_frame(self):
        from bot.messages_v7 import generate_chart
        cand = _candidate(anchor_min_ago=300 * 15, entry_min_ago=120 * 15)
        cand.metadata["target_ladder"] = {"targets": [106.0, 110.0, 113.0],
                                          "weights": [40, 30, 30], "hit_index": 1}
        cand.metadata["current_trailing_sl"] = 100.2
        hourly = _frame(150, "1h")
        with patch("data.fetcher.get_klines",
                   side_effect=lambda _s, tf, *_a, **_k: hourly if tf == "1h" else None):
            from bot.messages_v7 import _lifecycle_chart_frame
            frame = _lifecycle_chart_frame(cand, [], now=_NOW_REF)
            image = generate_chart(frame, cand, confirmed=True)
        self.assertEqual(cand.metadata["chart_view_tf"], "1h")
        self.assertEqual(cand.metadata["chart_tf_scale"], 0.25)
        self.assertTrue(cand.metadata["chart_view_note"])
        self.assertIsNotNone(image)
        self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
