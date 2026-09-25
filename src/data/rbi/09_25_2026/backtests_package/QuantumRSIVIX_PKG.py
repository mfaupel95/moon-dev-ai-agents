from backtesting.lib import SMA
self.sma = self.I(backtesting.lib.SMA, self.data.Close, 20)

import talib
self.sma = self.I(talib.SMA, self.data.Close, timeperiod=20)

from backtesting.lib import crossover
if crossover(fast_ma, slow_ma):
    buy()

# Bullish Crossover
if fast_ma[-2] < slow_ma[-2] and fast_ma[-1] > slow_ma[-1]:
    buy()

# Bearish Crossover
if fast_ma[-2] > slow_ma[-2] and fast_ma[-1] < slow_ma[-1]:
    sell()

# Always use self.I() for any indicator logic
self.rrsi = self.I(talib.RSI, self.data.Close, timeperiod=14)