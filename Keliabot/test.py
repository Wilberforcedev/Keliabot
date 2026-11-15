"""Futures strategy script (not the unit-test suite): SMA/base-line/RSI entries.

Orders go to Binance Futures Testnet and stay disabled until
KELIABOT_ALLOW_ORDERS=true. Market data comes from the public production
Futures endpoint because Testnet kline history is too sparse for indicators.

Near-duplicate of ReasonSignal.py. This copy rounds the entry up to Binance's
100 USDT minimum notional before submitting. The offline suite lives in
test_paper_trading.py, test_backtesting.py, test_market_data.py and
test_compare_timeframes.py.
"""
from binance.exceptions import BinanceAPIException, BinanceRequestException
from binance_clients import create_futures_client, create_public_futures_market_client, assert_order_submission_enabled
import ta
import numpy as np
import pandas as pd
from time import sleep
import warnings

# ta/pandas emit downcast warnings that are irrelevant to this strategy.
warnings.filterwarnings("ignore", category=FutureWarning, message="Downcasting object dtype arrays on .fillna, .ffill, .bfill is deprecated")



# Take-profit and stop-loss distance as a fraction of the entry price.
tp = 0.01
sl = 0.01
symbol = 'BTCUSDT'
volume = 10  # USDT notional per entry, multiplied by `leverage` before sizing
leverage = 10
min_notional_value = 100  # Minimum notional value required by Binance
stop_attempts = 3     # Tries at the stop before flattening the position
stop_retry_delay = 2  # Seconds between stop attempts

class TradingBot:
    """Futures order plumbing plus the SMA/base-line/RSI signal check."""

    def __init__(self):
        assert_order_submission_enabled()
        self.client = create_futures_client()                    # Testnet: balances and orders
        self.market_client = create_public_futures_market_client()  # Production: public candles

        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except BinanceAPIException as error:
            print(f"Error changing leverage. status: {error.status_code}, error code: {error.code}, error message: {error.message}")

        # -4046 means the margin type is already set to the requested value.
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
        except BinanceAPIException as error:
            if error.code == -4046:
                print(f"Margin type is already set to ISOLATED for {symbol}.")
            else:
                print(f"Error changing margin type. status: {error.status_code}, error code: {error.code}, error message: {error.message}")

    def get_balance_usdt(self):
        """Return the USDT futures wallet balance, or 0.0 if the call fails."""
        try:
            response = self.client.futures_account_balance()
            for balance in response:
                if balance['asset'] == 'USDT':
                    return float(balance['balance'])
        except BinanceAPIException as error:
            print(f"Binance API error. status: {error.status_code}, error code: {error.code}, error message: {error.message}")
        except BinanceRequestException as error:
            print(f"Binance Request error. error message: {error.message}")
        except Exception as error:
            print(f"An unexpected error occurred: {error}")
        return 0.0

    def get_btc_usdt_price(self):
        """Return the current futures mark price, or 0.0 if the call fails."""
        try:
            price_info = self.client.futures_symbol_ticker(symbol=symbol)
            return float(price_info['price'])
        except BinanceAPIException as error:
            print(f"Binance API Exception: {error}")
        except BinanceRequestException as error:
            print(f"Binance Request Exception: {error}")
        except Exception as error:
            print(f"An unexpected error occurred: {error}")
        return 0.0

    def klines(self, symbol, timeframe, limit=500, startTime=None, endTime=None):
        """Fetch raw futures OHLCV candles; the final row is still forming."""
        try:
            resp = pd.DataFrame(self.market_client.futures_klines(symbol=symbol, interval=timeframe, limit=limit, startTime=startTime, endTime=endTime))
            resp = resp.iloc[:, :6]
            resp.columns = ['Time', 'Open', 'High', 'Low', 'Close', 'Volume']
            resp = resp.set_index('Time')
            resp.index = pd.to_datetime(resp.index, unit='ms')
            resp = resp.astype(float)
            return resp
        except BinanceAPIException as e:
            print(f"Binance API Exception: {e}")
        except BinanceRequestException as e:
            print(f"Binance Request Exception: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

    def get_price_precision(self, symbol):
        """Return decimals allowed by the PRICE_FILTER tick size.

        String-based, so a tick size that Python renders in scientific
        notation (e.g. 1e-05) would be misread.
        """
        try:
            exchange_info = self.client.futures_exchange_info()
            for elem in exchange_info['symbols']:
                if elem['symbol'] == symbol:
                    for filter in elem['filters']:
                        if filter['filterType'] == 'PRICE_FILTER':
                            tick_size = float(filter['tickSize'])
                            price_precision = len(str(tick_size).split('.')[1].rstrip('0'))
                            return price_precision
            print(f"Symbol {symbol} not found.")
            return None
        except BinanceAPIException as e:
            print(f"Binance API Exception: {e}")
        except BinanceRequestException as e:
            print(f"Binance Request Exception: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        return None

    def get_qty_precision(self, symbol):
        """Return decimals allowed by the LOT_SIZE step size (same caveat)."""
        try:
            exchange_info = self.client.futures_exchange_info()
            for elem in exchange_info['symbols']:
                if elem['symbol'] == symbol:
                    for filter in elem['filters']:
                        if filter['filterType'] == 'LOT_SIZE':
                            step_size = float(filter['stepSize'])
                            qty_precision = len(str(step_size).split('.')[1].rstrip('0'))
                            return qty_precision
            print(f"Symbol {symbol} not found.")
            return None
        except BinanceAPIException as e:
            print(f"Binance API Exception: {e}")
        except BinanceRequestException as e:
            print(f"Binance Request Exception: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        return None

    def protect_position(self, symbol, entry_side, quantity, price):
        """Place the reduce-only stop, retrying before flattening the position.

        Returns True when the stop is in place, False when the position was
        flattened instead, and None when flattening also failed.
        """
        stop_price = price - price * sl if entry_side == 'buy' else price + price * sl
        exit_side = 'SELL' if entry_side == 'buy' else 'BUY'

        for attempt in range(1, stop_attempts + 1):
            try:
                # reduceOnly keeps the stop from opening a position in the
                # opposite direction if the position is already closed.
                print(self.client.futures_create_order(symbol=symbol, side=exit_side, type='STOP_MARKET', quantity=quantity, stopPrice=str(stop_price), reduceOnly='true'))
                return True
            except BinanceAPIException as error:
                print(f"Stop attempt {attempt}/{stop_attempts} failed. status: {error.status_code}, error code: {error.code}, error message: {error.message}")
                if attempt < stop_attempts:
                    sleep(stop_retry_delay)

        print(f"No stop after {stop_attempts} attempts; flattening {symbol}.")
        if self.close_position(symbol, entry_side, quantity):
            return False
        return None

    def open_order(self, symbol, side, volume):
        """Market-enter at or above the 100 USDT minimum, then attach a reduce-only stop.

        Entries under `min_notional_value` go out unprotected because Testnet
        rejects the stop. Returns True while a position (protected or not)
        remains open, False when the entry failed or had to be flattened.
        """
        assert_order_submission_enabled()
        price = self.get_btc_usdt_price()
        if price <= 0:
            print("Error: Price fetched is zero or negative.")
            return False

        qty_precision = self.get_qty_precision(symbol)
        price_precision = self.get_price_precision(symbol)

        if qty_precision is None or price_precision is None:
            print("Error: Could not fetch precision values.")
            return False

        # Binance rejects orders below 100 USDT, so round the entry up to it.
        min_quantity = round(min_notional_value / price, qty_precision)
        qty = round((volume * leverage) / price, qty_precision)
        qty = max(qty, min_quantity)

        if qty <= 0:
            print("Error: Calculated quantity is less than or equal to zero.")
            return False

        try:
            if side == 'buy':
                resp1 = self.client.futures_create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)
            elif side == 'sell':
                resp1 = self.client.futures_create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty)
            else:
                return False
            print(resp1)
        except BinanceAPIException as error:
            print(f"Found error. status: {error.status_code}, error code: {error.code}, error message: {error.message}")
            return False

        if (qty * price) < min_notional_value:
            print(f"{symbol}: {qty * price:.2f} USDT notional is under {min_notional_value}; entering without a stop.")
            return True

        outcome = self.protect_position(symbol, side, qty, price)
        if outcome is None:
            print(f"{symbol}: stop failed and flattening failed too; the position may still be open.")
            return True
        return outcome

    def check_positions(self):
        """Return futures positions whose positionAmt is non-zero."""
        try:
            open_positions = self.client.futures_position_information(symbol=symbol)
            return [pos for pos in open_positions if float(pos['positionAmt']) != 0]
        except BinanceAPIException as error:
            print(f"Found error. status: {error.status_code}, error code: {error.code}, error message: {error.message}")
        return []

    def close_position(self, symbol, side, qty):
        """Market-close a position with a reduce-only order.

        Returns True when the flattening order was accepted, False otherwise.
        """
        assert_order_submission_enabled()
        try:
            response = self.client.futures_create_order(
                symbol=symbol,
                side='BUY' if side == 'SELL' else 'SELL',
                type='MARKET',
                quantity=qty,
                reduceOnly='true'
            )
            print(response)
            return True
        except BinanceAPIException as error:
            print(f"Found error. status: {error.status_code}, error code: {error.code}, error message: {error.message}")
            return False

    def check_signal(self, data, equity):
        """Return 'up'/'down' only on the candle where a signal flips on."""
        # The last kline is still forming; signals must only use closed candles.
        data = data.iloc[:-1].copy()
        strategy = RevisedHFTSwingSignalStrategy(data)
        result = strategy.execute_strategy(equity)
        last_row = result.iloc[-1]
        if last_row['long_signal'] and not result['long_signal'].shift(1).iloc[-1]:
            return 'up'
        elif last_row['short_signal'] and not result['short_signal'].shift(1).iloc[-1]:
            return 'down'
        else:
            return 'none'

class RevisedHFTSwingSignalStrategy:
    """SMA/base-line/RSI trend signals with an ATR-derived position size.

    Long: close above fast SMA + ATR buffer, fast SMA above slow SMA, RSI < 70.
    Short: close below fast SMA + ATR buffer, fast SMA below slow SMA, RSI > 30.
    `position_size` is expressed in quote currency; main() trades `volume` instead.
    """

    def __init__(self, data, fast_length=50, slow_length=100, length=14, base_atr_multiplier=1.5, risk_percent=0.01, max_position_size=0.1):
        self.data = data
        self.fast_length = fast_length
        self.slow_length = slow_length
        self.length = length
        self.base_atr_multiplier = base_atr_multiplier
        self.risk_percent = risk_percent
        self.max_position_size = max_position_size

        self.data['fast_ma'] = ta.trend.sma_indicator(self.data['Close'], window=self.fast_length)
        self.data['slow_ma'] = ta.trend.sma_indicator(self.data['Close'], window=self.slow_length)
        self.data['rsi'] = ta.momentum.rsi(self.data['Close'], window=self.length)
        self.data['atr'] = ta.volatility.average_true_range(self.data['High'], self.data['Low'], self.data['Close'], window=self.length)
        self.data['base_line'] = self.data['fast_ma'] + self.base_atr_multiplier * self.data['atr']

    def calculate_position_size(self, equity, stop_loss):
        """Risk-based size capped at max_position_size of equity."""
        if stop_loss == 0:
            return 0  # Avoid division by zero
        return min(equity * self.max_position_size, equity * self.risk_percent / stop_loss)

    def execute_strategy(self, equity):
        self.data['long_signal'] = (self.data['Close'] > self.data['base_line']) & (self.data['fast_ma'] > self.data['slow_ma']) & (self.data['rsi'] < 70)
        self.data['short_signal'] = (self.data['Close'] < self.data['base_line']) & (self.data['fast_ma'] < self.data['slow_ma']) & (self.data['rsi'] > 30)
        self.data['position_size'] = self.data.apply(lambda row: self.calculate_position_size(equity, row['atr']), axis=1)
        return self.data

def main():
    """Poll position state every minute and trade a fresh signal flip."""
    bot = TradingBot()
    symbol = 'BTCUSDT'
    timeframe = '1m'
    # Set once an entry is submitted so the bot waits for an exit before re-entering.
    order = False

    while True:
        try:
            positions = bot.check_positions()

            if len(positions) > 0:
                print(f'Pamela! You have {len(positions)} opened positions')

                # Take profit or stop loss corner. positionAmt is negative for shorts.
                for pos in positions:
                    side = 'SELL' if float(pos['positionAmt']) < 0 else 'BUY'
                    qty = abs(float(pos['positionAmt']))
                    entry_price = float(pos['entryPrice'])
                    current_price = float(bot.client.futures_symbol_ticker(symbol=symbol)['price'])

                    if (side == 'SELL' and current_price <= entry_price * (1 - tp)) or (side == 'BUY' and current_price >= entry_price * (1 + tp)):
                        bot.close_position(symbol, side, qty)
                        print('Profit hit. Closing position and waiting for 5 minutes...')
                        sleep(300)
                    elif (side == 'SELL' and current_price >= entry_price * (1 + sl)) or (side == 'BUY' and current_price <= entry_price * (1 - sl)):
                        bot.close_position(symbol, side, qty)
                        print('Stop loss hit. Closing position and waiting for 5 minutes...')
                        sleep(300)

            if len(positions) == 0 and order:
                print('No open positions. Waiting for 5 minutes...')
                sleep(300)
                order = False

            if not order:
                # Closed candles only; check_signal drops the forming one.
                df = bot.klines(symbol, timeframe, 500)
                signal = bot.check_signal(df, bot.get_balance_usdt())

                if signal == 'up':
                    print('Pamela, Found Buy signal for', symbol)
                    sleep(1)
                    print('Pamela, Placing order for', symbol)
                    order = bot.open_order(symbol, 'buy', volume)
                elif signal == 'down':
                    print('Pamela, Found Sell signal for', symbol)
                    sleep(1)
                    print('Pamela, Placing order for', symbol)
                    order = bot.open_order(symbol, 'sell', volume)
                else:
                    print('Pamela, No trade signal for', symbol)

            print('Waiting 60 seconds...')
            sleep(60)

        except Exception as e:
            print(f"An error occurred: {e}")
            sleep(60)
    

if __name__ == "__main__":
    main()
