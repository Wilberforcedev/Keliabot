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
        
        # Set leverage
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
        except BinanceAPIException as error:
            print(f"Error changing leverage. status: {error.status_code}, error code: {error.code}, error message: {error.message}")
        
        # Set margin type
        try:
            self.client.futures_change_margin_type(symbol=symbol, marginType='ISOLATED')
        except BinanceAPIException as error:
            if error.code == -4046:
                print(f"Pamela Account Margin type is set to ISOLATED for {symbol}.")
            else:
                print(f"Error changing margin type. status: {error.status_code}, error code: {error.code}, error message: {error.message}")

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
        price = self.get_btc_usdt_price()
        if price <= 0:
            print("Error: Price fetched is zero or negative.")
            return

        qty_precision = self.get_qty_precision(symbol)
        price_precision = self.get_price_precision(symbol)

        if qty_precision is None or price_precision is None:
            print("Error: Could not fetch precision values.")
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
                if (qty * price) >= 100:  # Ensure notional value meets the minimum requirement
                    resp2 = self.client.futures_create_order(symbol=symbol, side='SELL', type='STOP_MARKET', quantity=qty, stopPrice=str(price - price * sl))
                    print(resp2)
                print(resp1)
            elif side == 'sell':
                resp1 = self.client.futures_create_order(symbol=symbol, side='SELL', type='MARKET', quantity=qty)
                sl_price = round(price + price * tp, price_precision)
                if (qty * price) >= 100:  # Ensure notional value meets the minimum requirement
                    resp2 = self.client.futures_create_order(symbol=symbol, side='BUY', type='STOP_MARKET', quantity=qty, stopPrice=str(price + price * sl))
                    print(resp2)
                print(resp1)
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
        if stop_loss == 0:
            return 0  # Avoid division by zero
        return min(equity * self.max_position_size, equity * self.risk_percent / stop_loss)

    def execute_strategy(self, equity):
        self.data['long_signal'] = (self.data['Close'] > self.data['base_line']) & (self.data['fast_ma'] > self.data['slow_ma']) & (self.data['rsi'] < 70)
        self.data['short_signal'] = (self.data['Close'] < self.data['base_line']) & (self.data['fast_ma'] < self.data['slow_ma']) & (self.data['rsi'] > 30)
        self.data['position_size'] = self.data.apply(lambda row: self.calculate_position_size(equity, row['atr']), axis=1)
        print(self.data[['Close', 'fast_ma', 'slow_ma', 'rsi', 'atr', 'base_line', 'long_signal', 'short_signal']].tail(10))  # Print last 10 rows for debugging
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
