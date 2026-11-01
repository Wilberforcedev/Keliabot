"""Local Streamlit dashboard for offline Keliabot backtests and paper trading.

This app does not connect to Binance or submit exchange orders.
Run from this directory: streamlit run dashboard.py
"""
import csv
import io
from decimal import Decimal
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from backtesting import SMACrossoverBacktester
from paper_trading import PaperTradingAccount

st.set_page_config(page_title="Keliabot", page_icon="📈", layout="wide")

st.markdown(
    """
    <style>
      .block-container {max-width: 1440px; padding-top: 1.4rem; padding-bottom: 2rem;}
      [data-testid="stMetric"] {background:#111827; padding:16px 18px; border-radius:12px;}
      .mode-banner {padding:12px 16px; border-radius:10px; background:#e7f7ef;
        border:1px solid #a7e1c1; color:#14532d; font-weight:700; margin-bottom:16px;}
      .risk-note {padding:12px 14px; border-left:4px solid #f59e0b;
        background:#fff7e6; border-radius:6px; color:#713f12;}
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Keliabot")
st.caption("Offline research and paper trading")

with st.sidebar:
    st.header("Workspace")
    view = st.radio("View", ["Backtests", "Paper Trading", "Trade History"])
    st.divider()
    st.header("Strategy settings")
    symbol = st.text_input("Symbol", value="BTCUSDT").strip().upper() or "BTCUSDT"
    timeframe = st.selectbox("Timeframe", ["1m", "5m", "15m", "1h", "1d"])
    strategy = st.selectbox("Strategy", ["SMA crossover"])
    starting_cash = st.number_input("Starting cash (USDT)", min_value=1.0, value=1000.0, step=100.0)
    fee_rate = st.number_input("Fee rate per side", min_value=0.0, max_value=0.05, value=0.001, step=0.001, format="%.4f")
    risk_allocation = st.slider("Maximum allocation per backtest trade", 5, 100, 95, format="%d%%") / 100
    fast_period = st.number_input("Fast SMA period", min_value=1, max_value=250, value=9, step=1)
    slow_period = st.number_input("Slow SMA period", min_value=2, max_value=500, value=26, step=1)
    if fast_period >= slow_period:
        st.warning("Slow SMA period must be greater than fast SMA period.")

st.markdown('<div class="mode-banner">PAPER / OFFLINE MODE · No Binance connection · No exchange orders</div>', unsafe_allow_html=True)
st.markdown('<div class="risk-note">Backtest and paper-trading results are simulations. They do not predict future performance.</div>', unsafe_allow_html=True)

if "paper_account" not in st.session_state or st.session_state.get("paper_config") != (starting_cash, fee_rate):
    st.session_state.paper_account = PaperTradingAccount(str(starting_cash), str(fee_rate))
    st.session_state.paper_config = (starting_cash, fee_rate)
    st.session_state.paper_mark = 60000.0

def uploaded_rows(upload):
    """Convert an uploaded OHLC CSV into the rows expected by the offline engine."""
    text = upload.getvalue().decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("The CSV needs a header row.")
    columns = {name.strip().lower(): name for name in reader.fieldnames}
    if "open" not in columns or "close" not in columns:
        raise ValueError("The CSV must contain open and close columns.")
    rows = [
        {"open": row[columns["open"]], "close": row[columns["close"]]}
        for row in reader
    ]
    if len(rows) < 3:
        raise ValueError("Upload at least three candle rows.")
    return rows

def record_from_account(account, mark):
    try:
        return account.summary(str(mark))
    except ValueError:
        return None

if view == "Backtests":
    st.subheader("Backtests")
    st.write(f"Run the **{strategy}** strategy for **{symbol} · {timeframe}** using a local candle file.")
    upload = st.file_uploader("Upload OHLC CSV", type=["csv"], help="Include at least open and close columns. The file stays in this browser session.")
    if upload:
        try:
            rows = uploaded_rows(upload)
            if fast_period >= slow_period:
                st.error("Set the slow SMA period above the fast period.")
            elif st.button("Run offline backtest", type="primary"):
                result = SMACrossoverBacktester(
                    starting_cash=str(starting_cash),
                    fee_rate=str(fee_rate),
                    fast_period=int(fast_period),
                    slow_period=int(slow_period),
                    allocation=str(risk_allocation),
                ).run(rows)
                st.session_state.last_backtest = {
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "result": result,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                }
        except (ValueError, UnicodeDecodeError) as error:
            st.error(str(error))

    run = st.session_state.get("last_backtest")
    if run:
        result = run["result"]
        st.caption(f"Latest run: {run['symbol']} · {run['timeframe']} · SMA {int(fast_period)}/{int(slow_period)}")
        a, b, c, d = st.columns(4)
        a.metric("Ending equity", f"{result['ending_equity']:,.2f} USDT")
        b.metric("Net P/L", f"{result['net_pnl']:,.2f} USDT")
        c.metric("Return", f"{result['total_return_pct']:.2f}%")
        d.metric("Max drawdown", f"{result['max_drawdown_pct']:.2f}%")
        curve = pd.DataFrame({"Equity (USDT)": [float(x) for x in result["equity_curve"]]})
        if not curve.empty:
            st.subheader("Equity curve")
            st.line_chart(curve, height=300)
        st.caption(f"Closed trades: {result['closed_trades']} · Win rate: {result['win_rate_pct']:.2f}% · Open quantity: {result['open_position_quantity']}")

elif view == "Paper Trading":
    st.subheader("Paper Trading")
    account = st.session_state.paper_account
    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("#### Simulated position")
        mark = st.number_input("Mark price (USDT)", min_value=0.01, value=float(st.session_state.paper_mark), step=100.0)
        quantity = st.number_input("Quantity (BTC)", min_value=0.000001, value=0.001, step=0.001, format="%.6f")
        buy, sell = st.columns(2)
        if buy.button("Paper buy", type="primary", use_container_width=True):
            try:
                account.execute("buy", str(quantity), str(mark))
                st.session_state.paper_mark = mark
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        if sell.button("Paper sell", use_container_width=True):
            try:
                account.execute("sell", str(quantity), str(mark))
                st.session_state.paper_mark = mark
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        st.caption("These buttons only update the local simulator. They cannot place exchange orders.")
    with right:
        st.markdown("#### Account")
        st.session_state.paper_mark = mark
        summary = record_from_account(account, mark)
        if summary:
            a, b = st.columns(2)
            a.metric("Cash", f"{summary['cash']:,.2f} USDT")
            b.metric("Equity", f"{summary['equity']:,.2f} USDT")
            a.metric(f"{symbol} quantity", f"{summary['asset_quantity']:.6f}")
            b.metric("Market value", f"{summary['market_value']:,.2f} USDT")
        st.button("STOP TESTNET EXECUTION — NOT CONNECTED", disabled=True, use_container_width=True, help="A Testnet execution service and kill-switch are not connected in this version.")

else:
    st.subheader("Trade History")
    account = st.session_state.paper_account
    paper_rows = [
        {
            "Time (UTC)": "Session",
            "Type": "Paper trade",
            "Symbol": symbol,
            "Side": trade.side.upper(),
            "Quantity": float(trade.quantity),
            "Price (USDT)": float(trade.price),
            "Fee (USDT)": float(trade.fee),
            "Net P/L (USDT)": None,
        }
        for trade in account.trades
    ]
    run = st.session_state.get("last_backtest")
    backtest_rows = []
    if run:
        for trade in run["result"]["trades"]:
            backtest_rows.append({
                "Time (UTC)": run["created_at"],
                "Type": "Backtest",
                "Symbol": run["symbol"],
                "Side": "CLOSED",
                "Quantity": float(trade.quantity),
                "Price (USDT)": float(trade.exit_price),
                "Fee (USDT)": float(trade.exit_fee),
                "Net P/L (USDT)": float(trade.net_pnl),
            })
    history = paper_rows + backtest_rows
    if history:
        st.dataframe(pd.DataFrame(history), use_container_width=True, hide_index=True)
    else:
        st.info("No trades recorded in this session yet.")
