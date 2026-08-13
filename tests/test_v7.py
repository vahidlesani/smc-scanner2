import os
import tempfile
import unittest
from datetime import timedelta

import pandas as pd

from analysis.models import EvidenceItem, SignalCandidate, generate_viva_signal_id, iso_now, utc_now
from analysis.quality_engine import evaluate_confirmation
from analysis.risk import build_money_management
from bot.messages_v7 import build_confirmed_message, build_educational_message


def make_candidate(status="EDUCATIONAL", score=7):
    return SignalCandidate(
        signal_id=generate_viva_signal_id("BTCUSDT", "SWING", "LSR"),
        symbol="BTCUSDT",
        style="SWING",
        setup_code="LSR",
        setup_name="Liquidity Sweep Retest",
        strategy_fa="جمع‌آوری نقدینگی و بازگشت",
        direction="LONG",
        score=score,
        status=status,
        entry_zone_bottom=99.0,
        entry_zone_top=100.0,
        planned_entry=99.5,
        sl=98.0,
        tp1=106.0,
        tp2=109.0,
        rr_tp1=4.3,
        rr_tp2=6.3,
        bias="BULLISH",
        trigger_timeframe="15m",
        evidence=[
            EvidenceItem(
                "liquidity",
                "جمع‌آوری نقدینگی",
                "قیمت کف قبلی را Sweep کرده، بالای سطح برگشته و برای تأیید نهایی منتظر بسته‌شدن کندل هستیم.",
                True,
                2,
            )
        ],
        confirmations=["سشن نیویورک"],
        warnings=["این تحلیل تا قبل از تأیید دستور ورود نیست."],
        mandatory_gates={"htf": True, "sweep": True, "poi": True, "rr": True},
        market={"turnover24h": 1_000_000_000, "spread_pct": 0.02},
        metadata={"atr": 1.0, "touched": False, "session": "NEW_YORK"},
        created_at=(utc_now() - timedelta(hours=1)).isoformat(timespec="seconds"),
        expires_at=(utc_now() + timedelta(hours=4)).isoformat(timespec="seconds"),
    )


class V7ModelTests(unittest.TestCase):
    def test_viva_signal_id_contains_style_and_prefix(self):
        value = generate_viva_signal_id("ETHUSDT", "SCALP", "TLR")
        self.assertTrue(value.startswith("viva-ETH-SC-TLR-"))

    def test_educational_label_is_unambiguous(self):
        text = build_educational_message(make_candidate())
        self.assertIn("این پیام تأیید ورود نیست", text)
        self.assertIn("فقط برای رصد بازار و اهداف آموزشی", text)
        self.assertIn("جمع‌آوری نقدینگی", text)
        self.assertNotIn("ENTRY CONFIRMED", text)

    def test_confirmed_message_has_numbered_reason_and_risk(self):
        candidate = make_candidate("CONFIRMED", 8)
        candidate.confirmed_at = iso_now()
        text = build_confirmed_message(candidate)
        self.assertIn("ENTRY CONFIRMED", text)
        self.assertIn("1. جمع‌آوری نقدینگی", text)
        self.assertIn("مدیریت سرمایه بهینه", text)
        self.assertIn("viva-", text)

    def test_money_management_caps_margin(self):
        candidate = make_candidate("CONFIRMED", 8)
        plan = build_money_management(candidate, account=1000)
        self.assertLessEqual(plan["margin_pct"], 25.0001)
        self.assertGreater(plan["leverage"], 0)
        self.assertLessEqual(plan["risk_pct"], 1.01)

    def test_confirmation_uses_closed_trigger_after_touch(self):
        times = pd.date_range(end=pd.Timestamp.utcnow().tz_localize(None), periods=30, freq="15min")
        rows = []
        for i, timestamp in enumerate(times):
            rows.append({
                "timestamp": timestamp,
                "open": 100.0,
                "high": 100.4,
                "low": 99.2 if i >= 25 else 99.7,
                "close": 100.0,
                "volume": 1000.0,
                "turnover": 100000.0,
            })
        rows[-2].update({"open": 99.9, "high": 100.3, "low": 99.4, "close": 100.0, "volume": 1000})
        rows[-1].update({"open": 99.8, "high": 101.5, "low": 99.5, "close": 101.2, "volume": 2500})
        frame = pd.DataFrame(rows)
        candidate = make_candidate(score=7)
        confirmed, candidate, _ = evaluate_confirmation(candidate, frame)
        self.assertTrue(confirmed)
        self.assertEqual(candidate.status, "CONFIRMED")
        self.assertGreaterEqual(candidate.score, 8)


class V7PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        from database import db
        from database import candidate_store
        db.USE_POSTGRES = False
        db.DB_PATH = os.path.join(self.tempdir.name, "signals.db")
        candidate_store.DB_PATH = os.path.join(self.tempdir.name, "candidates.db")
        candidate_store.init_candidate_store()
        from database.repository_v7 import init_v7_schema
        init_v7_schema()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_unconfirmed_cannot_enter_signal_history(self):
        from database.repository_v7 import save_confirmed_signal
        with self.assertRaises(ValueError):
            save_confirmed_signal(make_candidate("EDUCATIONAL", 7))

    def test_confirmed_enters_signal_and_active_history(self):
        from database.repository_v7 import save_confirmed_signal
        from database.db import get_active_signals, get_recent_signals
        candidate = make_candidate("CONFIRMED", 8)
        candidate.confirmed_at = iso_now()
        self.assertTrue(save_confirmed_signal(candidate))
        self.assertEqual(len(get_recent_signals()), 1)
        self.assertEqual(len(get_active_signals()), 1)
        self.assertTrue(get_recent_signals()[0]["signal_id"].startswith("viva-"))

    def test_trade_monitor_processes_tp1_then_breakeven_chronologically(self):
        from database import repository_v7
        from database.repository_v7 import save_confirmed_signal
        from database.db import get_recent_signals

        candidate = make_candidate("CONFIRMED", 8)
        confirmed_time = utc_now().replace(microsecond=0)
        candidate.confirmed_at = confirmed_time.isoformat(timespec="seconds")
        self.assertTrue(save_confirmed_signal(candidate))

        frame = pd.DataFrame([
            {
                "timestamp": confirmed_time.replace(tzinfo=None) + timedelta(minutes=15),
                "open": 100.0, "high": 106.5, "low": 99.6, "close": 105.0,
                "volume": 1000, "turnover": 100000,
            },
            {
                "timestamp": confirmed_time.replace(tzinfo=None) + timedelta(minutes=30),
                "open": 105.0, "high": 105.2, "low": 99.4, "close": 100.0,
                "volume": 1000, "turnover": 100000,
            },
        ])
        original = repository_v7.get_klines
        repository_v7.get_klines = lambda *args, **kwargs: frame
        try:
            events = repository_v7.monitor_confirmed_trades()
        finally:
            repository_v7.get_klines = original
        self.assertEqual([event["event"] for event in events], ["TP1", "CLOSED"])
        self.assertEqual(events[-1]["result"], "WIN")
        self.assertGreater(get_recent_signals()[0]["pnl_pct"], 0)


if __name__ == "__main__":
    unittest.main()
