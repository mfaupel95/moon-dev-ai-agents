import pandas as pd
import backtesting as bt
import talib
from backtesting import Strategy, DataFeed

# Data Path
DATA_PATH = '/Users/md/Dropbox/dev/github/moon-dev-ai-agents-for-trading/src/data/rbi/BTC-USD-15m.csv'

# Initialize Backtest Object
capital = 1_000_000  # Size requirement

# Load and Clean Data
data = pd.read_csv(DATA_PATH)
data.columns = data.columns.str.strip().str.lower()
data = data.drop(columns=[col for col in data.columns if 'unnamed' in col.lower()])

# Ensure required columns exist and are in correct case
required_columns = ['datetime', 'open', 'high', 'low', 'close', 'volume']
if not all(col in data.columns for col in required_columns):
    raise ValueError("Data must contain: datetime, open, high, low, close, volume")

# Map columns to standard names expected by backtesting.py
# Ensure 'datetime' is the first column
data = data[['datetime'] + [col for col in required_columns[1:] if col in data.columns]]
data.columns = ['datetime'] + [col.capitalize() for col in required_columns[1:]]

# Ensure data is sorted by datetime
data = data.sort_values('datetime').reset_index(drop=True)

# Create DataFeed
df = DataFeed(data['Open'], data['High'], data['Low'], data['Close'], data['Volume'])

# Define Strategy
class MoonDevStrategy(Strategy):
    # Indicators using self.I() wrapper and TA-Lib
    sma_20 = self.I(talib.SMA, self.data.Close, timeperiod=20)
    sma_50 = self.I(talib.SMA, self.data.Close, timeperiod=50)
    rsi = self.I(talib.RSI, self.data.Close, timeperiod=14)

    def next(self):
        # Entry Logic
        if self.position.size == 0:
            if self.data.Close > self.data.Open and self.sma_20 > self.sma_50 and self.rsi > 50:
                # Calculate position size
                equity = self.data.Equity
                position_size = int(round(capital * 0.1 / (self.data.Close - (self.data.Close * 0.01))))  # 10% allocation, 1% risk approx
                self.buy(size=position_size)
        else:
            # Exit Logic (Stop Loss / Take Profit)
            stop_loss = self.data.Close * 0.98
            take_profit = self.data.Close * 1.05
            
            if self.data.Close < stop_loss:
                self.sell()
            elif self.data.Close > take_profit:
                self.sell()
            
            # Exit on crossover
            if self.position:
                if self.sma_20 < self.sma_50:
                    self.sell()

# Run Backtest
bt = bt.Backtest(data, MoonDevStrategy, capital=capital)
stats = bt.run()

# Print Full Stats
print("\n🌙 Moon Dev Backtest Statistics 🌙")
print(stats)
print("\n🌙 Strategy Stats 🌙")
print(stats._strategy)
print("\n✨ Moon Dev Trade Complete ✨")