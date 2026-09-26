"""r35 (Viva 09-26): SPOT inherits every chart law + the lane is un-strangled +
CryptoCave-clean spot charts + on-chain reference block on spot cards."""
import os

REPO = "/home/user/smc-scanner2"


# ── 1. the shared code path: spot charts ARE generate_chart ───────────────
def test_spot_publishers_use_the_shared_renderer():
    src = open(f"{REPO}/main.py", encoding="utf-8").read()
    # both the confirmed publisher and the ladder render via generate_chart
    assert src.count("generate_chart(frame, cand") >= 2
    # ⇒ Tehran clocks, 50-bar line law, render identity, numeric pills,
    #   ledger, smart-zoom recent floor all apply to spot automatically.


def test_spot_chart_gets_the_cryptocave_clean_pass():
    src = open(f"{REPO}/bot/messages_v7.py", encoding="utf-8").read()
    assert '_spot_clean35 = str((candidate.metadata or {}).get("market") or "").upper() == "SPOT"' in src
    assert "if not _clean_zone_view and not _spot_clean35:" in src
    assert "if _spot_clean35:\n            _rz = []" in src


# ── 2. the lane is no longer strangled by the daily budget ────────────────
def test_spot_budgets_raised():
    src = open(f"{REPO}/main.py", encoding="utf-8").read()
    assert 'os.getenv("SPOT_MAX_PER_DAY", "16")' in src
    assert 'os.getenv("SPOT_ALERT_MAX_PER_DAY", "30")' in src
    # the dedup stamp remains the real anti-spam layer
    assert "_spot_stamp(key, window, commit=False)" in src


def test_spot_engine_only_publishes_bullish_breaks_and_warns_both_sides():
    src = open(f"{REPO}/analysis/spot_engine.py", encoding="utf-8").read()
    # signals: only a valid close ABOVE the upper side (LONG)
    assert "bullish_pattern_ok(pat, close, upper)" in src
    assert "close <= upper + eps" in src
    assert "BREAK_DOWN" in src
    # ladder: both sides warn (the alert post names UPPER and LOWER edges)
    msrc = open(f"{REPO}/bot/messages_v7.py", encoding="utf-8").read()
    # r42: the merged one-line analysis names BOTH edges inline
    assert "'بالا' if side == 'HIGH' else 'پایین'" in msrc


# ── 3. the on-chain witness block on confirmed spot cards ─────────────────
def test_spot_confirmed_card_carries_onchain_reference_block():
    src = open(f"{REPO}/bot/messages_v7.py", encoding="utf-8").read()
    assert "from analysis.onchain_free import market_snapshot, symbol_stats" in src
    assert "رفرنس آنچین" in src
    assert "هرگز شرطِ سیگنال نیست" in src
    # inserted into the confirmed-card return, after result_line
    seg = src[src.index("_onchain35 = \"\""):]
    seg = seg[:seg.index("📌 <b>VIVAMON-Labs-Pro</b>")]
    assert "result_line + _onchain35" in seg


# ── 4. on-chain engine present, enabled by default, fail-open ─────────────
def test_onchain_engine_exists_and_enabled():
    from analysis import onchain_free
    assert onchain_free.ENABLED is True
    assert onchain_free.COINGECKO.startswith("https://api.coingecko.com")
    # functions exist and never raise without network
    assert callable(onchain_free.market_snapshot)
    assert callable(onchain_free.symbol_stats)
    assert callable(onchain_free.context_line_fa)
