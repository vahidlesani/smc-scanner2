import requests
import io
import os
import pandas as pd
import mplfinance as mpf
import matplotlib
matplotlib.use('Agg')  # بدون GUI

TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")


def send_message(text: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }, timeout=10)


def send_photo(image_bytes: bytes, caption: str):
    url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    requests.post(url, 
        data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
        files={"photo": ("chart.png", image_bytes, "image/png")},
        timeout=30
    )


def generate_chart(df: pd.DataFrame, sig: dict) -> bytes:
    """
    چارت کندل با ناحیه‌های مهم
    """
    # آخرین 60 کندل
    chart_df = df.tail(60).copy()
    chart_df = chart_df.set_index("timestamp")
    chart_df.index = pd.DatetimeIndex(chart_df.index)
    
    # رنگ‌بندی
    mc = mpf.make_marketcolors(
        up='#00ff88', down='#ff4444',
        edge='inherit',
        wick='inherit',
        volume='in'
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        base_mpf_style='nightclouds',
        gridstyle=':'
    )
    
    # خطوط اضافه
    hlines = []
    hline_colors = []
    
    # Entry
    hlines.append(sig["entry"])
    hline_colors.append('#ffffff')
    
    # SL
    hlines.append(sig["sl"])
    hline_colors.append('#ff4444')
    
    # TP1
    hlines.append(sig["tp1"])
    hline_colors.append('#00ff88')
    
    # TP2
    hlines.append(sig["tp2"])
    hline_colors.append('#00aa55')
    
    # رندر به bytes
    buf = io.BytesIO()
    
    mpf.plot(
        chart_df,
        type='candle',
        style=style,
        title=f"\n{sig['symbol']} | {sig['source']} | {sig['direction']}",
        ylabel='Price',
        hlines=dict(hlines=hlines, colors=hline_colors, 
                   linestyle='--', linewidths=1),
        volume=True,
        savefig=dict(fname=buf, dpi=150, bbox_inches='tight'),
        figsize=(12, 7)
    )
    
    buf.seek(0)
    return buf.read()


def send_signal_with_chart(sig: dict, df_15m: pd.DataFrame):
    """
    سیگنال رو با چارت میفرسته
    """
    direction_emoji = "🟢" if sig["direction"] == "LONG" else "🔴"
    source_emoji = {
        "SMC": "📊",
        "RTM": "🔷", 
        "ICT": "💎"
    }.get(sig["source"], "📌")
    
    # متن پیام
    caption = build_caption(sig, direction_emoji, source_emoji)
    
    # ساخت چارت
    try:
        chart_bytes = generate_chart(df_15m, sig)
        send_photo(chart_bytes, caption)
    except Exception as e:
        print(f"Chart error: {e}")
        # اگر چارت خطا داد، فقط متن بفرست
        send_message(caption)


def build_caption(sig: dict, dir_emoji: str, src_emoji: str) -> str:
    
    conf_lines = ""
    if "confirmations" in sig:
        conf_lines = "\n".join(sig["confirmations"])
    
    extra = ""
    if sig["source"] == "SMC":
        extra = f"🔲 OB Zone: {sig.get('ob_zone','')}\n"
    elif sig["source"] == "RTM":
        extra = f"🔷 Pattern: {sig.get('pattern','')} ({sig.get('strength','')})\n"
        extra += f"📌 Base: {sig.get('base_zone','')}\n"
    elif sig["source"] == "ICT":
        kz = sig.get('killzone','None')
        in_kz = "✅" if sig.get('in_killzone') else "⚠️"
        mss = "✅ MSS" if sig.get('mss') else "⏳ No MSS"
        extra = f"⏰ KZ: {in_kz} {kz} | {mss}\n"
    
    trade = sig["trade_params"]
    
    return f"""{src_emoji} <b>{sig['source']} SIGNAL</b> {dir_emoji}
━━━━━━━━━━━━━━━
🪙 <b>{sig['symbol']}</b> | {sig['direction']}
📈 HTF Bias: {sig['bias']}

{extra}
📍 Entry: <b>{sig['entry']:.4f}</b>
🛑 SL: {sig['sl']:.4f} ({trade['sl_pct']:.2f}%)
🎯 TP1: {sig['tp1']:.4f} (1:2)
🎯 TP2: {sig['tp2']:.4f} (1:3)

{conf_lines}

💰 Risk: ${trade['risk_amount']:.1f}
━━━━━━━━━━━━━━━
⚠️ <i>چارت رو چک کن قبل از ورود!</i>"""


def send_performance_report(stats: dict):
    """گزارش عملکرد روزانه"""
    if not stats:
        send_message("📊 هنوز سیگنال بسته‌ای نداریم.")
        return
    
    lines = ["📊 <b>Performance Report</b>\n━━━━━━━━━━━━━━━"]
    
    for source, data in stats.items():
        emoji = {"SMC": "📊", "RTM": "🔷", "ICT": "💎"}.get(source, "📌")
        lines.append(
            f"{emoji} <b>{source}</b>\n"
            f"   Win: {data['wins']} | Loss: {data['losses']}\n"
            f"   WinRate: {data['winrate']:.1f}%\n"
            f"   Avg PnL: {data['avg_pnl']:.2f}%"
        )
    
    send_message("\n".join(lines))
