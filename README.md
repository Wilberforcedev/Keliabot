# Keliabot

Keliabot is an experimental Python project for exploring Binance Spot and Futures trading strategies. It includes offline paper trading, historical backtesting, and tools for downloading and comparing market data.

> **Testnet only:** Keliabot is experimental and is not ready for funded or live trading. Keep order submission disabled unless you intentionally enable it for Binance Testnet. Never use live API credentials, and disable withdrawals on API keys.

## Quick start

Requirements: Python 3.10 or newer.

```bash
git clone https://github.com/Wilberforcedev/Keliabot.git
cd Keliabot/Keliabot
python -m venv .venv
```

Activate the virtual environment:

```bash
# Windows PowerShell
.venv\Scripts\Activate.ps1

# macOS/Linux
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Try the offline tools

The paper-trading simulator and historical backtester run without Binance API credentials. Run the offline test suite from the `Keliabot` directory:

```bash
python -m unittest test_paper_trading test_backtesting test_market_data test_compare_timeframes -v
```

See the project guide for examples covering paper trading, backtesting, market-data downloads, timeframe comparisons, and Testnet setup:

[Read the Keliabot guide](Keliabot/ReadMe.md)

## Security

Do not commit API keys or secrets. Copy `.env.example` to `.env` and use fresh Testnet credentials only. If a credential was ever committed, revoke it; deleting it from the latest version does not remove it from Git history.

## License

Keliabot is released under the [MIT License](LICENSE).
