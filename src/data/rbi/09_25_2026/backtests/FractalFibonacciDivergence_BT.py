import backtesting as bt
import talib
import pandas_ta as ta
import pandas as pd
import numpy as np

# Set Moon Dev's backtest engine
strategy_name = "FractalFibonacciDivergence"

# Load Data
data_path = r'O:\Werkstatt\Repos\moon-dev-ai-agents\src\data\rbi\BTC-USD-15m.csv'
data = pd.read_csv(data_path)

# Critical Data Handling
data.columns = data.columns.str.strip().str.lower()
data = data.drop(columns=[col for col in data.columns if 'unnamed' in col.lower()])
data = data[['open', 'high', 'low', 'close', 'volume']]
data = data.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})

# Moon Dev: Pre-processing for clean data
data = data.dropna()
data = data.set_index('datetime')

class FractalFibonacciDivergence(bt.Strategy):
    params = (
        ('fib_level', 0.618),
        ('fib_tolerance', 0.001),
        ('trend_ema', 200),
        ('position_size', 1000000),
        ('risk_pct', 0.01),
    )

    def __init__(self):
        self.order = None
        self.entry_price = 0
        self.entry_date = None
        self.swing_high = 0
        self.swing_low = 0
        self.current_fib_level = 0
        self.trend_direction = 0
        
        # Initialize indicators
        self.data = bt.indicators.SeriesIndicator(data.Close)
        self.ema = bt.indicators.EMA(self.data, period=self.params.trend_ema)
        
        # Calculate Fractals using TALIB
        self.high = bt.indicators.SeriesIndicator(data.High)
        self.low = bt.indicators.SeriesIndicator(data.Low)
        self.fractal_high = talib.FR(self.high, length=5)
        self.fractal_low = talib.FR(self.low, length=5)
        
        # Calculate Swing Highs/Lows
        self.swing_highs = talib.MAX(self.high, timeperiod=50)
        self.swing_lows = talib.MIN(self.low, timeperiod=50)
        
        # Calculate Fibonacci Retracement Levels
        self.fib_0_382 = ta.fibonacci(self.swing_lows, self.swing_highs, level=0.382)
        self.fib_0_618 = ta.fibonacci(self.swing_lows, self.swing_highs, level=0.618)
        self.fib_0_786 = ta.fibonacci(self.swing_lows, self.swing_highs, level=0.786)
        self.fib_1_272 = ta.fibonacci(self.swing_highs, self.swing_lows, level=1.272)
        self.fib_1_618 = ta.fibonacci(self.swing_highs, self.swing_lows, level=1.618)
        
        # Volume Confirmation
        self.volume = bt.indicators.SeriesIndicator(data.Volume)
        self.volume_ma = ta.SMA(self.volume, 20)

    def next(self):
        # Check if we already have an open order
        if self.order:
            if self.order.isclosed:
                self.order = None
            else:
                # Check for invalidation (stop loss or take profit)
                current_price = self.data[0]
                
                # Determine current trend direction
                if self.ema[0] > 0:
                    self.trend_direction = 1  # Bullish
                else:
                    self.trend_direction = -1  # Bearish
                
                # Check Stop Loss / Take Profit
                if self.trend_direction == 1:
                    # Long Position: Stop below fractal low, TP at 1.272 or 1.618
                    if current_price < self.entry_price * (1 - self.params.risk_pct):
                        self.log("🌙 STOP LOSS HIT! Fractal pattern invalidated.")
                        self.close()
                    elif current_price >= self.entry_price * (1 + self.params.risk_pct):
                        self.log("🚀 TAKE PROFIT HIT! Fractal momentum confirmed.")
                        self.close()
                else:
                    # Short Position: Stop above fractal high, TP at -1.272 or -1.618
                    if current_price > self.entry_price * (1 + self.params.risk_pct):
                        self.log("🌙 STOP LOSS HIT! Fractal pattern invalidated.")
                        self.close()
                    elif current_price <= self.entry_price * (1 - self.params.risk_pct):
                        self.log("🚀 TAKE PROFIT HIT! Fractal momentum confirmed.")
                        self.close()
            return

        # Determine Trend Direction
        if self.ema[0] > 0:
            self.trend_direction = 1
        else:
            self.trend_direction = -1

        # --- BULLISH ENTRY LOGIC ---
        if self.trend_direction == 1:
            # 1. Check for Bullish Fractal (High > Next 2 Highs, Low < Prev 2 Lows)
            if self.fractal_high[0] == 1:
                # 2. Check if Price touches or breaks slightly above 0.618 Fib level
                current_price = self.data[0]
                fib_618 = self.fib_0_618[0]
                
                # Check if price is at or above 0.618 level (with tolerance)
                if current_price >= fib_618 * (1 - self.params.fib_tolerance):
                    # 3. Check Volume Confirmation (Volume > MA)
                    if self.volume[0] > self.volume_ma[0]:
                        # Confirm Fractal is complete (5 candles passed)
                        if self.data.index[0] - self.data.index[0 - 4] > 4:
                            # Calculate Position Size (Fixed risk or Fixed size as per prompt requirement)
                            # Prompt says size should be 1,000,000, but also mentions risk management.
                            # We will use the fixed size of 1,000,000 for this trade.
                            position_size = int(round(self.params.position_size))
                            
                            self.log(f"🌙 BULLISH SIGNAL: Fractal at 0.618 Fib! Entry Price: {current_price:.2f}")
                            
                            # Determine Stop Loss (Below Fractal Low)
                            fractal_low = self.fractal_low[0]
                            stop_loss = fractal_low * (1 - self.params.risk_pct) # 1% risk buffer below low
                            
                            self.buy(size=position_size, duration=1)
                            self.entry_price = current_price
                            self.entry_date = self.data.index[0]
                            self.swing_high = self.data.index[0]
                            
        # --- BEARISH ENTRY LOGIC ---
        elif self.trend_direction == -1:
            # 1. Check for Bearish Fractal (Low < Next 2 Lows, High > Prev 2 Highs)
            if self.fractal_low[0] == 1:
                # 2. Check if Price touches or breaks slightly below 0.618 Fib level
                current_price = self.data[0]
                fib_618 = self.fib_0_618[0]
                
                # Check if price is at or below 0.618 level (with tolerance)
                if current_price <= fib_618 * (1 + self.params.fib_tolerance):
                    # 3. Check Volume Confirmation (Volume > MA)
                    if self.volume[0] > self.volume_ma[0]:
                        # Confirm Fractal is complete (5 candles passed)
                        if self.data.index[0] - self.data.index[0 - 4] > 4:
                            # Calculate Position Size
                            position_size = int(round(self.params.position_size))
                            
                            self.log(f"🌙 BEARISH SIGNAL: Fractal at 0.618 Fib! Entry Price: {current_price:.2f}")
                            
                            # Determine Stop Loss (Above Fractal High)
                            fractal_high = self.fractal_high[0]
                            stop_loss = fractal_high * (1 + self.params.risk_pct) # 1% risk buffer above high
                            
                            self.sell(size=position_size, duration=1)
                            self.entry_price = current_price
                            self.entry_date = self.data.index[0]
                            self.swing_low = self.data.index[0]
                            
    def on_stop(self):
        # Called when stop loss is triggered
        self.log(f"🌙 Stop Loss triggered on {self.order.side}.")
        
    def on_enter(self):
        # Called when entry is triggered
        self.log(f"✨ Entry confirmed at {self.order.side} price: {self.data[0]:.2f}")
        
    def on_exit(self):
        # Called when exit is triggered
        self.log(f"🚀 Exit confirmed at {self.order.side} price: {self.data[0]:.2f}")

# Run Backtest
bt.backtest(
    data=data,
    strategy=FractalFibonacciDivergence,
    cash=1000000,  # Initial equity
    commission=0.001,
    slippage=0.0005,
    initial_date='2023-01-01',
    end_date='2023-12-31',
    cash_curve=True,
    equity_curve=True,
    logger='moon_dev_logger',
)

# Print Full Stats
stats = bt.backtest(
    data=data,
    strategy=FractalFibonacciDivergence,
    cash=1000000,
    commission=0.001,
    slippage=0.0005,
    initial_date='2023-01-01',
    end_date='2023-12-31',
    cash_curve=True,
    equity_curve=True,
    logger='moon_dev_logger',
)

print("🌙 MOON DEV BACKTEST RESULTS")
print("=" * 50)
print(stats)
print("=" * 50)
print(f"📊 Final Equity: ${stats.finance('Final Equity', 'cash')}")
print(f"📈 Total Return: {stats.finance('Total Return', 'percent'):.2f}%")
print(f"📉 Best Day: {stats.finance('Best Day', 'date')}")
print(f"📉 Worst Day: {stats.finance('Worst Day', 'date')}")
print(f"💰 Total Trades: {stats.trades}")
print(f"🏆 Win Rate: {stats.wins / stats.trades * 100:.2f}%")
print(f"💸 Max Drawdown: ${stats.max_drawdown}")
print("✨ Backtest complete! 🚀")