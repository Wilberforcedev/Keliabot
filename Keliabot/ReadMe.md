# Keliabot — Binance Trading Bot Prototype

Keliabot is an experimental Python trading-bot repository containing Spot and Futures strategy examples. It is not financial advice. Do not connect it to a funded account.

## Security first

- Revoke any Binance API credentials previously committed to this repository. Removing a secret from the latest source does not erase it from Git history.
- Use fresh Testnet credentials only. Keep withdrawals disabled and grant the minimum permissions required.
- Copy `.env.example` to `.env` and enter credentials locally. Never commit or share `.env`.

## Setup

Use Python 3.10 or newer:

```bash
cd Keliabot
python -m venv .venv
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Offline paper trading (no API keys or network)

The simulator is deliberately independent of Binance and uses a virtual cash balance:

```bash
python -m unittest test_paper_trading -v
```

Example use:

```python
from paper_trading import PaperTradingAccount

account = PaperTradingAccount(starting_cash="1000", fee_rate="0.001")
account.execute("buy", quantity="0.01", price="60000")
print(account.summary(mark_price="61000"))
```

The simulator supports spot-style buys and sells, fee accounting, balance checks, and mark-to-market equity. It does not place orders or connect to an exchange.


## Historical backtesting (offline)

Keliabot includes a simple long-only Spot SMA crossover backtester. It reads local historical candle CSV data and does not connect to Binance or submit orders. It uses the candle close to calculate signals and fills a signal at the next candle's open to avoid same-candle look-ahead. Fees are charged on both entry and exit. Any open position is marked to the final close for ending equity; it is not force-closed.

CSV input requires a header with at least `open` and `close` columns (case-insensitive). Other columns such as timestamp, high, low, and volume may also be present.

Run it from the `Keliabot` directory:

```bash
python run_backtest.py path/to/BTCUSDT.csv --cash 1000 --fee 0.001 --fast 9 --slow 26
```

The report includes ending equity, net P/L, return, closed trades, win rate, and maximum drawdown. Results depend on the input data, fee assumptions, and selected parameters. They do not predict future performance and do not account for slippage, spread, funding, liquidity, or exchange-specific execution constraints.

Run the offline tests:

```bash
python -m unittest test_paper_trading test_backtesting test_market_data -v
```


## Download historical Binance Spot data

The downloader uses Binance's public market-data endpoint. It does not require API keys, connect to a user account, or place orders. Supported intervals are 1m, 5m, and 15m.

Run from the \`Keliabot\` directory. The end date is exclusive and dates without a time are interpreted as UTC:

\`\`\`bash
python fetch_market_data.py --symbol BTCUSDT --interval 1m --start 2026-01-01 --end 2026-01-08
python fetch_market_data.py --symbol BTCUSDT --interval 5m --start 2026-01-01 --end 2026-01-08
python fetch_market_data.py --symbol BTCUSDT --interval 15m --start 2026-01-01 --end 2026-01-08
\`\`\`

By default, files are saved under \`data/\`, for example \`data/BTCUSDT_1m.csv\`. You can set \`--output\` to choose another path. The generated CSV includes open time, OHLC prices, volume, and close time and can be passed directly to the backtester:

\`\`\`bash
python run_backtest.py data/BTCUSDT_1m.csv --cash 1000 --fee 0.001 --fast 9 --slow 26
\`\`\`

Download only the date range and timeframe you need. Public endpoint availability and historical retention are subject to Binance service limits. Backtest output is historical analysis, not a prediction or trading recommendation.

## Compare backtest timeframes

After downloading comparable BTCUSDT data for the same UTC date range, generate one HTML report with shared strategy settings:

\`\`\`bash
python compare_timeframes.py --1m data/BTCUSDT_1m.csv --5m data/BTCUSDT_5m.csv --15m data/BTCUSDT_15m.csv --cash 1000 --fee 0.001 --fast 9 --slow 26
\`\`\`

Open \`timeframe_comparison.html\` in a browser. The report contains equity curves and a metrics table for ending equity, net P/L, return, maximum drawdown, closed trades, and win rate. You can compare only the intervals you have by supplying one or two of the CSV options. All intervals use the same starting cash, fee rate, and SMA periods.

The report labels the highest historical return but does not declare a profitable or universally best timeframe. Make sure each input file covers the same date range. The equity curves plot recorded backtest observations in sequence; because candle intervals differ, observation counts are not directly time-aligned.

Run all offline tests:

\`\`\`bash
python -m unittest test_paper_trading test_backtesting test_market_data test_compare_timeframes -v
\`\`\`

## Testnet client helper

`binance_clients.py` provides separate Spot and USD-M Futures Testnet client factories. It rejects a non-Testnet mode and keeps order submission disabled unless explicitly opted in. This helper is not yet wired into every legacy strategy script; those scripts remain experimental and should not be run until their execution paths have been reviewed and migrated.

Configuration variables in `.env`:

- `BINANCE_API_KEY` and `BINANCE_API_SECRET`: Testnet credentials only.
- `KELIABOT_MODE=testnet`: only supported mode in the helper.
- `KELIABOT_ALLOW_ORDERS=false`: default; order submission remains disabled in the helper.

## Existing strategy files

- `main.py` — legacy Spot strategy.
- `BTCUSDT.py` — Futures strategy.
- `ReasonSignal.py` — alternate Futures strategy.
- `test.py` — legacy strategy experiment (not the offline unit-test suite).
- `keys.py` — shared environment-based credential loader.
- `paper_trading.py` — offline simulator.
- `test_paper_trading.py` — simulator unit tests.

## Known limitations

The legacy strategies need further work on exchange filters, order lifecycle handling, stop-loss/take-profit logic, position sizing, duplicate-order prevention, API failures, and safe execution gating. No profitability or live-trading readiness is claimed. Validate the simulator and strategy logic before any Testnet integration.
