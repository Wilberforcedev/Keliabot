from sys import argv
from binance_clients import create_spot_client, assert_order_submission_enabled
import ta
import numpy as np
import pandas as pd
from time import sleep
from binance.exceptions import BinanceAPIException, BinanceRequestException
import warnings

# Suppress specific FutureWarnings
warnings.filterwarnings("ignore", category=FutureWarning, message="Downcasting object dtype arrays on .fillna, .ffill, .bfill is deprecated")

spot_client = create_spot_client()

tp = 0.01
sl = 0.01
symbol = 'BTCUSDT' 
volume = 0.1
qty = 0.001      #fixed amount for btcusdt  
leverage = 10 


def get_balance_usdt():
    try:
        response = spot_client.get_asset_balance(asset='USDT')
        free_balance = float(response['free'])
        return free_balance
    except BinanceAPIException as error:
        print(
            "Binance API error. status: {}, error code: {}, error message: {}".format(
                error.status_code, error.code, error.message
            )
        )
    except BinanceRequestException as error:
        print(
            "Binance Request error. error message: {}".format(
                error.message
            )
        )
    except Exception as error:
        print("An unexpected error occurred:", str(error))
    return 0.0

balance = get_balance_usdt()
print(f"Pamela Your balance is: {round(balance, 3)} USDT")

def get_btc_usdt_price():
    try:
        price_info = spot_client.get_symbol_ticker(symbol=symbol)
        return float(price_info['price'])
    except BinanceAPIException as error:
        print(f"Binance API Exception: {error}")
    except BinanceRequestException as error:
        print(f"Binance Request Exception: {error}")
    except Exception as error:
        print(f"An unexpected error occurred: {error}")
    return 0.0

price = get_btc_usdt_price()
print(f"BTC/USDT Current price is: {round(price, 3)} USDT")

#  amount in USDT
staking_amount = volume * price / 100  

print(f"Pamela, Your stake is: {round(staking_amount, 3)} USDT")

if balance < staking_amount:
    print("Oooops, The balance is less than the minimum, Top Up.")
else:
    print("Your balance is sufficient, Let's gooo!.")


class TradingBot:
    def __init__(self, api_key, api_secret):
        self.client = spot_client

    def klines(self, symbol, timeframe, limit=500, startTime=None, endTime=None):
        try:
            resp = pd.DataFrame(self.client.get_klines(symbol=symbol, interval=timeframe, limit=limit, startTime=startTime, endTime=endTime))
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
            exchange_info = spot_client.get_exchange_info()
            print(f"Exchange info retrieved for symbol: {symbol}")  # Debugging
            for elem in exchange_info['symbols']:
                if elem['symbol'] == symbol:
                    print(f"Found symbol: {symbol}")  # Debugging line
                    for filter in elem['filters']:
                        if filter['filterType'] == 'PRICE_FILTER':
                            tick_size = float(filter['tickSize'])
                            price_precision = len(str(tick_size).split('.')[1].rstrip('0'))
                            print(f"Price precision for {symbol}: {round(price_precision, 3)}")  # Debugging line
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
            exchange_info = spot_client.get_exchange_info()
            print(f"Exchange info retrieved for symbol: {symbol}")  # Debugging
            for elem in exchange_info['symbols']:
                if elem['symbol'] == symbol:
                    print(f"Found symbol: {symbol}")  # Debugging line
                    for filter in elem['filters']:
                        if filter['filterType'] == 'LOT_SIZE':
                            step_size = float(filter['stepSize'])
                            qty_precision = len(str(step_size).split('.')[1].rstrip('0'))
                            print(f"Quantity precision for {symbol}: {round(qty_precision, 3)}")  # Debugging line
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
        # Keep all legacy Spot order submissions on Testnet and disabled by default.
        assert_order_submission_enabled()
        price = float(self.client.get_symbol_ticker(symbol=symbol)['price'])
        qty_precision = self.get_qty_precision(symbol)
        price_precision = self.get_price_precision(symbol)
        
        if qty_precision is None or price_precision is None:
            print("Error: Precision maths aint happening.")
            return
        
        qty = round(volume / price, qty_precision)
        
        if side == 'buy':
            try:
                resp1 = self.client.order_limit_buy(symbol=symbol, quantity=qty, price=str(price))
                print(symbol, side, "placing order now")
                print(resp1)
                sleep(2)
                sl_price = round(price - price * tp, price_precision)
                resp2 = self.client.order_oco_sell(symbol=symbol, quantity=qty, price=str(sl_price), stopPrice=str(price - price * sl), stopLimitPrice=str(price - price * sl), stopLimitTimeInForce='GTC')
                print(resp2)
            except BinanceAPIException as error:
                print(
                    "Found error. status: {}, error code: {}, error message: {}".format(
                        error.status_code, error.code, error.message
                    )
                )
        if side == 'sell':
            try:
                resp1 = self.client.order_limit_sell(symbol=symbol, quantity=qty, price=str(price))
                print(symbol, side, "placing order now")
                print(resp1)
                sleep(2)
                sl_price = round(price + price * tp, price_precision)
                resp2 = self.client.order_oco_buy(symbol=symbol, quantity=qty, price=str(sl_price), stopPrice=str(price + price * sl), stopLimitPrice=str(price + price * sl), stopLimitTimeInForce='GTC')
                print(resp2)
            except BinanceAPIException as error:
                print(
                    "Found error. status: {}, error code: {}, error message: {}".format(
                        error.status_code, error.code, error.message
                    )
                )

    def check_positions(self):
        try:
            open_orders = self.client.get_open_orders(symbol=symbol)
            return open_orders
        except BinanceAPIException as error:
            print(
                "Found error. status: {}, error code: {}, error message: {}".format(
                    error.status_code, error.code, error.message
                )
            )
        return []

    def close_open_orders(self, symbol):
        try:
            response = self.client.cancel_open_orders(symbol=symbol)
            print(response)
        except BinanceAPIException as error:
            print(
                "Found error. status: {}, error code: {}, error message: {}".format(
                    error.status_code, error.code, error.message
                )
            )

    def close_position(self, symbol, side, qty):
        try:
            response = self.client.order_market(
                symbol=symbol,
                side='BUY' if side == 'SELL' else 'SELL',
                quantity=qty,
            )
            print(response)
        except BinanceAPIException as error:
            print(
                "Found error. status: {}, error code: {}, error message: {}".format(
                    error.status_code, error.code, error.message
                )
            )

    def get_open_position_qty(self, symbol):
        try:
            open_orders = self.client.get_open_orders(symbol=symbol)
            for order in open_orders:
                if float(order['origQty']) != 0:
                    return abs(float(order['origQty']))
        except BinanceAPIException as error:
            print(
                "Found error. status: {}, error code: {}, error message: {}".format(
                    error.status_code, error.code, error.message
                )
            )
        return 0

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
        self.data['dynamic_atr_multiplier'] = self.base_atr_multiplier * self.data['avg_price_level'] / self.data['Close']
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
            
            #  profit  or stop loss  corner
            for pos in positions:
                side = pos['side']
                qty = float(pos['origQty'])
                entry_price = float(pos['price'])
                current_price = float(bot.client.get_symbol_ticker(symbol=symbol)['price'])

                if (side == 'SELL' and current_price <= entry_price * (1 - tp)) or (side == 'BUY' and current_price >= entry_price * (1 + tp)):
                    bot.close_position(symbol, side, qty)
                    print('Profit hit. Closing position and waiting for Just 5 minute...')
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

            df = bot.klines(symbol, timeframe, 500)
            
            #  trading signals
            signal = bot.check_signal(df, balance)
            
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
