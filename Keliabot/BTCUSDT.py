from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceRequestException
import ta
import numpy as np
import pandas as pd
from time import sleep
import warnings

# Suppress specific FutureWarnings
warnings.filterwarnings("ignore", category=FutureWarning, message="Downcasting object dtype arrays on .fillna, .ffill, .bfill is deprecated")

from keys import api_key, api_secret
# Initialize the Binance Futures Client for the Testnet
spot_client = Client(api_key, api_secret, testnet=True)

# Set the testnet URL for futures
spot_client.API_URL = 'https://testnet.binancefuture.com/fapi/v1/'

tp = 0.01
sl = 0.01
symbol = 'BTCUSDT'
volume = 10  # Adjust this volume based on your account balance and desired position size
leverage = 10

class TradingBot:
    def __init__(self, api_key, api_secret):
        self.client = Client(api_key, api_secret, testnet=True)
        self.client.API_URL = 'https://testnet.binancefuture.com/fapi/v1/'
        self.client.futures_change_leverage(symbol=symbol, leverage=leverage)

    def get_balance_usdt(self):
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
        try:
            resp = pd.DataFrame(self.client.futures_klines(symbol=symbol, interval=timeframe, limit=limit, startTime=startTime, endTime=endTime))
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
        price = float(self.client.futures_symbol_ticker(symbol=symbol)['price'])
        qty_precision = self.get_qty_precision(symbol)
        price_precision = self.get_price_precision(symbol)

        if qty_precision is None or price_precision is None:
            print("Error: Precision maths aint happening.")
            return

        qty = round((volume * leverage) / price, qty_precision)
        print(f"Calculated quantity: {qty}")  # Debugging statement

        if qty <= 0:
            print("Error: Calculated quantity is less than or equal to zero.")
            return

        try:
            if side == 'buy':
                resp1 = self.client.futures_create_order(symbol=symbol, side='BUY', type='MARKET', quantity=qty)
                sl_price = round(price - price * tp, price_precision)
                resp2 = self.client.futures_create_order(symbol=symbol, side='SELL', type='STOP_MARKET', quantity=qty, stopPrice=str(price - price * sl))
                print(resp1)
                print(resp2)
            elif side == 'sell':
                resp1 = self.client.futures_create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty)
                sl_price = round(price + price * tp, price_precision)
                resp2 = self.client.futures_create_order(symbol=symbol, side='BUY', type='STOP_MARKET', quantity=qty, stopPrice=str(price + price * sl))
                print(resp1)
                print(resp2)
        except BinanceAPIException as error:
            print(f"Found error. status: {error.status_code}, error code: {error.code}, error message: {error.message}")

    def check_positions(self):
        try:
            open_positions = self.client.futures_position_information(symbol=symbol)
            return [pos for pos in open_positions if float(pos['positionAmt']) != 0]
        except BinanceAPIException as error:
            print(f"Found error. status: {error.status_code}, error code: {error.code}, error message: {error.message}")
        return []

    def close_position(self, symbol, side, qty):
        try:
            response = self.client.futures_create_order(
                symbol=symbol,
                side='BUY' if side == 'SELL' else 'SELL',
                type='MARKET',
                quantity=qty
            )
            print(response)
        except BinanceAPIException as error:
            print(f"Found error. status: {error.status_code}, error code: {error.code}, error message: {error.message}")

    def check_signal(self, data, equity):
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
        self.data['avg_price_level'] = ta.trend.sma_indicator(self.data['Close'], window=30)
        self.data['dynamic_atr_multiplier'] = self.base_atr_multiplier * self.data['avg_price_level'] / self.data['avg_price_level'].shift(self.length)
        self.data['long_signal'] = np.where((self.data['fast_ma'] > self.data['slow_ma']) & (self.data['Close'] > self.data['fast_ma']), 1, 0)
        self.data['short_signal'] = np.where((self.data['fast_ma'] < self.data['slow_ma']) & (self.data['Close'] < self.data['fast_ma']), 1, 0)

    def execute_strategy(self, equity):
        self.data['position_size'] = (self.risk_percent * equity) / (self.data['atr'] * self.data['dynamic_atr_multiplier'])
        self.data['position_size'] = np.where(self.data['position_size'] > self.max_position_size, self.max_position_size, self.data['position_size'])
        return self.data

bot = TradingBot(api_key, api_secret)
symbol = 'BTCUSDT'
timeframe = '1m'
order = False

while True:
    try:
        positions = bot.check_positions()

        if len(positions) > 0:
            print(f'Pamela! You have {len(positions)} opened positions')

            # Profit or stop loss corner
            for pos in positions:
                side = 'SELL' if float(pos['positionAmt']) < 0 else 'BUY'
                qty = abs(float(pos['positionAmt']))
                entry_price = float(pos['entryPrice'])
                current_price = float(bot.client.futures_symbol_ticker(symbol=symbol)['price'])

                if (side == 'SELL' and current_price >= entry_price * (1 + tp)) or (side == 'BUY' and current_price <= entry_price * (1 - tp)):
                    bot.close_position(symbol, side, qty)
                    print('Profit hit. Closing position and waiting for 5 minutes...')
                    sleep(300)
                elif (side == 'SELL' and current_price <= entry_price * (1 - sl)) or (side == 'BUY' and current_price >= entry_price * (1 + sl)):
                    bot.close_position(symbol, side, qty)
                    print('Stop loss hit. Closing position and waiting for 5 minutes...')
                    sleep(300)

        if len(positions) == 0 and order:
            print('No open positions. Waiting for 5 minutes...')
            sleep(300)
            order = False

        if not order:
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
