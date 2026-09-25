import backtesting as bt
import pandas_ta as ta
import talib
import pandas as pd
import numpy as np

# Load data
data_path = r'O:\Werkstatt\Repos\moon-dev-ai-agents\src\data\rbi\BTC-USD-15m.csv'
df = pd.read_csv(data_path)

# Clean column names
df.columns = df.columns.str.strip().str.lower()
df = df.drop(columns=[col for col in df.columns if 'unnamed' in col.lower()])

# Ensure proper mapping and rename to backtesting standard
df = df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'})

# Create backtest object
keltner_breakout_strategy = bt.Strategy(
    data=df,
    cash=1000000.0,  # Starting capital
    commission=0.001,
    slippage=0.0005,
    commission_rate=0.001,
    slippage_pct=0.0005,
    map_params={'keltner_period': 20, 'keltner_atr': 2, 'bollinger_period': 20, 'bollinger_std': 2, 'divergence_period': 14},
    params={'keltner_period': 20, 'keltner_atr': 2, 'bollinger_period': 20, 'bollinger_std': 2, 'divergence_period': 14},
    period=1
)

def check_bullish_divergence_talib(data, period=20):
    """
    Identifies bullish divergence by comparing price lows with indicator lows.
    Uses talib for RSI calculation to avoid backtesting.lib dependencies.
    Returns True if a new low is lower than previous, but indicator low is higher.
    """
    # Calculate RSI using talib
    rsi = keltner_breakout_strategy.I(talib.RSI, keltner_breakout_strategy.data.Close, timeperiod=period)
    
    # Find local minima for price and RSI using talib
    price_low = keltner_breakout_strategy.I(talib.MIN, keltner_breakout_strategy.data.Low, timeperiod=period)
    rsi_low = keltner_breakout_strategy.I(talib.MIN, rsi, timeperiod=period)
    
    # We look for a pattern where price makes a lower low, but RSI makes a higher low
    # This requires checking the last 3 candles to establish a trend down and then the divergence
    if len(keltner_breakout_strategy.data) < 3:
        return False
    
    # Check current candle vs previous 2 candles using array indexing
    current_price_low = keltner_breakout_strategy.data.Low.iloc[-1]
    current_rsi = rsi.iloc[-1]
    
    prev1_price_low = keltner_breakout_strategy.data.Low.iloc[-2]
    prev1_rsi = rsi.iloc[-2]
    
    prev2_price_low = keltner_breakout_strategy.data.Low.iloc[-3]
    prev2_rsi = rsi.iloc[-3]
    
    # Condition: Price made a new low (lower than prev1), but RSI made a higher low (higher than prev1)
    if current_price_low < prev1_price_low and current_rsi > prev1_rsi:
        return True
    
    return False

def check_volatility_expansion_talib(bollinger_upper, bollinger_lower):
    """
    Checks if Bollinger Bands are expanding (widening).
    We compare the band width of the current period vs the previous period.
    """
    if len(keltner_breakout_strategy.data) < 2:
        return False
    
    current_width = bollinger_upper.iloc[-1] - bollinger_lower.iloc[-1]
    prev_width = bollinger_upper.iloc[-2] - bollinger_lower.iloc[-2]
    
    return current_width > prev_width

def divergence_logic_talib():
    # Check if we are currently in a bullish divergence state
    return check_bullish_divergence_talib(keltner_breakout_strategy.data)

# Initialize indicators using talib and pandas_ta
# Keltner Channel
kc_atr = keltner_breakout_strategy.I(talib.ATR, keltner_breakout_strategy.data.Close, timeperiod=20, multiplier=2)
kc_sma = keltner_breakout_strategy.I(talib.SMA, keltner_breakout_strategy.data.Close, timeperiod=20)
kc_upper = keltner_breakout_strategy.I(lambda x, y, z: x + (y * z), kc_sma, kc_atr, timeperiod=1)
kc_lower = keltner_breakout_strategy.I(lambda x, y, z: x - (y * z), kc_sma, kc_atr, timeperiod=1)
kc_middle = kc_sma

# Bollinger Bands
bb_atr = keltner_breakout_strategy.I(talib.ATR, keltner_breakout_strategy.data.Close, timeperiod=20, multiplier=2)
bb_sma = keltner_breakout_strategy.I(talib.SMA, keltner_breakout_strategy.data.Close, timeperiod=20)
bb_upper = keltner_breakout_strategy.I(lambda x, y, z: x + (y * z), bb_sma, bb_atr, timeperiod=1)
bb_lower = keltner_breakout_strategy.I(lambda x, y, z: x - (y * z), bb_sma, bb_atr, timeperiod=1)

# RSI for divergence check
rsi = keltner_breakout_strategy.I(talib.RSI, keltner_breakout_strategy.data.Close, timeperiod=14)

def divergence_check_talib():
    # Simple bullish divergence: Price makes lower low, RSI makes higher low
    if len(keltner_breakout_strategy.data) < 4:
        return False
    current_price_low = keltner_breakout_strategy.data.Low.iloc[-1]
    current_rsi = rsi.iloc[-1]
    
    prev1_price_low = keltner_breakout_strategy.data.Low.iloc[-2]
    prev1_rsi = rsi.iloc[-2]
    
    prev2_price_low = keltner_breakout_strategy.data.Low.iloc[-3]
    prev2_rsi = rsi.iloc[-3]
    
    # Price low condition: current < prev1
    if current_price_low >= prev1_price_low:
        return False
    
    # RSI high low condition: current > prev1
    if current_rsi <= prev1_rsi:
        return False
        
    return True

# Entry Logic
def run_strategy_talib():
    # Condition A: Volatility Expansion
    current_bb_width = bb_upper - bb_lower
    prev_bb_width = bb_upper.shift(1) - bb_lower.shift(1)
    volatility_expanded = current_bb_width > prev_bb_width
    
    # Condition B: Bullish Divergence
    bullish_div = divergence_check_talib()
    
    # Trigger: Price closes above Keltner Upper
    break_out = keltner_breakout_strategy.data.Close > kc_upper
    
    # Enter Long if all conditions met
    if break_out and bullish_div and volatility_expanded:
        # Calculate risk
        # Stop loss at Keltner Lower or fixed % below entry
        entry_price = keltner_breakout_strategy.data.Close
        stop_loss_price = kc_lower
        
        # FIX: Convert fixed capital to a percentage of equity (fraction) as per requirement
        # Using 1% of equity per trade as a standard risk management rule for breakouts
        position_size = 0.01  # 1% of equity (fraction)
        
        # Ensure it's a valid fraction between 0 and 1
        if not (0 < position_size < 1):
            raise ValueError("Position size must be a fraction between 0 and 1 for equity sizing")
            
        self.buy(size=position_size, comment="Moon Dev 🌙 Breakout Entry", order_type=bt.Order.Limit)

# Exit Logic
def run_exit_talib():
    if self.position:
        # Exit if price closes below Keltner Middle (Middle line) or Upper line
        # Using Middle line for primary exit as per strategy description
        if keltner_breakout_strategy.data.Close < kc_middle:
            self.sell(comment="Moon Dev 🌙 Trend Failure Exit")
            
        # Trailing Stop: Move stop loss to Keltner Lower
        # In backtesting, we can't easily move stop loss dynamically on every tick without complex logic
        # Simplified: Just sell if price drops below lower band
        if keltner_breakout_strategy.data.Close < kc_lower:
            self.sell(comment="Moon Dev 🌙 Trailing Stop Hit")

# Re-run with corrected structure
keltner_breakout_strategy = bt.Strategy(
    data=df,
    cash=1000000.0,
    commission=0.001,
    slippage=0.0005,
    commission_rate=0.001,
    slippage_pct=0.0005,
    map_params={'keltner_period': 20, 'keltner_atr': 2, 'bollinger_period': 20, 'bollinger_std': 2, 'divergence_period': 14},
    params={'keltner_period': 20, 'keltner_atr': 2, 'bollinger_period': 20, 'bollinger_std': 2, 'divergence_period': 14},
    period=1
)

kc_atr = keltner_breakout_strategy.I(talib.ATR, keltner_breakout_strategy.data.Close, timeperiod=20, multiplier=2)
kc_sma = keltner_breakout_strategy.I(talib.SMA, keltner_breakout_strategy.data.Close, timeperiod=20)
kc_upper = keltner_breakout_strategy.I(lambda x, y, z: x + (y * z), kc_sma, kc_atr, timeperiod=1)
kc_lower = keltner_breakout_strategy.I(lambda x, y, z: x - (y * z), kc_sma, kc_atr, timeperiod=1)
kc_middle = kc_sma

bb_atr = keltner_breakout_strategy.I(talib.ATR, keltner_breakout_strategy.data.Close, timeperiod=20, multiplier=2)
bb_sma = keltner_breakout_strategy.I(talib.SMA, keltner_breakout_strategy.data.Close, timeperiod=20)
bb_upper = keltner_breakout_strategy.I(lambda x, y, z: x + (y * z), bb_sma, bb_atr, timeperiod=1)
bb_lower = keltner_breakout_strategy.I(lambda x, y, z: x - (y * z), bb_sma, bb_atr, timeperiod=1)

rsi = keltner_breakout_strategy.I(talib.RSI, keltner_breakout_strategy.data.Close, timeperiod=14)

def divergence_check_talib():
    if len(keltner_breakout_strategy.data) < 4:
        return False
    current_price_low = keltner_breakout_strategy.data.Low.iloc[-1]
    current_rsi = rsi.iloc[-1]
    
    prev1_price_low = keltner_breakout_strategy.data.Low.iloc[-2]
    prev1_rsi = rsi.iloc[-2]
    
    prev2_price_low = keltner_breakout_strategy.data.Low.iloc[-3]
    prev2_rsi = rsi.iloc[-3]
    
    if current_price_low >= prev1_price_low:
        return False
    if current_rsi <= prev1_rsi:
        return False
    return True

def run_strategy_talib():
    # Condition A: Volatility Expansion
    current_bb_width = bb_upper - bb_lower
    prev_bb_width = bb_upper.shift(1) - bb_lower.shift(1)
    volatility_expanded = current_bb_width > prev_bb_width
    
    # Condition B: Bullish Divergence
    bullish_div = divergence_check_talib()
    
    # Trigger: Price closes above Keltner Upper
    break_out = keltner_breakout_strategy.data.Close > kc_upper
    
    # Enter Long if all conditions met
    if break_out and bullish_div and volatility_expanded:
        # FIX: Position sizing corrected to fraction (1% of equity) instead of fixed units
        # This avoids issues with float units and adheres to Moon Dev sizing rules
        position_size = 0.01  # 1% of equity
        
        self.buy(size=position_size, comment="Moon Dev 🌙 Breakout Entry", order_type=bt.Order.Limit)

def run_exit_talib():
    if self.position:
        # Exit if price closes below Keltner Middle
        if keltner_breakout_strategy.data.Close < kc_middle:
            self.sell(comment="Moon Dev 🌙 Trend Failure Exit")
        
        # Trailing Stop
        if keltner_breakout_strategy.data.Close < kc_lower:
            self.sell(comment="Moon Dev 🌙 Trailing Stop Hit")

keltner_breakout_strategy.run_strategy = run_strategy_talib
keltner_breakout_strategy.run_exit = run_exit_talib

# Run backtest
stats = bt.run(keltner_breakout_strategy)

# Print full stats
print("\n🌙 Moon Dev Backtest Complete 🚀\n")
print(stats)
print("\n📊 Strategy Performance:\n")
print(stats._strategy)