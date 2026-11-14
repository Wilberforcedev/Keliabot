"""Futures variant of the Keliabot strategy: SMA-cross entries.

Orders go to Binance Futures Testnet and stay disabled until
KELIABOT_ALLOW_ORDERS=true. Market data comes from the public production
Futures endpoint because Testnet kline history is too sparse for indicators.

Near-duplicate of ReasonSignal.py (which adds an RSI filter and a 100 USDT
minimum-notional guard on the stop order). Kept as its own runnable script.
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

class TradingBot:
    """Futures order plumbing plus the SMA-cross signal check."""

    def __init__(self):
        assert_order_submission_enabled()
        self.client = create_futures_client()                    # Testnet: balances and orders
        self.market_client = create_public_futures_market_client()  # Production: public candles
        self.client.futures_change_leverage(symbol=symbol, leverage=leverage)

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

    def open_order(self, symbol, side, volume):
        """Market-enter, then attach a reduce-only stop-loss order."""
        assert_order_submission_enabled()
        price = float(self.client.futures_symbol_ticker(symbol=symbol)['price'])
        qty_precision = self.get_qty_precision(symbol)
        price_precision = self.get_price_precision(symbol)

        if qty_precision is None or price_precision is None:
            print("Error: Precision maths aint happening.")
            return

        qty = round((volume * leverage) / price, qty_precision)

        if qty <= 0:
            print("Error: Calculated quantity is less than or equal to zero.")
            return

        try:
            if side == 'buy':
                resp1 = self.client.futures_create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)
                # reduceOnly keeps the stop from opening a short if the
                # position is already closed.
                resp2 = self.client.futures_create_order(symbol=symbol, side='SELL', type='STOP_MARKET', quantity=qty, stopPrice=str(price - price * sl), reduceOnly='true')
                print(resp1)
                print(resp2)
            elif side == 'sell':
                resp1 = self.client.futures_create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty)
                resp2 = self.client.futures_create_order(symbol=symbol, side='BUY', type='STOP_MARKET', quantity=qty, stopPrice=str(price + price * sl), reduceOnly='true')
                print(resp1)
                print(resp2)
        except BinanceAPIException as error:
            print(f"Found error. status: {error.status_code}, error code: {error.code}, error message: {error.message}")

    def check_positions(self):
        """Return futures positions whose positionAmt is non-zero."""
        try:
            open_positions = self.client.futures_position_information(symbol=symbol)
            return [pos for pos in open_positions if float(pos['positionAmt']) != 0]
        except BinanceAPIException as error:
            print(f"Found error. status: {error.status_code}, error code: {error.code}, error message: {error.message}")
        return []

    def close_position(self, symbol, side, qty):
        """Market-close a position with a reduce-only order."""
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
        except BinanceAPIException as error:
            print(f"Found error. status: {error.status_code}, error code: {error.code}, error message: {error.message}")

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
    """SMA-cross trend filter with an ATR-derived position size.

    Long signal: fast SMA above slow SMA and price above the fast SMA.
    Short signal: fast SMA below slow SMA and price below the fast SMA.
    `position_size` is expressed in quote currency; main() trades `volume` instead.
    """

    def __init__(self, data, length=14, base_atr_multiplier=0.10, risk_percent=0.75, max_position_size=0.25, fast_length=9, slow_length=26):
        self.data = data
        self.length = length
        self.base_atr_multiplier = base_atr_multiplier
        self.risk_percent = risk_percent
        self.max_position_size = max_position_size
        self.fast_length = fast_length
        self.slow_length = slow_length
        self.data['fast_ma'] = ta.trend.sma_indicator(self.data['Close'], window=self.fast_length)
        self.data['slow_ma'] = ta.trend.sma_indicator(self.data['Close'], window=self.slow_length)
        self.data['atr'] = ta.volatility.average_true_range(self.data['High'], self.data['Low'], self.data['Close'], window=self.length)
        # Scale the ATR stop distance by how far price has moved from its
        # 30-candle average relative to that average `length` candles ago.
        self.data['avg_price_level'] = ta.trend.sma_indicator(self.data['Close'], window=30)
        self.data['dynamic_atr_multiplier'] = self.base_atr_multiplier * self.data['avg_price_level'] / self.data['avg_price_level'].shift(self.length)
        self.data['long_signal'] = np.where((self.data['fast_ma'] > self.data['slow_ma']) & (self.data['Close'] > self.data['fast_ma']), 1, 0)
        self.data['short_signal'] = np.where((self.data['fast_ma'] < self.data['slow_ma']) & (self.data['Close'] < self.data['fast_ma']), 1, 0)

    def execute_strategy(self, equity):
        # Risk-scaled size, capped at max_position_size of the equity.
        self.data['position_size'] = (self.risk_percent * equity) / (self.data['atr'] * self.data['dynamic_atr_multiplier'])
        self.data['position_size'] = np.where(self.data['position_size'] > self.max_position_size, self.max_position_size, self.data['position_size'])
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
                    bot.open_order(symbol, 'buy', volume)
                    order = True
                elif signal == 'down':
                    print('Pamela, Found Sell signal for', symbol)
                    sleep(1)
                    print('Pamela, Placing order for', symbol)
                    bot.open_order(symbol, 'sell', volume)
                    order = True
                else:
                    print('Pamela, No trade signal for', symbol)

            print('Waiting 60 seconds...')
            sleep(60)

        except Exception as e:
            print(f"An error occurred: {e}")
            sleep(60)
    

if __name__ == "__main__":
    main()
