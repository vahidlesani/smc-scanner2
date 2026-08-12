# smc-scanner v4 - codes + risk + dual channel
import time
import schedule
import os
import pandas as pd
from datetime import datetime

from data.fetcher import get_multi_tf, get_klines
from analysis.structure import find_swing_points, classify_structure, detect_bos_choch
from analysis.smc import find_order_blocks, detect_liquidity
from analysis.rtm import get_rtm_signal
from analysis.ict import get_ict_signal
from bot.telegram_bot import (
    send_signal_with_chart, send_message,
    send_performance_report, attach_money_management,
)
from database.db import (
    init_db, save_signal, save_active_signal,
    was_signal_sent_recently, get_performance_stats,
    check_open_signals, update_market_memory,
    get_market_memory, get_active_signals,
    cancel_active_signal, confirm_active_signal
)

ACCOUNT_SIZE = float(os.environ.get("ACCOUNT_SIZE", "1000"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.5"))
CHAT_ID_SIGNALS = os.environ.get("CHAT_ID_SIGNALS", "")
CHAT_ID_ADMIN = os.environ.get("CHAT_ID", "")

SYMBOLS = sorted(set([
    # بزرگ‌ها
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    "PAXGUSDT", "XAGUSDT", "LINKUSDT", "LDOUSDT", "ICPUSDT",
    "BCHUSDT", "DOGEUSDT",
    # لایه ۱
    "ADAUSDT", "AVAXUSDT", "DOTUSDT", "ATOMUSDT", "NEARUSDT",
    # لایه ۲
    "LTCUSDT", "POLUSDT", "INJUSDT", "APTUSDT",
    # دیفای و جدید
    "ARBUSDT", "OPUSDT", "SUIUSDT",
    # اضافه
    "SEIUSDT", "TIAUSDT", "JUPUSDT", "WLDUSDT", "STXUSDT",
    "FETUSDT", "RENDERUSDT", "AAVEUSDT", "MKRUSDT",
]))


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
        in_zone = ob.bottom <= current_price <= ob.top
        near_zone = (
            abs(current_price - ob.top) / current_price < 0.015
            or abs(current_price - ob.bottom) / current_price < 0.015
        )
        if not (in_zone or near_zone):
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
        # CHoCH واقعی: شکست خلاف ساختار فعلی LTF، هم‌جهت با HTF
        has_choch = bool(
            bos_15m
            and bos_15m.direction == htf_bias
            and bos_15m.type == "CHoCH"
        )

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
        kz = ict.get("killzone")
        ict_in_kz = bool(kz)
        mss = ict.get("mss_confirmed", False)

        if trade and not prev_in_ote:
            signals.append({
                "source": "ICT", "symbol": symbol,
                "direction": ict["direction"], "entry": entry,
                "sl": sl, "tp1": trade["tp1"], "tp2": trade["tp2"],
                "ote_zone": f"{ict['entry_bottom']:.4f}-{ict['entry_top']:.4f}",
                "killzone": kz, "in_killzone": ict_in_kz,
                "mss": mss, "pdh": ict.get("pdh"), "pdl": ict.get("pdl"),
                "confirmations": [
                    f"{'✅' if ict_in_kz else '⚠️'} KZ: {kz or 'None'}",
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


def check_signal_confirmation(sig_data: dict, df_15m: pd.DataFrame) -> bool:
    """
    چک میکنه آیا پوزیشن تایید ورود گرفته
    یعنی قیمت از Entry رد شده
    """
    if df_15m is None:
        return False

    current_close = df_15m["close"].iloc[-1]
    entry = sig_data["entry"]
    direction = sig_data["direction"]

    if direction == "LONG" and current_close > entry * 1.001:
        return True
    if direction == "SHORT" and current_close < entry * 0.999:
        return True
    return False


def check_signal_cancellation(sig_data: dict, df_15m: pd.DataFrame) -> bool:
    """
    چک میکنه آیا سیگنال باطل شده
    یعنی قیمت برگشته و ساختار خراب شده
    """
    if df_15m is None:
        return False

    current_close = df_15m["close"].iloc[-1]
    entry = sig_data["entry"]
    sl = sig_data["sl"]
    direction = sig_data["direction"]

    sl_distance = abs(entry - sl)

    if direction == "LONG":
        cancel_level = entry - (sl_distance * 0.5)
        return current_close < cancel_level
    else:
        cancel_level = entry + (sl_distance * 0.5)
        return current_close > cancel_level


def monitor_active_signals():
    """
    هر اسکن این رو صدا میزنیم:
    ۱. سیگنال‌های تایید نشده رو چک میکنه
    ۲. اگه تایید شد → اعلام میکنه
    ۳. اگه برگشت → باطل اعلام میکنه
    """
    active = get_active_signals()

    for sig_data in active:
        try:
            symbol = sig_data["symbol"]
            signal_id = sig_data["signal_id"]

            df_15m = get_klines(symbol, "15m", 10, closed_only=False)
            if df_15m is None:
                continue

            target_chat = CHAT_ID_SIGNALS if CHAT_ID_SIGNALS else CHAT_ID_ADMIN

            if check_signal_confirmation(sig_data, df_15m):
                confirm_active_signal(signal_id)
                send_message(
                    f"✅ <b>Signal Confirmed!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🆔 <code>{signal_id}</code>\n"
                    f"🪙 <b>{symbol}</b> | {sig_data['direction']}\n"
                    f"📍 Entry confirmed at "
                    f"<b>{df_15m['close'].iloc[-1]:.4f}</b>\n"
                    f"✅ پوزیشن تایید شد - میتوانید وارد شوید!",
                    chat_id=target_chat
                )

            elif check_signal_cancellation(sig_data, df_15m):
                cancel_active_signal(signal_id)
                send_message(
                    f"❌ <b>Signal Cancelled!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"🆔 <code>{signal_id}</code>\n"
                    f"🪙 <b>{symbol}</b> | {sig_data['direction']}\n"
                    f"⚠️ قیمت در جهت مخالف حرکت کرد.\n"
                    f"❌ این سیگنال باطل شد - وارد نشوید!",
                    chat_id=target_chat
                )

        except Exception as e:
            print(f"Monitor error {sig_data.get('signal_id')}: {e}")


def run_scan():
    try:
        print(f"[{datetime.utcnow().strftime('%H:%M')}] "
              f"Scanning {len(SYMBOLS)} symbols...")

        # چک سیگنال‌های باز (WIN/LOSS)
        try:
            closed = check_open_signals()
            for c in closed:
                from bot.telegram_bot import send_result_to_channel
                send_result_to_channel(
                    symbol=c["symbol"],
                    signal_id=c.get("signal_id", "N/A"),
                    result=c["result"],
                    pnl=c["pnl"],
                    leverage=c.get("leverage", 5),
                    margin_usd=c.get("margin_usd", 0)
                )
        except Exception as e:
            print(f"Check closed signals error: {e}")

        # چک تایید/باطل شدن سیگنال‌های فعال
        try:
            monitor_active_signals()
        except Exception as e:
            print(f"Monitor active signals error: {e}")

        # اسکن نمادها
        for symbol in SYMBOLS:
            try:
                signals, df_15m = analyze_symbol(symbol)

                for sig in signals:
                    try:
                        if was_signal_sent_recently(
                            symbol, sig["source"],
                            sig["direction"], hours=4
                        ):
                            continue

                        attach_money_management(sig)
                        save_signal(sig)
                        save_active_signal(sig)
                        send_signal_with_chart(sig, df_15m)
                        time.sleep(2)

                    except Exception as e:
                        print(f"Signal send error {symbol}: {e}")

            except Exception as e:
                print(f"Error {symbol}: {e}")

        print(f"[{datetime.utcnow().strftime('%H:%M')}] Scan done.")

    except Exception as e:
        print(f"Critical scan error: {e}")


def run_daily_report():
    try:
        stats = get_performance_stats()
        send_performance_report(stats)
    except Exception as e:
        print(f"Daily report error: {e}")
        send_message("📊 گزارش روزانه: هنوز سیگنال بسته‌ای نداریم.")


def main():
    if not os.environ.get("TELEGRAM_TOKEN"):
        print("WARNING: TELEGRAM_TOKEN is not set")

    try:
        init_db()
    except Exception as e:
        print(f"DB init error: {e}")

    send_message(
        "🚀 <b>Scanner v4 Started</b>\n"
        "📊 SMC | 🔷 RTM | 💎 ICT\n"
        "🧠 Smart Memory Active\n"
        f"📌 {len(SYMBOLS)} Symbols\n"
        "⏱ Scan: 15min"
    )

    schedule.every(15).minutes.do(run_scan)
    schedule.every().day.at("08:00").do(run_daily_report)

    run_scan()

    while True:
        try:
            schedule.run_pending()
            time.sleep(60)
        except Exception as e:
            print(f"Scheduler error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
