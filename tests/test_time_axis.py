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
                             TOOL_FORWARD_BARS)


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
        "target_ladder": {"targets": [106.0, 110.0, 113.0, 116.0, 119.0],
                          "weights": [40, 30, 30, 0, 0], "hit_index": 0},
    }
    return cand


class ViewPlanTests(unittest.TestCase):
    """His clarified rule: the 40 bars were an example — ANY number of candles
    that left the tool triggers the higher-TF live chart, and while price is
    still inside the long/short tool the trigger TF stays."""

    def _frame_after_entry(self, entry_ts, bars, price=None):
        """Trigger-TF tape: `bars` closed candles after the entry candle."""
        ts = [entry_ts - pd.Timedelta(minutes=15)]
        base = float(price if price is not None else 99.5)
        rows = [{"timestamp": ts[0], "open": base, "high": base + 0.2,
                 "low": base - 0.2, "close": base, "volume": 1000}]
        for i in range(bars):
            _t = entry_ts + pd.Timedelta(minutes=15 * (i + 1))
            _p = float(price if price is not None else 100.0)
            rows.append({"timestamp": _t, "open": _p - 0.1, "high": _p + 0.3,
                         "low": _p - 0.3, "close": _p, "volume": 1000})
        return pd.DataFrame(rows)

    def test_inside_tool_stays_on_trigger_tf(self):
        cand = _candidate(anchor_min_ago=0.0, entry_min_ago=0.0)
        cand.metadata["tool_entry_ts"] = str(_NOW_REF)
        frame = self._frame_after_entry(_NOW_REF, bars=10, price=101.0)
        view, escaped, note = _lifecycle_view_plan(
            cand, now=_NOW_REF + pd.Timedelta(minutes=150), frame=frame)
        self.assertEqual(view, "15m")
        self.assertEqual(escaped, 0)
        self.assertEqual(note, "")

    def test_one_candle_past_the_tool_edge_is_enough(self):
        cand = _candidate(anchor_min_ago=0.0, entry_min_ago=0.0)
        cand.metadata["tool_entry_ts"] = str(_NOW_REF)
        rows = []  # 45 candles after entry: the tool edge is 42 bars out
        for i in range(45):
            _t = _NOW_REF + pd.Timedelta(minutes=15 * (i + 1))
            rows.append({"timestamp": _t, "open": 101.0, "high": 101.3,
                         "low": 100.8, "close": 101.0, "volume": 1000})
        frame = pd.DataFrame(rows)
        view, escaped, note = _lifecycle_view_plan(
            cand, now=_NOW_REF + pd.Timedelta(minutes=15 * 46), frame=frame)
        self.assertEqual(view, "1h")
        self.assertGreaterEqual(escaped, 1)
        self.assertIn("پس از خروج", note)
        self.assertIn("تایم فریم ۱ ساعته", note)
        self.assertIn("جابه‌جا نشده", note)

    def test_exactly_42_candles_is_still_the_trigger_tf(self):
        cand = _candidate(anchor_min_ago=0.0, entry_min_ago=0.0)
        cand.metadata["tool_entry_ts"] = str(_NOW_REF)
        rows = [{"timestamp": _NOW_REF + pd.Timedelta(minutes=15 * (i + 1)),
                 "open": 101.0, "high": 101.3, "low": 100.8, "close": 101.0,
                 "volume": 1000} for i in range(TOOL_FORWARD_BARS)]
        frame = pd.DataFrame(rows)
        view, escaped, _note = _lifecycle_view_plan(
            cand, now=_NOW_REF + pd.Timedelta(minutes=15 * (TOOL_FORWARD_BARS + 1)),
            frame=frame)
        self.assertEqual((view, escaped), ("15m", 0))

    def test_price_out_of_the_band_steps_up_even_early(self):
        """A stop-out candle is OUTSIDE the tool price band → higher TF."""
        cand = _candidate(anchor_min_ago=0.0, entry_min_ago=0.0)
        cand.metadata["tool_entry_ts"] = str(_NOW_REF)
        frame = self._frame_after_entry(_NOW_REF, bars=6, price=101.0)
        frame.loc[frame.index[-1], "close"] = 97.4   # through the 98.0 stop
        view, escaped, note = _lifecycle_view_plan(
            cand, now=_NOW_REF + pd.Timedelta(minutes=15 * 7), frame=frame)
        self.assertEqual(view, "1h")
        self.assertGreaterEqual(escaped, 1)
        self.assertTrue(note)

    def test_above_the_top_pill_steps_up(self):
        cand = _candidate(anchor_min_ago=0.0, entry_min_ago=0.0)
        cand.metadata["tool_entry_ts"] = str(_NOW_REF)
        frame = self._frame_after_entry(_NOW_REF, bars=5, price=120.0)  # > 119
        view, _escaped, _note = _lifecycle_view_plan(
            cand, now=_NOW_REF + pd.Timedelta(minutes=15 * 6), frame=frame)
        self.assertEqual(view, "1h")

    def test_very_old_tool_steps_all_the_way_to_4h(self):
        cand = _candidate(anchor_min_ago=0.0, entry_min_ago=0.0)
        cand.metadata["tool_entry_ts"] = str(_NOW_REF)
        frame = self._frame_after_entry(_NOW_REF, bars=900, price=101.0)
        view, escaped, note = _lifecycle_view_plan(
            cand, now=_NOW_REF + pd.Timedelta(minutes=15 * 901), frame=frame)
        self.assertEqual(view, "4h")
        self.assertGreaterEqual(escaped, 1)
        self.assertIn("۴ ساعته", note)

    def test_1d_tool_has_nowhere_to_step(self):
        cand = _candidate(tf="1d", anchor_min_ago=0.0, entry_min_ago=0.0)
        cand.metadata["tool_entry_ts"] = str(_NOW_REF)
        rows = [{"timestamp": _NOW_REF + pd.Timedelta(days=i + 1),
                 "open": 101.0, "high": 101.3, "low": 100.8, "close": 101.0,
                 "volume": 10} for i in range(60)]
        view, _escaped, note = _lifecycle_view_plan(
            cand, now=_NOW_REF + pd.Timedelta(days=61), frame=pd.DataFrame(rows))
        self.assertEqual(view, "1d")
        self.assertEqual(note, "")

    def test_no_tape_falls_back_to_the_clock(self):
        """No frame available: the clock alone decides (never stalls)."""
        cand = _candidate(anchor_min_ago=0.0, entry_min_ago=0.0)
        cand.metadata["tool_entry_ts"] = str(_NOW_REF)
        view, escaped, _note = _lifecycle_view_plan(
            cand, now=_NOW_REF + pd.Timedelta(minutes=15 * 50), frame=None)
        self.assertEqual(view, "1h")
        self.assertGreaterEqual(escaped, 1)

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
        cand = _candidate(anchor_min_ago=0.0, entry_min_ago=0.0)
        cand.metadata["tool_entry_ts"] = str(_NOW_REF)
        cand.confirmed_at = _NOW_REF.isoformat(sep=" ")
        # 60 bars after the entry → candles left the tool, but the venue has
        # no 1h tape: the render stays on 15m and says nothing extra
        rows = [{"timestamp": _NOW_REF + pd.Timedelta(minutes=15 * (i + 1)),
                 "open": 101.0, "high": 101.3, "low": 100.8, "close": 101.0,
                 "volume": 1000} for i in range(60)]
        narrow = pd.DataFrame(rows)
        with patch("data.fetcher.get_klines",
                   side_effect=lambda _s, tf, *_a, **_k: narrow if tf == "15m" else None):
            frame = _lifecycle_chart_frame(cand, [], now=_NOW_REF + pd.Timedelta(minutes=15 * 61))
        self.assertIs(frame, narrow)
        self.assertEqual(cand.metadata["chart_view_tf"], "15m")
        self.assertEqual(cand.metadata["chart_view_note"], "")
        self.assertEqual(cand.metadata["chart_tf_scale"], 1.0)

    def test_confirmed_chart_renders_on_the_stepped_up_frame(self):
        from bot.messages_v7 import generate_chart, _lifecycle_chart_frame
        cand = _candidate(anchor_min_ago=0.0, entry_min_ago=0.0)
        cand.metadata.update({
            "tool_entry_ts": str(_NOW_REF),
            "tool_anchor_ts": str(_NOW_REF - pd.Timedelta(minutes=55 * 15)),
            "current_trailing_sl": 100.2,
        })
        rows = [{"timestamp": _NOW_REF + pd.Timedelta(minutes=15 * (i + 1)),
                 "open": 101.0, "high": 101.3, "low": 100.8, "close": 101.0,
                 "volume": 1000} for i in range(55)]
        narrow = pd.DataFrame(rows)
        hourly = _frame(150, "1h")
        with patch("data.fetcher.get_klines",
                   side_effect=lambda _s, tf, *_a, **_k: hourly if tf == "1h" else narrow):
            frame = _lifecycle_chart_frame(cand, [], now=_NOW_REF + pd.Timedelta(minutes=15 * 56))
            image = generate_chart(frame, cand, confirmed=True)
        self.assertEqual(cand.metadata["chart_view_tf"], "1h")
        self.assertEqual(cand.metadata["chart_tf_scale"], 0.25)
        self.assertTrue(cand.metadata["chart_view_note"])
        self.assertIsNotNone(image)
        self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
