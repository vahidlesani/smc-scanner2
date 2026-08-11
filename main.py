# smc-scanner v3 - with memory
import time
import schedule
import os
from datetime import datetime

from data.fetcher import get_multi_tf, get_klines
from analysis.structure import find_swing_points, classify_structure, detect_bos_choch
from analysis.smc import find_order_blocks, find_fvg, detect_liquidity
from analysis.rtm import get_rtm_signal
from analysis.ict import get_ict_signal
from bot.telegram_bot import send_signal_with_chart, send_message, send_performance_report
from database.db import (init_db, save_signal, was_signal_sent_recently,
                          get_performance_stats, check_open_signals,
                          update_market_memory, get_market_memory)

ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", "1000"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.5"))

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "AVAXUSDT", "LINKUSDT", "DOTUSDT", "NEARUSDT",
    "APTUSDT", "ARBUSDT", "OPUSDT", "SUIUSDT", "TONUSDT",
    "DOGEUSDT", "MATICUSDT", "LTCUSDT", "ATOMUSDT", "INJUSDT",
]


def calculate_trade_params(entry, sl, direction):
    sl_distance = abs(entry - sl)
    sl_pct = sl_distance / entry
    if sl_pct == 0:
        return None

    risk_amount = ACCOUNT_SIZE * (RISK_PERCENT / 100)
    position_size = risk_amount / sl_distance

    if direction == "LONG":
        tp1 = entry + sl_distance * 2
        tp2 = entry + sl_distance * 3
    else:
        tp1 = entry - sl_distance * 2
        tp2 = entry - sl_distance * 3

    return {
        "sl_pct": sl_pct * 100,
        "risk_amount": risk_amount,
        "position_size": position_size,
        "tp1": tp1,
        "tp2": tp2
    }


def analyze_symbol(symbol):
    signals = []
    tf_data = get_multi_tf(symbol)

    df_1d = tf_data.get("1d")
    df_4h = tf_data.get("4h")
    df_15m = tf_data.get("15m")

    if df_4h is None or df_15m is None:
        return signals, None

    # HTF Bias
    sh_4h, sl_4h = find_swing_points(df_4h, lookback=5)
    structure = classify_structure(sh_4h, sl_4h)
    htf_bias = structure["bias"]

    if not htf_bias or "NEUTRAL" in htf_bias:
        return signals, df_15m

    current_price = df_15m["close"].iloc[-1]

    # وضعیت قبلی از حافظه
    prev_memory = get_market_memory(symbol)

    # SMC
    obs = find_order_blocks(df_4h, htf_bias, lookback=50)
    sh_15m, sl_15m = find_swing_points(df_15m, lookback=3)
    liquidity = detect_liquidity(df_15m, sh_15m, sl_15m)
    bos_15m = detect_bos_choch(df_15m, sh_15m, sl_15m)

    near_ob = False
    ob_top = 0
    ob_bottom = 0
    ob_strength = 0
    has_sweep = False
    has_choch = False

    for ob in obs[:2]:
        price_near_ob = abs(current_price - ob.top) / current_price < 0.015
        if not price_near_ob:
            continue

        near_ob = True
        ob_top = ob.top
        ob_bottom = ob.bottom
        ob_strength = ob.strength

        has_sweep = (
            (htf_bias == "BULLISH" and
             liquidity["sweep_type"] == "SWEEP_LOW") or
            (htf_bias == "BEARISH" and
             liquidity["sweep_type"] == "SWEEP_HIGH")
        )
        has_choch = bool(bos_15m and bos_15m.direction == htf_bias)

        # مقایسه با حافظه - فقط تغییرات جدید
        prev_had_sweep = prev_memory.get("has_sweep", False)
        prev_had_choch = prev_memory.get("has_choch", False)
        prev_near_ob = prev_memory.get("near_ob", False)

        new_sweep = has_sweep and not prev_had_sweep
        new_choch = has_choch and not prev_had_choch
        just_entered_ob = near_ob and not prev_near_ob

        confirmations = []
        confirmations.append("✅ Sweep" if has_sweep else "⚠️ No Sweep")
        confirmations.append("✅ CHoCH" if has_choch else "⚠️ No CHoCH")

        if new_sweep:
            confirmations.append("🆕 Sweep جدید!")
        if new_choch:
            confirmations.append("🆕 CHoCH جدید!")
        if just_entered_ob:
            confirmations.append("🆕 ورود به OB!")

        # سیگنال فقط وقتی تغییر جدیدی هست
        should_signal = new_sweep or new_choch or just_entered_ob

        direction = "LONG" if htf_bias == "BULLISH" else "SHORT"
        sl = ob_bottom * 0.998 if direction == "LONG" else ob_top * 1.002
        trade = calculate_trade_params(current_price, sl, direction)

        if trade and should_signal:
            signals.append({
                "source": "SMC", "symbol": symbol,
                "direction": direction, "entry": current_price,
                "sl": sl, "tp1": trade["tp1"], "tp2": trade["tp2"],
                "ob_zone": f"{ob_bottom:.4f}-{ob_top:.4f}",
                "ob_strength": f"{ob_strength:.1f}x",
                "confirmations": confirmations,
                "bias": htf_bias, "trade_params": trade
            })

    # RTM
    rtm = get_rtm_signal(df_4h, htf_bias)
    rtm_pattern = ""
    rtm_fresh = False

    if rtm:
        rtm_pattern = rtm["pattern"]
        rtm_fresh = True
        prev_rtm = prev_memory.get("rtm_pattern", "")

        sl = (rtm["base_bottom"] * 0.997 if rtm["direction"] == "LONG"
              else rtm["base_top"] * 1.003)
        trade = calculate_trade_params(current_price, sl, rtm["direction"])

        # فقط اگه pattern جدیده سیگنال بده
        if trade and rtm_pattern != prev_rtm:
            signals.append({
                "source": "RTM", "symbol": symbol,
                "direction": rtm["direction"], "entry": current_price,
                "sl": sl, "tp1": trade["tp1"], "tp2": trade["tp2"],
                "pattern": rtm["pattern"],
                "base_zone": f"{rtm['base_bottom']:.4f}-{rtm['base_top']:.4f}",
                "strength": rtm["strength"],
                "confirmations": [
                    f"Pattern: {rtm['pattern']}",
                    f"Strength: {rtm['strength']}",
                    "🆕 Pattern جدید!"
                ],
                "bias": htf_bias, "trade_params": trade
            })

    # ICT
    ict = get_ict_signal(df_4h, df_15m, df_1d, htf_bias)
    ict_in_ote = False
    ict_in_kz = False

    if ict:
        ict_in_ote = True
        prev_in_ote = prev_memory.get("ict_in_ote", False)

        entry = (ict["entry_top"] + ict["entry_bottom"]) / 2
        sl = (ict["entry_bottom"] * 0.997 if ict["direction"] == "LONG"
              else ict["entry_top"] * 1.003)
        trade = calculate_trade_params(entry, sl, ict["direction"])
        kz = ict.get("killzone", "None")
        ict_in_kz = kz != "None"
        mss = ict.get("mss_confirmed", False)

        # فقط اگه تازه وارد OTE شده سیگنال بده
        if trade and not prev_in_ote:
            signals.append({
                "source": "ICT", "symbol": symbol,
                "direction": ict["direction"], "entry": entry,
                "sl": sl, "tp1": trade["tp1"], "tp2": trade["tp2"],
                "ote_zone": f"{ict['entry_bottom']:.4f}-{ict['entry_top']:.4f}",
                "killzone": kz, "in_killzone": ict_in_kz,
                "mss": mss, "pdh": ict.get("pdh"), "pdl": ict.get("pdl"),
                "confirmations": [
                    f"{'✅' if ict_in_kz else '⚠️'} KZ: {kz}",
                    f"{'✅' if mss else '⚠️'} MSS",
                    "🆕 ورود به OTE!"
                ],
                "bias": htf_bias, "trade_params": trade
            })

    # ذخیره وضعیت فعلی در حافظه
    update_market_memory(symbol, {
        "bias": htf_bias,
        "near_ob": near_ob,
        "ob_top": ob_top,
        "ob_bottom": ob_bottom,
        "ob_strength": ob_strength,
        "has_sweep": has_sweep,
        "has_choch": has_choch,
        "rtm_pattern": rtm_pattern,
        "rtm_fresh": rtm_fresh,
        "ict_in_ote": ict_in_ote,
        "ict_in_killzone": ict_in_kz,
        "current_price": current_price
    })

    return signals, df_15m


def run_scan():
    print(f"[{datetime.utcnow().strftime('%H:%M')}] Scanning {len(SYMBOLS)} symbols...")

    closed = check_open_signals()
    for c in closed:
        emoji = "✅ WIN" if c["result"] == "WIN" else "❌ LOSS"
        send_message(f"{emoji}\n{c['symbol']} | PnL: {c['pnl']:.2f}%")

    for symbol in SYMBOLS:
        try:
            signals, df_15m = analyze_symbol(symbol)

            for sig in signals:
                if was_signal_sent_recently(
                    symbol, sig["source"], sig["direction"], hours=4
                ):
                    continue

                save_signal(sig)
                send_signal_with_chart(sig, df_15m)
                time.sleep(2)

        except Exception as e:
            print(f"Error {symbol}: {e}")

    print(f"[{datetime.utcnow().strftime('%H:%M')}] Scan done.")


def run_daily_report():
    stats = get_performance_stats()
    send_performance_report(stats)


def main():
    init_db()
    send_message(
        "🚀 <b>Scanner v3 Started</b>\n"
        "📊 SMC | 🔷 RTM | 💎 ICT\n"
        "🧠 Smart Memory Active\n"
        f"📌 {len(SYMBOLS)} Symbols\n"
        "⏱ Scan: 15min"
    )

    schedule.every(15).minutes.do(run_scan)
    schedule.every().day.at("08:00").do(run_daily_report)

    run_scan()

    while True:
        schedule.run_pending()
        time.sleep(60)


if __name__ == "__main__":
    main()
