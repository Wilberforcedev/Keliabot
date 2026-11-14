"""Legacy Binance Spot strategy: SMA-cross entries with an OCO exit pair.

Orders are submitted to Binance Spot Testnet and stay disabled until
KELIABOT_ALLOW_ORDERS=true. Candles come from the public production
endpoint because Testnet kline history is too sparse for indicators.
"""
from binance_clients import create_spot_client, create_public_market_client, assert_order_submission_enabled
import ta
import numpy as np
import pandas as pd
from decimal import Decimal
from time import monotonic, sleep
from binance.exceptions import BinanceAPIException, BinanceRequestException
import warnings

# ta/pandas emit downcast warnings that are irrelevant to this strategy.
warnings.filterwarnings("ignore", category=FutureWarning, message="Downcasting object dtype arrays on .fillna, .ffill, .bfill is deprecated")

# Take-profit and stop-loss distance as a fraction of the entry price.
tp = 0.01
sl = 0.01
symbol = 'BTCUSDT'
volume = 20.0     # USDT notional per entry
fill_timeout = 30  # Seconds to wait for a limit entry to fill before cancelling
poll_interval = 2  # Seconds between entry fill checks
oco_attempts = 3   # Tries at the exit pair before flattening the position
oco_retry_delay = 2  # Seconds between exit-pair attempts


def get_balance_usdt(client=None):
    """Return the free USDT balance, or 0.0 if the account call fails."""
    client = client or create_spot_client()
    try:
        response = client.get_asset_balance(asset='USDT')
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


class TradingBot:
    def __init__(self):
        self.client = create_spot_client()                  # Testnet: balances and orders
        self.market_client = create_public_market_client()   # Production: public candles

    def klines(self, symbol, timeframe, limit=500, startTime=None, endTime=None):
        """Fetch raw OHLCV candles; the final row is the still-forming candle."""
        try:
            resp = pd.DataFrame(self.market_client.get_klines(symbol=symbol, interval=timeframe, limit=limit, startTime=startTime, endTime=endTime))
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
        """Return decimals allowed by the PRICE_FILTER tick size."""
        try:
            exchange_info = self.client.get_exchange_info()
            for elem in exchange_info['symbols']:
                if elem['symbol'] == symbol:
                    for filter in elem['filters']:
                        if filter['filterType'] == 'PRICE_FILTER':
                            tick_size = Decimal(filter['tickSize'])
                            return -tick_size.normalize().as_tuple().exponent
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
        """Return decimals allowed by the LOT_SIZE step size."""
        try:
            exchange_info = self.client.get_exchange_info()
            for elem in exchange_info['symbols']:
                if elem['symbol'] == symbol:
                    for filter in elem['filters']:
                        if filter['filterType'] == 'LOT_SIZE':
                            step_size = Decimal(filter['stepSize'])
                            return -step_size.normalize().as_tuple().exponent
            print(f"Symbol {symbol} not found.")
            return None
        except BinanceAPIException as e:
            print(f"Binance API Exception: {e}")
        except BinanceRequestException as e:
            print(f"Binance Request Exception: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        return None

    def wait_for_entry_fill(self, symbol, order_id, timeout=fill_timeout, interval=poll_interval):
        """Poll a submitted entry until it fills and return the executed quantity.

        Spot OCO sells need the base asset to be free, so the exit pair can only
        be placed after the entry fills. On timeout the unfilled remainder is
        cancelled and whatever partially filled is returned. Returns None when
        the state could not be confirmed.
        """
        deadline = monotonic() + timeout
        filled_qty = 0.0
        while True:
            try:
                order = self.client.get_order(symbol=symbol, orderId=order_id)
            except BinanceAPIException as error:
                print(
                    "Could not confirm fill. status: {}, error code: {}, error message: {}".format(
                        error.status_code, error.code, error.message
                    )
                )
                return None

            filled_qty = float(order['executedQty'])
            if order['status'] == 'FILLED':
                return filled_qty
            if order['status'] in ('CANCELED', 'REJECTED', 'EXPIRED'):
                return filled_qty
            if monotonic() >= deadline:
                try:
                    self.client.cancel_order(symbol=symbol, orderId=order_id)
                except BinanceAPIException as error:
                    print(
                        "Could not cancel unfilled entry. status: {}, error code: {}, error message: {}".format(
                            error.status_code, error.code, error.message
                        )
                    )
                return filled_qty
            sleep(interval)

    def protect_position(self, symbol, entry_side, quantity, price, price_precision):
        """Attach the OCO exit pair to a filled entry, retrying on rejection.

        Returns True when the pair is in place, False when the position had to
        be flattened, and None when flattening also failed.
        """
        if entry_side == 'buy':
            # Long: take profit above entry, stop below; OCO needs limit > stop.
            take_profit_price = round(price + price * tp, price_precision)
            stop_price = round(price - price * sl, price_precision)
            stop_limit_price = round(price - price * sl, price_precision)
            place_oco = self.client.order_oco_sell
        else:
            # Short: take profit below entry, stop above; OCO needs limit < stop.
            take_profit_price = round(price - price * tp, price_precision)
            stop_price = round(price + price * sl, price_precision)
            stop_limit_price = round(price + price * sl, price_precision)
            place_oco = self.client.order_oco_buy

        for attempt in range(1, oco_attempts + 1):
            try:
                print(place_oco(symbol=symbol, quantity=quantity, price=str(take_profit_price), stopPrice=str(stop_price), stopLimitPrice=str(stop_limit_price), stopLimitTimeInForce='GTC'))
                return True
            except BinanceAPIException as error:
                print(f"OCO attempt {attempt}/{oco_attempts} failed. status: {error.status_code}, error code: {error.code}, error message: {error.message}")
                if attempt < oco_attempts:
                    sleep(oco_retry_delay)

        print(f"No exit pair after {oco_attempts} attempts; flattening {symbol}.")
        if self.close_position(symbol, entry_side, quantity):
            return False
        return None

    def open_order(self, symbol, side, volume):
        """Submit a limit entry, wait for the fill, then attach an OCO pair.

        Returns True while a position (protected or not) remains open, False
        when nothing was left open: an unfilled entry, or a filled entry that
        had to be flattened after the exit pair was rejected.
        """
        assert_order_submission_enabled()
        price = float(self.client.get_symbol_ticker(symbol=symbol)['price'])
        qty_precision = self.get_qty_precision(symbol)
        price_precision = self.get_price_precision(symbol)

        if qty_precision is None or price_precision is None:
            print(f"Error: could not read exchange filters for {symbol}.")
            return False

        qty = round(volume / price, qty_precision)
        if qty <= 0:
            print(f"Error: {volume} USDT at {price} rounds to zero quantity; increase the entry notional.")
            return False

        if side == 'buy':
            try:
                resp1 = self.client.order_limit_buy(symbol=symbol, quantity=qty, price=str(price))
                print(symbol, side, "placing order now")
                print(resp1)
                filled_qty = self.wait_for_entry_fill(symbol, resp1['orderId'])
                if filled_qty is None:
                    return True  # Unconfirmed: assume a position rather than re-enter.
                if filled_qty <= 0:
                    print(f"Entry {resp1['orderId']} did not fill within {fill_timeout}s; no OCO placed.")
                    return False
                outcome = self.protect_position(symbol, side, str(filled_qty), price, price_precision)
                if outcome is None:
                    print(f"{symbol}: exit pair failed and flattening failed too; the position may still be open.")
                    return True
                return outcome
            except BinanceAPIException as error:
                print(
                    "Found error. status: {}, error code: {}, error message: {}".format(
                        error.status_code, error.code, error.message
                    )
                )
                return False
        elif side == 'sell':
            try:
                resp1 = self.client.order_limit_sell(symbol=symbol, quantity=qty, price=str(price))
                print(symbol, side, "placing order now")
                print(resp1)
                filled_qty = self.wait_for_entry_fill(symbol, resp1['orderId'])
                if filled_qty is None:
                    return True  # Unconfirmed: assume a position rather than re-enter.
                if filled_qty <= 0:
                    print(f"Entry {resp1['orderId']} did not fill within {fill_timeout}s; no OCO placed.")
                    return False
                outcome = self.protect_position(symbol, side, str(filled_qty), price, price_precision)
                if outcome is None:
                    print(f"{symbol}: exit pair failed and flattening failed too; the position may still be open.")
                    return True
                return outcome
            except BinanceAPIException as error:
                print(
                    "Found error. status: {}, error code: {}, error message: {}".format(
                        error.status_code, error.code, error.message
                    )
                )
                return False
        return False

    def check_positions(self):
        """Return open orders for the symbol.

        Spot has no position endpoint, so these are orders, not fills: an
        unfilled entry and both OCO legs still appear here.
        """
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

    def close_position(self, symbol, side, qty):
        """Market-close the position; Spot can only sell the balance held.

        Returns True when the market order was accepted.
        """
        assert_order_submission_enabled()
        try:
            response = self.client.order_market(
                symbol=symbol,
                side='BUY' if side == 'SELL' else 'SELL',
                quantity=qty,
            )
            print(response)
            return True
        except BinanceAPIException as error:
            print(
                "Found error. status: {}, error code: {}, error message: {}".format(
                    error.status_code, error.code, error.message
                )
            )
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
    """SMA-cross trend filter with an ATR-derived position size.

    Long signal: fast SMA above slow SMA and price above the fast SMA.
    Short signal: fast SMA below slow SMA and price below the fast SMA.
    `position_size` is expressed in quote currency (equity scaled by ATR).
    main() does not use it; the entry path trades a fixed `volume` instead.
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
        # Scale the ATR stop distance inversely with price so old and new candles
        # are measured on comparable volatility.
        self.data['avg_price_level'] = ta.trend.sma_indicator(self.data['Close'], window=30)
        self.data['dynamic_atr_multiplier'] = self.base_atr_multiplier * self.data['avg_price_level'] / self.data['Close']
        self.data['long_signal'] = np.where((self.data['fast_ma'] > self.data['slow_ma']) & (self.data['Close'] > self.data['fast_ma']), 1, 0)
        self.data['short_signal'] = np.where((self.data['fast_ma'] < self.data['slow_ma']) & (self.data['Close'] < self.data['fast_ma']), 1, 0)

    def execute_strategy(self, equity):
        # Risk-scaled size, capped at max_position_size of the equity.
        self.data['position_size'] = (self.risk_percent * equity) / (self.data['atr'] * self.data['dynamic_atr_multiplier'])
        self.data['position_size'] = np.where(self.data['position_size'] > self.max_position_size, self.max_position_size, self.data['position_size'])
        return self.data

def main():
    """Poll order state every minute and trade a fresh SMA-cross entry."""
    bot = TradingBot()
    symbol = 'BTCUSDT'
    timeframe = '1m'
    # Set once an entry is submitted so the bot waits for an exit before re-entering.
    order = False

    while True:
        try:
            # Open orders include the entry and both OCO legs. Spot has no
            # position endpoint, so this loop approximates exits from them.
            positions = bot.check_positions()

            if len(positions) > 0:
                print(f'Pamela! You have {len(positions)} opened positions')

                # Take profit or stop loss corner.
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
                # Closed candles only; check_signal drops the forming one.
                df = bot.klines(symbol, timeframe, 500)

                # Trading signals. Signal must flip on this candle to act, so
                # a persistent state does not re-enter every loop.
                signal = bot.check_signal(df, get_balance_usdt(bot.client))

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
