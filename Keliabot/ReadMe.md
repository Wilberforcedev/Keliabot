# Spot Trading bot summary .
This is for a spot trading robot on binance that trrades BTCUSDT pair on an infinite loop, the bot gets the BUY & SELL signals form the RevisedHFTSwingSignalStrategy alias Puma 100 on trading view. the bot searches for signals from the market based on the stratgy, it handles one order at a time (however it can be adjusted in the code, for it to handle multiple) it places the orders and handles the profit and stops the losss at 1% 
it will wait for 1 minute if it does not find a signal in the market, since it running an infinite loop checking for open positions, it will print positions if they are open but if theres none. it doesnt print. after the positions has closed after hitting the target, th bot will wait for 5 minutes because of the terms and conditions of binance, if the api receives many reqests the account gets banned which i am trying to avoid, as we had talked earlier about me setting it to 60 seconds.

### How to run this bot project in your system?
1. I assume by the time your here, you have received the file and unzipped it and already installed python running.
2. Make sure you have Python installed in your system, and you have set its executeable path. you can download python for mac from here, hover over the link and press command + click to follow it *** https://www.python.org/downloads/ ***
3. Ensure Python is in your environment. Type "***python --version***" in command prompt to check.
4. Now install all the project requirements by typing the following command in your command prompt - "***pip install -r requirements.txt***" this will install  the things you need to run the trading bot.
5. Enjoy the bot.
