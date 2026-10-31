"""Run an offline SMA crossover backtest against a local OHLCV CSV file."""
import argparse
from backtesting import SMACrossoverBacktester, load_ohlcv_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", help="CSV file with open and close columns")
    parser.add_argument("--cash", default="1000", help="Starting virtual cash (default: 1000)")
    parser.add_argument("--fee", default="0.001", help="Fee rate per side (default: 0.001)")
    parser.add_argument("--fast", type=int, default=9, help="Fast SMA period")
    parser.add_argument("--slow", type=int, default=26, help="Slow SMA period")
    args = parser.parse_args()

    rows = load_ohlcv_csv(args.csv)
    result = SMACrossoverBacktester(
        starting_cash=args.cash,
        fee_rate=args.fee,
        fast_period=args.fast,
        slow_period=args.slow,
    ).run(rows)

    print("OFFLINE BACKTEST RESULTS (not a forecast)")
    for label, key in [
        ("Starting cash", "starting_cash"),
        ("Ending equity", "ending_equity"),
        ("Net P/L", "net_pnl"),
        ("Return (%)", "total_return_pct"),
        ("Closed trades", "closed_trades"),
        ("Winning trades", "winning_trades"),
        ("Win rate (%)", "win_rate_pct"),
        ("Maximum drawdown (%)", "max_drawdown_pct"),
        ("Open position quantity", "open_position_quantity"),
    ]:
        print(f"{label}: {result[key]}")


if __name__ == "__main__":
    main()
