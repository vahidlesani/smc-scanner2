# dashboard/app.py - Simple Web Dashboard
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template_string, jsonify
from database.db import (
    get_dashboard_summary, get_recent_signals,
    get_strategy_performance, get_backtest_stats
)
from database.repository_v7 import init_v7_schema
from config import get_settings

SETTINGS = get_settings()
app = Flask(__name__)

# ── r27b: visible boot fingerprint — «تأیید هر دیپلوی» از سطحِ عمومی. The
# live commit (Railway injects RAILWAY_GIT_COMMIT_SHA) beats the stamped
# BUILD_INFO file; /health exposes both boot identity keys.
_BOOT_SHA = ((os.getenv("RAILWAY_GIT_COMMIT_SHA")
              or os.getenv("COMMIT_SHA") or "")[:12])
if not _BOOT_SHA:
    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "..", "BUILD_INFO")) as _bif:
            _BOOT_SHA = _bif.read().strip()[:12] or "unknown"
    except Exception:
        _BOOT_SHA = "unknown"
_BOOT_AT = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

# ── Viva 09-23: the mobile PWA (feed/analytics/control) + THE login lock on
# every route of this server (the Railway domain is public — nothing leaks).
from webapp_viva import install_viva_app
install_viva_app(app)

# r55 (Viva: «اپلیکیشن دقیقا باید مثل تلگرام عمل بکنه»): the 5s lifecycle
# tailer lives in the web process — it watches confirmed/tp/closed stamps and
# fires the phone pushes. Fail-open: a push outage never touches the scanner.
try:
    from database.app_push import start_push_tailer as _spt55
    _spt55()
except Exception as _tail_exc:
    print(f"push tailer not started: {_tail_exc}")
CHANNEL_NAME = SETTINGS.channel_name

try:
    init_v7_schema()
except Exception as exc:
    print(f"Dashboard DB initialization warning: {exc}")

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>📊 Viva Confirmed Signals Dashboard v7</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, sans-serif;
            background: #0a0a1a;
            color: #e0e0e0;
            min-height: 100vh;
        }
        .header {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            padding: 20px 30px;
            border-bottom: 2px solid #0f3460;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 { color: #00ff88; font-size: 24px; }
        .header .channel { color: #64ffda; font-size: 14px; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        .stat-card {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            border: 1px solid #0f3460;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }
        .stat-card .value {
            font-size: 32px;
            font-weight: bold;
            margin: 10px 0;
        }
        .stat-card .label { color: #888; font-size: 14px; }
        .stat-card.win .value { color: #00ff88; }
        .stat-card.loss .value { color: #ff4444; }
        .stat-card.pending .value { color: #ffd700; }
        .stat-card.rate .value { color: #64ffda; }
        
        .section {
            background: linear-gradient(135deg, #1a1a2e, #16213e);
            border: 1px solid #0f3460;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .section h2 {
            color: #00ff88;
            margin-bottom: 15px;
            font-size: 18px;
            border-bottom: 1px solid #0f3460;
            padding-bottom: 10px;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 10px 12px;
            text-align: center;
            border-bottom: 1px solid #1a1a3e;
        }
        th { color: #64ffda; font-size: 13px; }
        td { font-size: 13px; }
        tr:hover { background: rgba(100, 255, 218, 0.05); }
        
        .badge {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
        }
        .badge-win { background: rgba(0,255,136,0.2); color: #00ff88; }
        .badge-loss { background: rgba(255,68,68,0.2); color: #ff4444; }
        .badge-pending { background: rgba(255,215,0,0.2); color: #ffd700; }
        .badge-long { background: rgba(0,255,136,0.15); color: #00ff88; }
        .badge-short { background: rgba(255,68,68,0.15); color: #ff4444; }
        
        .progress-bar {
            height: 8px;
            background: #1a1a3e;
            border-radius: 4px;
            overflow: hidden;
            margin-top: 5px;
        }
        .progress-fill {
            height: 100%;
            border-radius: 4px;
            transition: width 0.3s;
        }
        .progress-fill.green { background: #00ff88; }
        .progress-fill.yellow { background: #ffd700; }
        .progress-fill.red { background: #ff4444; }
        
        .score { color: #ffd700; }
        .pnl-pos { color: #00ff88; }
        .pnl-neg { color: #ff4444; }
        
        @media (max-width: 768px) {
            .stats-grid { grid-template-columns: repeat(2, 1fr); }
            table { font-size: 11px; }
            th, td { padding: 6px 4px; }
        }
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>📊 Viva Confirmed Signals • v7</h1>
            <div class="channel">📢 {{ channel }} • فقط معاملات Confirmed</div>
        </div>
        <div style="text-align: left;">
            <div style="color: #888; font-size: 12px;">Auto-refresh: 60s</div>
        </div>
    </div>
    
    <div class="container">
        <!-- خلاصه آمار -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="label">کل سیگنال‌ها</div>
                <div class="value">{{ summary.total_signals }}</div>
            </div>
            <div class="stat-card win">
                <div class="label">برنده ✅</div>
                <div class="value">{{ summary.wins }}</div>
            </div>
            <div class="stat-card loss">
                <div class="label">باخته ❌</div>
                <div class="value">{{ summary.losses }}</div>
            </div>
            <div class="stat-card pending">
                <div class="label">در انتظار ⏳</div>
                <div class="value">{{ summary.pending }}</div>
            </div>
            <div class="stat-card rate">
                <div class="label">Win Rate 🎯</div>
                <div class="value">{{ summary.winrate }}%</div>
                <div class="progress-bar">
                    <div class="progress-fill {{ 'green' if summary.winrate >= 55 else 'yellow' if summary.winrate >= 40 else 'red' }}" 
                         style="width: {{ summary.winrate }}%"></div>
                </div>
            </div>
            <div class="stat-card">
                <div class="label">میانگین سود</div>
                <div class="value {{ 'pnl-pos' if summary.avg_pnl >= 0 else 'pnl-neg' }}">
                    {{ '%+.2f'|format(summary.avg_pnl) }}%
                </div>
            </div>
        </div>
        
        <!-- عملکرد استراتژی‌ها -->
        <div class="section">
            <h2>🔮 عملکرد استراتژی‌ها</h2>
            <table>
                <thead>
                    <tr>
                        <th>استراتژی</th>
                        <th>کل</th>
                        <th>برد</th>
                        <th>باخت</th>
                        <th>Win Rate</th>
                        <th>میانگین PnL</th>
                        <th>بهترین</th>
                        <th>بدترین</th>
                        <th>امتیاز</th>
                    </tr>
                </thead>
                <tbody>
                    {% for s in strategies %}
                    <tr>
                        <td><strong>{{ s.strategy_fa }}</strong></td>
                        <td>{{ s.total }}</td>
                        <td class="pnl-pos">{{ s.wins }}</td>
                        <td class="pnl-neg">{{ s.losses }}</td>
                        <td>
                            <span class="score">{{ '%.1f'|format(s.winrate) }}%</span>
                            <div class="progress-bar">
                                <div class="progress-fill {{ 'green' if s.winrate >= 55 else 'yellow' if s.winrate >= 40 else 'red' }}" 
                                     style="width: {{ s.winrate }}%"></div>
                            </div>
                        </td>
                        <td class="{{ 'pnl-pos' if s.avg_pnl >= 0 else 'pnl-neg' }}">
                            {{ '%+.2f'|format(s.avg_pnl) }}%
                        </td>
                        <td class="pnl-pos">{{ '%+.2f'|format(s.best_pnl) }}%</td>
                        <td class="pnl-neg">{{ '%+.2f'|format(s.worst_pnl) }}%</td>
                        <td class="score">{{ s.avg_score }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <!-- سیگنال‌های اخیر -->
        <div class="section">
            <h2>📋 سیگنال‌های اخیر</h2>
            <table>
                <thead>
                    <tr>
                        <th>شناسه</th>
                        <th>نماد</th>
                        <th>ستاپ</th>
                        <th>نوع</th>
                        <th>جهت</th>
                        <th>ورود</th>
                        <th>استاپ</th>
                        <th>TP1</th>
                        <th>نتیجه</th>
                        <th>PnL</th>
                        <th>امتیاز</th>
                    </tr>
                </thead>
                <tbody>
                    {% for sig in signals %}
                    <tr>
                        <td><code style="font-size:10px;">{{ sig.signal_id }}</code></td>
                        <td><strong>{{ sig.symbol }}</strong></td>
                        <td>{{ sig.strategy_fa }}</td>
                        <td><span class="badge badge-pending">{{ sig.trade_style }}</span></td>
                        <td>
                            <span class="badge badge-{{ sig.direction|lower }}">
                                {{ sig.direction }}
                            </span>
                        </td>
                        <td>{{ '%.4f'|format(sig.entry) }}</td>
                        <td>{{ '%.4f'|format(sig.sl) }}</td>
                        <td>{{ '%.4f'|format(sig.tp1) }}</td>
                        <td>
                            <span class="badge badge-{{ sig.result|lower }}">
                                {{ sig.result }}
                            </span>
                        </td>
                        <td class="{{ 'pnl-pos' if sig.pnl_pct >= 0 else 'pnl-neg' }}">
                            {{ '%+.2f'|format(sig.pnl_pct) }}%
                        </td>
                        <td class="score">{{ sig.score }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        
        <!-- بک‌تست -->
        {% if backtests %}
        <div class="section">
            <h2>🧪 نتایج بک‌تست</h2>
            <table>
                <thead>
                    <tr>
                        <th>استراتژی</th>
                        <th>کل</th>
                        <th>برد</th>
                        <th>باخت</th>
                        <th>Win Rate</th>
                        <th>میانگین PnL</th>
                        <th>Expectancy</th>
                        <th>Profit Factor</th>
                        <th>میانگین کندل</th>
                        <th>Max DD</th>
                    </tr>
                </thead>
                <tbody>
                    {% for b in backtests %}
                    <tr>
                        <td><strong>{{ b.strategy }}</strong></td>
                        <td>{{ b.total }}</td>
                        <td class="pnl-pos">{{ b.wins }}</td>
                        <td class="pnl-neg">{{ b.losses }}</td>
                        <td class="score">{{ '%.1f'|format(b.winrate) }}%</td>
                        <td class="{{ 'pnl-pos' if b.avg_pnl >= 0 else 'pnl-neg' }}">
                            {{ '%+.2f'|format(b.avg_pnl) }}%
                        </td>
                        <td class="{{ 'pnl-pos' if b.expectancy|default(0) >= 0 else 'pnl-neg' }}">{{ '%+.3f'|format(b.expectancy|default(0)) }}%</td>
                        <td class="score">{{ '%.2f'|format(b.profit_factor|default(0)) }}</td>
                        <td>{{ '%.0f'|format(b.avg_bars) }}</td>
                        <td class="pnl-neg">{{ '%.2f'|format(b.avg_dd) }}%</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        {% endif %}
    </div>
    
    <script>
        // Auto-refresh every 60 seconds
        setTimeout(() => location.reload(), 60000);
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    summary = get_dashboard_summary()
    signals = get_recent_signals(30)
    strategies = get_strategy_performance()
    backtests = get_backtest_stats()
    
    return render_template_string(
        DASHBOARD_HTML,
        channel=CHANNEL_NAME,
        summary=summary,
        signals=signals,
        strategies=strategies,
        backtests=backtests
    )


@app.route("/api/summary")
def api_summary():
    return jsonify(get_dashboard_summary())


@app.route("/api/signals")
def api_signals():
    return jsonify(get_recent_signals(50))


@app.route("/api/strategies")
def api_strategies():
    return jsonify(get_strategy_performance())


@app.route("/api/backtest")
def api_backtest():
    return jsonify(get_backtest_stats())


@app.route("/health")
def health():
    scanner = app.config.get("VIVA_SCANNER_THREAD")
    scanner_alive = scanner.is_alive() if scanner is not None else None
    status = "ok" if scanner_alive is not False else "degraded"
    payload = {
        "status": status,
        "version": SETTINGS.version,
        "confirmed_only": True,
        "scanner_alive": scanner_alive,
        "boot_sha": _BOOT_SHA,
        "boot_at": _BOOT_AT,
    }
    # r55 DIAGNOSTICS (Viva 09-28: «ببین علت طبیعیه یا گیت خفه‌کننده یا باگ؟؟»)
    # Everything below is fail-open: a broken probe never degrades /health.
    import json as _json
    diag: dict = {}
    try:   # the app's state engine — the 09-28 freeze detector
        import webapp_viva as _wv
        st = _wv._STATE_CACHE.get("state") or {}
        feed = st.get("feed") or []
        pend = [x for x in feed if x.get("result") == "PENDING"]
        diag["app_state"] = {
            "last_rebuild_error": str(getattr(_wv, "_LAST_STATE_ERROR", "") or ""),
            "cache_age_s": (round(time.monotonic() - _wv._STATE_CACHE["at"], 1)
                            if _wv._STATE_CACHE.get("state") else None),
            "feed_rows": len(feed),
            "newest_created_at": str(feed[0].get("time") or "") if feed else "",
            "newest_pending_at": str(pend[0].get("time") or "") if pend else "",
        }
    except Exception as _e1:
        diag["app_state"] = {"error": str(_e1)[:80]}
    try:   # lane activity: last 24h per setup/source + spot + VOID
        from database.db import db_cursor
        with db_cursor() as c:
            c.execute("""
                SELECT COALESCE(setup_code, source) AS lane, COUNT(*),
                       SUM(CASE WHEN confirmed=TRUE THEN 1 ELSE 0 END),
                       MAX(created_at), MAX(confirmed_at)
                FROM signals
                WHERE created_at >= (NOW() - INTERVAL '24 hours')
                GROUP BY 1 ORDER BY MAX(created_at) DESC
            """ if getattr(__import__("database.db", fromlist=["db"]).db, "USE_POSTGRES", False) else """
                SELECT COALESCE(setup_code, source) AS lane, COUNT(*),
                       SUM(CASE WHEN confirmed=1 THEN 1 ELSE 0 END),
                       MAX(created_at), MAX(confirmed_at)
                FROM signals
                WHERE created_at >= datetime('now', '-24 hours')
                GROUP BY 1 ORDER BY MAX(created_at) DESC
            """)
            diag["lanes_24h"] = [
                {"lane": r[0], "total": int(r[1] or 0), "confirmed": int(r[2] or 0),
                 "last_created": str(r[3] or ""), "last_confirmed": str(r[4] or "")}
                for r in c.fetchall()]
            c.execute("""
                SELECT COUNT(*), MAX(closed_at) FROM signals
                WHERE result='VOID' AND closed_at >= (NOW() - INTERVAL '24 hours')
            """ if getattr(__import__("database.db", fromlist=["db"]).db, "USE_POSTGRES", False) else """
                SELECT COUNT(*), MAX(closed_at) FROM signals
                WHERE result='VOID' AND closed_at >= datetime('now', '-24 hours')
            """)
            _v = c.fetchone()
            diag["void_24h"] = {"count": int(_v[0] or 0), "last": str(_v[1] or "")}
            c.execute("SELECT symbol, source, direction, created_at FROM signals "
                      "WHERE source ILIKE '%SPOT%' ORDER BY created_at DESC LIMIT 1"
                      if getattr(__import__("database.db", fromlist=["db"]).db, "USE_POSTGRES", False)
                      else "SELECT symbol, source, direction, created_at FROM signals "
                           "WHERE upper(source) LIKE '%SPOT%' ORDER BY created_at DESC LIMIT 1")
            _s = c.fetchone()
            diag["spot_last"] = ({"symbol": _s[0], "source": _s[1],
                                  "direction": _s[2], "created_at": str(_s[3] or "")}
                                 if _s else None)
    except Exception as _e2:
        diag["db"] = {"error": str(_e2)[:120]}
    try:   # KV liveness: scanner heartbeat, spot lane reason, funnel, push tail
        from database.bot_kv import get_json as _gj
        hb = _gj("scanner_heartbeat", {}) or {}
        diag["heartbeat"] = {"when": hb.get("when"), "stage": hb.get("stage"),
                             "last_scan": hb.get("last_scan"),
                             "last_monitor": hb.get("last_monitor")}
        sp = _gj("spot_lane_status", {}) or {}
        diag["spot_lane"] = {"reason": sp.get("reason"), "at": sp.get("at"),
                             "stats": sp.get("stats")}
        try:
            from database.app_push import tail_health, subscriber_count
            diag["push_tail"] = dict(tail_health(), subs=subscriber_count())
        except Exception as _e3:
            diag["push_tail"] = {"error": str(_e3)[:80]}
    except Exception as _e4:
        diag["kv"] = {"error": str(_e4)[:80]}
    payload["diag"] = diag
    return jsonify(payload), (200 if status == "ok" else 503)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("DASHBOARD_PORT", 8080)))
    app.run(host="0.0.0.0", port=port, debug=False)
