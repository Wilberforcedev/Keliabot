"""Generate a self-contained HTML comparison of offline backtests."""
import argparse
import html
import json
from pathlib import Path

from backtesting import SMACrossoverBacktester, load_ohlcv_csv


def compare_files(files, starting_cash="1000", fee_rate="0.001", fast_period=9, slow_period=26):
    """Run identical strategy settings against each timeframe's local CSV."""
    if not files:
        raise ValueError("Provide at least one timeframe CSV")
    results = {}
    for timeframe, path in files.items():
        rows = load_ohlcv_csv(path)
        results[timeframe] = SMACrossoverBacktester(
            starting_cash=starting_cash,
            fee_rate=fee_rate,
            fast_period=fast_period,
            slow_period=slow_period,
        ).run(rows)
    return results


def build_report(results, output_path, settings=None):
    """Write a self-contained HTML report with metric table and equity curves."""
    if not results:
        raise ValueError("No backtest results to report")
    settings = settings or {}
    names = list(results)
    colors = ["#2563eb", "#059669", "#d97706", "#7c3aed"]
    chart_data = []
    for index, name in enumerate(names):
        values = [float(value) for value in results[name]["equity_curve"]]
        if not values:
            values = [float(results[name]["starting_cash"]), float(results[name]["ending_equity"])]
        chart_data.append({"name": name, "values": values, "color": colors[index % len(colors)]})

    ranked = sorted(names, key=lambda name: results[name]["total_return_pct"], reverse=True)
    rows = []
    for name in names:
        result = results[name]
        rows.append(
            "<tr>"
            f"<th>{html.escape(name)}</th>"
            f"<td>{result['ending_equity']:.2f}</td>"
            f"<td>{result['net_pnl']:.2f}</td>"
            f"<td>{result['total_return_pct']:.2f}%</td>"
            f"<td>{result['max_drawdown_pct']:.2f}%</td>"
            f"<td>{result['closed_trades']}</td>"
            f"<td>{result['win_rate_pct']:.2f}%</td>"
            "</tr>"
        )
    settings_text = html.escape(
        f"Starting cash: {settings.get('starting_cash', '1000')} | "
        f"Fee per side: {settings.get('fee_rate', '0.001')} | "
        f"SMA: {settings.get('fast_period', 9)}/{settings.get('slow_period', 26)}"
    )
    winner = ranked[0]
    payload = json.dumps(chart_data, separators=(",", ":")).replace("</", "<\\/")
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Keliabot timeframe comparison</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f5f7fb;color:#172033;margin:0;padding:24px}}
main{{max-width:1100px;margin:auto}}h1{{margin-bottom:6px}}.muted{{color:#64748b}}
.panel{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:18px;margin:18px 0;overflow:auto}}
canvas{{width:100%;height:360px;display:block}}table{{border-collapse:collapse;width:100%;min-width:680px}}
th,td{{padding:12px;text-align:right;border-bottom:1px solid #e2e8f0}}th:first-child,td:first-child{{text-align:left}}
th{{background:#f8fafc}}.winner{{font-weight:700}}.note{{background:#fff7ed;border-left:4px solid #d97706;padding:12px}}
.legend span{{display:inline-block;margin:6px 16px 0 0}}.swatch{{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px}}
</style></head><body><main>
<h1>Keliabot · Timeframe comparison</h1><p class="muted">{settings_text}</p>
<div class="panel"><h2>Equity curves</h2><canvas id="equity" width="1000" height="360"></canvas><div class="legend" id="legend"></div>
<p class="muted">Each line plots recorded backtest equity observations in sequence. Different candle intervals can produce different observation counts.</p></div>
<div class="panel"><h2>Performance metrics</h2><table><thead><tr><th>Timeframe</th><th>Ending equity</th><th>Net P/L</th><th>Return</th><th>Max drawdown</th><th>Closed trades</th><th>Win rate</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>
<p class="muted">Highest historical return in this comparison: <strong>{html.escape(winner)}</strong>. This is not proof it is the best live strategy.</p></div>
<p class="note"><strong>Important:</strong> Historical results are not forecasts or financial advice. Comparisons are meaningful only when the CSVs cover comparable date ranges and use identical settings. This simple model excludes slippage, spread, liquidity effects and exchange execution constraints. Open positions are marked to market, not force-closed.</p>
</main>
<script>
const series={payload};
const canvas=document.getElementById('equity'),ctx=canvas.getContext('2d');
const W=canvas.width,H=canvas.height,pad=48;
const vals=series.flatMap(s=>s.values),lo=Math.min(...vals),hi=Math.max(...vals);
ctx.clearRect(0,0,W,H);ctx.strokeStyle='#cbd5e1';ctx.lineWidth=1;
for(let i=0;i<5;i++){{let y=pad+(H-2*pad)*i/4;ctx.beginPath();ctx.moveTo(pad,y);ctx.lineTo(W-pad,y);ctx.stroke();}}
ctx.fillStyle='#64748b';ctx.font='12px system-ui';
for(let i=0;i<5;i++){{let v=hi-(hi-lo)*i/4;ctx.fillText(v.toFixed(2),4,pad+(H-2*pad)*i/4+4);}}
for(const s of series){{ctx.strokeStyle=s.color;ctx.lineWidth=2.5;ctx.beginPath();
s.values.forEach((v,i)=>{{const x=pad+(W-2*pad)*(s.values.length===1?0:i/(s.values.length-1));const y=H-pad-(H-2*pad)*(hi===lo?0.5:(v-lo)/(hi-lo));if(i===0)ctx.moveTo(x,y);else ctx.lineTo(x,y);}});ctx.stroke();
const item=document.createElement('span');item.innerHTML='<i class="swatch" style="background:'+s.color+'"></i>'+s.name;document.getElementById('legend').appendChild(item);}}
</script></body></html>"""
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(document, encoding="utf-8")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--1m", dest="one_minute", help="1-minute candle CSV")
    parser.add_argument("--5m", dest="five_minute", help="5-minute candle CSV")
    parser.add_argument("--15m", dest="fifteen_minute", help="15-minute candle CSV")
    parser.add_argument("--cash", default="1000")
    parser.add_argument("--fee", default="0.001")
    parser.add_argument("--fast", type=int, default=9)
    parser.add_argument("--slow", type=int, default=26)
    parser.add_argument("--output", default="timeframe_comparison.html")
    args = parser.parse_args()
    files = {name: path for name, path in (
        ("1m", args.one_minute), ("5m", args.five_minute), ("15m", args.fifteen_minute)
    ) if path}
    if not files:
        parser.error("Provide at least one CSV using --1m, --5m, or --15m")
    results = compare_files(files, args.cash, args.fee, args.fast, args.slow)
    path = build_report(results, args.output, {
        "starting_cash": args.cash, "fee_rate": args.fee,
        "fast_period": args.fast, "slow_period": args.slow,
    })
    print(f"Comparison report saved to {path}")
    print("Highest historical return:", max(results, key=lambda name: results[name]["total_return_pct"]))


if __name__ == "__main__":
    main()
