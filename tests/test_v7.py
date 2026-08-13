import os
import tempfile
import unittest
from datetime import timedelta
from unittest.mock import patch

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

    def test_branded_confirmed_chart_is_exact_1440_by_900_png(self):
        from bot.messages_v7 import generate_chart

        candidate = make_candidate("CONFIRMED", 8)
        candidate.confirmed_at = iso_now()
        timestamps = pd.date_range("2026-01-01", periods=100, freq="15min")
        closes = [99.0 + index * 0.01 for index in range(100)]
        frame = pd.DataFrame({
            "timestamp": timestamps,
            "open": [value - 0.08 for value in closes],
            "high": [value + 0.22 for value in closes],
            "low": [value - 0.20 for value in closes],
            "close": closes,
            "volume": [1000 + index * 3 for index in range(100)],
            "turnover": [100000 + index * 100 for index in range(100)],
        })
        image = generate_chart(frame, candidate, confirmed=True)
        self.assertIsNotNone(image)
        self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(int.from_bytes(image[16:20], "big"), 1440)
        self.assertEqual(int.from_bytes(image[20:24], "big"), 900)

    def test_money_management_caps_margin(self):
        candidate = make_candidate("CONFIRMED", 8)
        plan = build_money_management(candidate, account=1000)
        self.assertLessEqual(plan["margin_pct"], 5.0001)
        self.assertLessEqual(plan["margin_limit_pct"], 5.0)
        self.assertGreater(plan["leverage"], 0)
        self.assertLessEqual(plan["leverage"], 20)
        self.assertLessEqual(plan["risk_pct"], 1.01)

    def test_quality_controls_three_to_five_percent_margin_and_leverage(self):
        from analysis.risk import quality_plan, suggested_leverage

        self.assertEqual(quality_plan(7)["margin_pct"], 3.0)
        self.assertEqual(quality_plan(10)["margin_pct"], 5.0)
        self.assertEqual(suggested_leverage(7, 0.01), 5)
        self.assertEqual(suggested_leverage(10, 0.01), 20)
        self.assertLess(suggested_leverage(10, 0.08), 20)

    def test_liquidity_invalidation_is_beyond_poi_and_dynamic_buffer(self):
        from analysis.setups_v7 import _liquidity_protected_invalidation

        frame = pd.DataFrame({
            "timestamp": pd.date_range("2026-01-01", periods=9, freq="15min"),
            "high": [102, 103, 102, 104, 102, 103, 102, 104, 103],
            "low": [99, 98, 99, 97.5, 99, 98.2, 99, 97.8, 99],
        })
        result = _liquidity_protected_invalidation(
            frame, {"bottom": 99.0, "top": 100.0}, "LONG", 1.0, "SWING", 0.05
        )
        self.assertLess(result["price"], result["liquidity_anchor"])
        self.assertLessEqual(result["liquidity_anchor"], 99.0)
        self.assertGreaterEqual(result["buffer"], 0.35)

    def test_bybit_tradfi_asset_classification(self):
        from data.universe import _asset_class

        self.assertEqual(_asset_class({"symbol": "EURUSD", "baseCoin": "EUR", "quoteCoin": "USD"}), "FOREX")
        self.assertEqual(_asset_class({"symbol": "XAUUSDT", "baseCoin": "XAU", "quoteCoin": "USDT"}), "METAL")
        self.assertEqual(_asset_class({"symbol": "AAPLUSDT", "symbolType": "TradFi Stock"}), "EQUITY")

    def test_dynamic_universe_reserves_top_three_liquid_forex_pairs(self):
        from data import universe

        forex = [
            ("EURUSD", "EUR", "USD", 20_000_000),
            ("GBPUSD", "GBP", "USD", 18_000_000),
            ("USDJPY", "USD", "JPY", 16_000_000),
            ("USDCAD", "USD", "CAD", 14_000_000),
        ]
        instruments = [
            {
                "symbol": symbol,
                "baseCoin": base,
                "quoteCoin": quote,
                "settleCoin": "USDT",
                "status": "Trading",
                "contractType": "LinearPerpetual",
                "launchTime": "0",
                "leverageFilter": {"maxLeverage": "20"},
            }
            for symbol, base, quote, _turnover in forex
        ]
        tickers = [
            {
                "symbol": symbol,
                "bid1Price": "1.0000",
                "ask1Price": "1.0005",
                "lastPrice": "1.0002",
                "turnover24h": str(turnover),
                "volume24h": str(turnover),
            }
            for symbol, _base, _quote, turnover in forex
        ]
        now = pd.Timestamp.now(tz="UTC").tz_localize(None)
        timestamps = list(pd.date_range(end=now.normalize() - pd.Timedelta(days=1), periods=7, freq="D")) + [now.normalize()]

        def daily_for(symbol, *_args, **_kwargs):
            current = next(item[3] for item in forex if item[0] == symbol)
            return pd.DataFrame({
                "timestamp": timestamps,
                "turnover": [10_000_000] * 7 + [current],
            })

        with (
            patch.object(universe, "get_instruments", return_value=instruments),
            patch.object(universe, "get_tickers", return_value=tickers),
            patch.object(universe, "get_klines", side_effect=daily_for),
        ):
            symbols, metrics = universe.DynamicUniverse()._build()

        selected_forex = [symbol for symbol in symbols if metrics[symbol]["asset_class"] == "FOREX"]
        self.assertEqual(selected_forex, ["EURUSD", "GBPUSD", "USDJPY"])
        self.assertNotIn("USDCAD", selected_forex)

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

        first_score = candidate.score
        first_confirmed_at = candidate.confirmed_at
        candidate.status = "APPROACHING"
        confirmed, candidate, _ = evaluate_confirmation(candidate, frame)
        self.assertTrue(confirmed)
        self.assertEqual(candidate.score, first_score)
        self.assertEqual(candidate.confirmed_at, first_confirmed_at)


class V7PublicationFlowTests(unittest.TestCase):
    def test_failed_telegram_confirmation_never_arms_result_monitoring(self):
        import main as scanner_main

        candidate = make_candidate("APPROACHING", 8)
        candidate.confirmed_at = iso_now()
        candidate.metadata["technical_confirmation_complete"] = True
        frame = pd.DataFrame({"close": [100.0]})
        with (
            patch.object(scanner_main, "get_active_candidates", return_value=[candidate]),
            patch.object(
                scanner_main,
                "_candidate_market_frames",
                return_value={(candidate.symbol, candidate.trigger_timeframe): (frame, frame, 100.0)},
            ),
            patch.object(scanner_main, "save_confirmed_signal", return_value=True),
            patch.object(scanner_main, "is_confirmation_published", return_value=False),
            patch.object(scanner_main, "send_confirmed", return_value=False),
            patch.object(scanner_main, "mark_confirmation_published") as mark_mock,
            patch.object(scanner_main, "update_candidate"),
            patch.object(scanner_main, "update_symbol_lock"),
        ):
            stats = scanner_main.monitor_candidates()

        mark_mock.assert_not_called()
        self.assertEqual(stats["confirmed"], 0)
        self.assertEqual(candidate.status, "APPROACHING")
        self.assertTrue(candidate.metadata["publication_pending"])


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

    def test_symbol_is_deduplicated_until_candidate_is_cancelled(self):
        from database.candidate_store import add_candidate, set_status

        first = make_candidate("EDUCATIONAL", 7)
        second = make_candidate("EDUCATIONAL", 8)
        second.style = "SCALP"
        second.setup_code = "TLR"
        second.direction = "SHORT"
        self.assertTrue(add_candidate(first))
        self.assertFalse(add_candidate(second))
        set_status(first.signal_id, "CANCELLED")
        self.assertTrue(add_candidate(second))

    def test_durable_symbol_lock_survives_local_candidate_state(self):
        from database.repository_v7 import acquire_symbol_lock, release_symbol_lock

        first = make_candidate("EDUCATIONAL", 7)
        second = make_candidate("EDUCATIONAL", 8)
        self.assertTrue(acquire_symbol_lock(first))
        self.assertFalse(acquire_symbol_lock(second))
        release_symbol_lock(first.symbol, first.signal_id)
        self.assertTrue(acquire_symbol_lock(second))

    def test_staged_confirmation_is_hidden_until_publication_is_committed(self):
        from database.repository_v7 import mark_confirmation_published, save_confirmed_signal
        from database.db import get_active_signals, get_recent_signals
        candidate = make_candidate("CONFIRMED", 8)
        candidate.confirmed_at = iso_now()
        self.assertTrue(save_confirmed_signal(candidate))

        # Technical confirmation alone is not execution history.
        self.assertEqual(get_recent_signals(), [])
        self.assertEqual(get_active_signals(), [])

        mark_confirmation_published(candidate.signal_id)
        self.assertEqual(len(get_recent_signals()), 1)
        self.assertEqual(len(get_active_signals()), 1)
        self.assertTrue(get_recent_signals()[0]["signal_id"].startswith("viva-"))

    def test_staged_symbol_lock_is_released_by_cancellation(self):
        from database.repository_v7 import (
            cancel_staged_confirmation,
            has_unresolved_symbol,
            save_confirmed_signal,
        )

        candidate = make_candidate("CONFIRMED", 8)
        candidate.confirmed_at = iso_now()
        save_confirmed_signal(candidate)
        self.assertTrue(has_unresolved_symbol(candidate.symbol))
        cancel_staged_confirmation(candidate.signal_id)
        self.assertFalse(has_unresolved_symbol(candidate.symbol))

    def test_trade_monitor_processes_tp1_then_breakeven_chronologically(self):
        from database import repository_v7
        from database.repository_v7 import mark_confirmation_published, save_confirmed_signal
        from database.db import get_recent_signals

        candidate = make_candidate("CONFIRMED", 8)
        confirmed_time = utc_now().replace(microsecond=0)
        candidate.confirmed_at = confirmed_time.isoformat(timespec="seconds")
        self.assertTrue(save_confirmed_signal(candidate))
        mark_confirmation_published(candidate.signal_id)

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

    def test_unpublished_and_legacy_rows_are_quarantined_everywhere(self):
        from config import get_settings
        from database import db, repository_v7
        from database.db import get_dashboard_summary, get_recent_signals, get_strategy_performance
        from database.repository_v7 import save_confirmed_signal

        unpublished = make_candidate("CONFIRMED", 8)
        unpublished.confirmed_at = iso_now()
        legacy = make_candidate("CONFIRMED", 8)
        legacy.confirmed_at = iso_now()
        self.assertTrue(save_confirmed_signal(unpublished))
        self.assertTrue(save_confirmed_signal(legacy))

        p = db._ph()
        truth = "TRUE" if db.USE_POSTGRES else "1"
        with db.db_cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE signals
                SET strategy_version={p}, status='CONFIRMED',
                    confirmation_sent={truth}, confirmation_sent_at={p},
                    result='WIN', pnl_pct=3.0, closed_at={p}
                WHERE signal_id={p}
                """,
                ("smc-core-6.0", iso_now(), iso_now(), legacy.signal_id),
            )

        with patch.object(repository_v7, "get_klines") as get_klines_mock:
            self.assertEqual(repository_v7.monitor_confirmed_trades(), [])
            get_klines_mock.assert_not_called()
        self.assertEqual(get_recent_signals(), [])
        self.assertEqual(get_strategy_performance(), [])
        self.assertEqual(get_dashboard_summary()["total_signals"], 0)
        self.assertEqual(get_settings().strategy_version, repository_v7.SETTINGS.strategy_version)

    def test_result_sender_fails_closed_without_matching_publication_proof(self):
        from config import get_settings
        from bot import messages_v7
        from database import db
        from database.repository_v7 import mark_confirmation_published, save_confirmed_signal

        candidate = make_candidate("CONFIRMED", 8)
        candidate.confirmed_at = iso_now()
        save_confirmed_signal(candidate)
        mark_confirmation_published(candidate.signal_id)
        with db.db_cursor() as cursor:
            cursor.execute(
                f"UPDATE signals SET result='WIN', pnl_pct=2.0, closed_at={db._ph()} "
                f"WHERE signal_id={db._ph()}",
                (iso_now(), candidate.signal_id),
            )

        valid_event = {
            "event": "CLOSED",
            "signal_id": candidate.signal_id,
            "symbol": candidate.symbol,
            "style": candidate.style,
            "result": "WIN",
            "pnl": 2.0,
            "profit_usd": 20.0,
            "strategy_version": get_settings().strategy_version,
            "confirmed_at": candidate.confirmed_at,
            "confirmation_sent": True,
        }
        with patch.object(messages_v7, "send_message", return_value=True) as send_mock:
            self.assertTrue(messages_v7.send_trade_result(valid_event))
            self.assertFalse(messages_v7.send_trade_result({**valid_event, "strategy_version": "v6"}))
            self.assertFalse(messages_v7.send_trade_result({**valid_event, "result": "LOSS"}))
            # One branded divider plus one validated result message.
            self.assertEqual(send_mock.call_count, 2)

    def test_confirmed_publication_resumes_without_duplicate_chart(self):
        from bot import messages_v7

        candidate = make_candidate("CONFIRMED", 8)
        candidate.confirmed_at = iso_now()
        with (
            patch.object(messages_v7, "generate_chart", return_value=b"chart") as chart_mock,
            patch.object(messages_v7, "send_photo", return_value=True) as photo_mock,
            patch.object(messages_v7, "send_message", side_effect=[True, False, True]) as message_mock,
        ):
            self.assertFalse(messages_v7.send_confirmed(candidate, pd.DataFrame({"x": [1]})))
            self.assertTrue(candidate.metadata["confirmation_chart_sent"])
            self.assertTrue(messages_v7.send_confirmed(candidate, pd.DataFrame({"x": [1]})))
            self.assertEqual(chart_mock.call_count, 1)
            self.assertEqual(photo_mock.call_count, 1)
            self.assertEqual(message_mock.call_count, 3)
            self.assertTrue(candidate.metadata["confirmation_separator_attempted"])
            self.assertTrue(candidate.metadata["confirmation_message_sent"])


if __name__ == "__main__":
    unittest.main()
