"""Download public Binance Spot klines to CSV; no API keys or trading permissions needed."""
import argparse
import csv
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_URL = "https://api.binance.com/api/v3/klines"
INTERVALS = {"1m", "5m", "15m"}
LIMIT = 1000
HEADERS = ["open_time", "open", "high", "low", "close", "volume", "close_time"]


def parse_utc(value):
    """Parse ISO date/time; date-only values mean midnight UTC."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Invalid ISO date/time: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.astimezone(timezone.utc).timestamp() * 1000)


def fetch_klines(symbol, interval, start_ms, end_ms, pause=0.2):
    if interval not in INTERVALS:
        raise ValueError(f"Unsupported interval {interval}; choose one of {sorted(INTERVALS)}")
    if not re.fullmatch(r"[A-Za-z0-9]{5,20}", symbol):
        raise ValueError("Symbol must contain 5-20 letters or digits, e.g. BTCUSDT")
    if start_ms >= end_ms:
        raise ValueError("start date must be earlier than end date")

    all_rows = []
    cursor = start_ms
    while cursor < end_ms:
        params = urlencode({
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": LIMIT,
        })
        request = Request(f"{API_URL}?{params}", headers={"User-Agent": "Keliabot-historical-data/1.0"})
        try:
            with urlopen(request, timeout=20) as response:
                batch = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"Binance public market-data request failed: {exc}") from exc
        if isinstance(batch, dict):
            raise RuntimeError(f"Binance returned an API error: {batch.get('msg', batch)}")
        if not batch:
            break
        for candle in batch:
            if len(candle) < 7:
                raise RuntimeError("Unexpected kline response shape")
            if start_ms <= int(candle[0]) < end_ms:
                all_rows.append([
                    int(candle[0]), candle[1], candle[2], candle[3],
                    candle[4], candle[5], int(candle[6])
                ])
        next_cursor = int(batch[-1][0]) + 1
        if next_cursor <= cursor:
            raise RuntimeError("Market-data pagination did not advance")
        cursor = next_cursor
        if len(batch) < LIMIT:
            break
        time.sleep(pause)
    return all_rows


def save_csv(rows, path):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        writer.writerows(rows)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", choices=sorted(INTERVALS), required=True)
    parser.add_argument("--start", type=parse_utc, required=True, help="UTC ISO date/time, e.g. 2026-01-01")
    parser.add_argument("--end", type=parse_utc, required=True, help="Exclusive UTC end date/time")
    parser.add_argument("--output", help="Output CSV path; defaults to data/SYMBOL_INTERVAL.csv")
    args = parser.parse_args()

    rows = fetch_klines(args.symbol, args.interval, args.start, args.end)
    if not rows:
        parser.error("No candles returned for the selected symbol and date range")
    output = args.output or f"data/{args.symbol.upper()}_{args.interval}.csv"
    destination = save_csv(rows, output)
    print(f"Saved {len(rows)} candles to {destination}")
    print("Data source: Binance public Spot market-data endpoint; no account credentials used.")


if __name__ == "__main__":
    main()
