"""Safe Binance client factories. Live trading is deliberately unsupported."""
import os
from binance.client import Client
from keys import api_key, api_secret, require_credentials

MODE = os.getenv("KELIABOT_MODE", "testnet").strip().lower()
ALLOW_ORDERS = os.getenv("KELIABOT_ALLOW_ORDERS", "false").strip().lower() == "true"

if MODE != "testnet":
    raise RuntimeError(
        "Keliabot only supports Binance Testnet. Set KELIABOT_MODE=testnet; "
        "live trading is intentionally disabled."
    )


def assert_order_submission_enabled():
    """Require an explicit opt-in before submitting any order, even on Testnet."""
    if not ALLOW_ORDERS:
        raise RuntimeError(
            "Order submission is disabled. Set KELIABOT_ALLOW_ORDERS=true "
            "only when intentionally testing with Binance Testnet credentials."
        )


def _credentials():
    require_credentials()
    return api_key, api_secret


def create_spot_client():
    """Create a Spot client pinned to Binance Spot Testnet."""
    key, secret = _credentials()
    client = Client(key, secret, testnet=True)
    client.API_URL = "https://testnet.binance.vision/api"
    return client


def create_futures_client():
    """Create a USD-M Futures client pinned to Binance Futures Testnet."""
    key, secret = _credentials()
    client = Client(key, secret, testnet=True)
    client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"
    return client
