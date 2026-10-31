# Keliabot — Binance Trading Bot

A Python-based Binance trading bot prototype for BTC/USDT. The repository contains Spot and Futures strategy implementations. Trading involves substantial financial risk; this project is not financial advice and must be tested on Binance Testnet before any live use.

## Security first

Never put API keys or secrets directly in Python source files. Credentials are loaded from environment variables through python-dotenv.

1. Revoke any API credentials that were previously committed to this repository. Removing a secret from the latest version does not remove it from Git history.
2. Create a new Binance API key. Keep withdrawals disabled and grant only the permissions required for testing.
3. Copy Keliabot/.env.example to Keliabot/.env and enter your new credentials.
4. Never commit the local .env file. The root .gitignore excludes it.

## Setup

Use Python 3.10 or newer where possible:

```bash
cd Keliabot
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Configuration

Copy Keliabot/.env.example to Keliabot/.env and set BINANCE_API_KEY and BINANCE_API_SECRET. Do not share the resulting file.

## Current files

- main.py — Spot trading implementation.
- BTCUSDT.py — Futures trading implementation.
- ReasonSignal.py — alternate Futures strategy implementation.
- keys.py — shared environment-based credential loader.

## Important limitations

This is an early-stage prototype. Order execution, exchange filters, stop-loss/take-profit handling, position sizing, and recovery from network/API failures still require review and testing. Do not run against a funded live account. The next development steps should add safe Testnet-only defaults, automated tests, and validated risk controls.
