# dashboard/app.py - Simple Web Dashboard
import os
import sys
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
    return jsonify({"status": "ok", "version": SETTINGS.version, "confirmed_only": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", os.environ.get("DASHBOARD_PORT", 8080)))
    app.run(host="0.0.0.0", port=port, debug=False)
