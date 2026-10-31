"""Centralized Binance credentials loaded from environment variables."""
import os
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("BINANCE_API_KEY", "")
api_secret = os.getenv("BINANCE_API_SECRET", "")


def require_credentials():
    if not api_key or not api_secret:
        raise RuntimeError(
            "Binance credentials are missing. Set BINANCE_API_KEY and "
            "BINANCE_API_SECRET in your environment."
        )
