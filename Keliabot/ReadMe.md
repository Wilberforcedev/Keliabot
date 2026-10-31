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
