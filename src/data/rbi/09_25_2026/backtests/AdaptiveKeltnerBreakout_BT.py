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
    map_params={'keltner_period': 20, 'keltner_atr': 2, 'bollinger_period': 20, 'bollinger_std': 2, 'divergence_period': 20},
    params={'keltner_period': 20, 'keltner_atr': 2, 'bollinger_period': 20, 'bollinger_std': 2, 'divergence_period': 20},
    period=1
)

def check_bullish_divergence(data, period=20):
    """
    Identifies bullish divergence by comparing price lows with indicator lows.
    Returns True if a new low is lower than previous, but indicator low is higher.
    """
    # Calculate RSI as a proxy for momentum/divergence indicator
    rsi = keltner_breakout_strategy.I(ta.rsi, keltner_breakout_strategy.data.Close, length=period)
    
    # Find local minima for price and RSI
    price_low = keltner_breakout_strategy.I(ta.MIN, keltner_breakout_strategy.data.Low, length=period)
    rsi_low = keltner_breakout_strategy.I(ta.MIN, rsi, length=period)
    
    # We look for a pattern where price makes a lower low, but RSI makes a higher low
    # This requires checking the last 3 candles to establish a trend down and then the divergence
    if len(keltner_breakout_strategy.data) < 3:
        return False
    
    # Check current candle vs previous 2 candles
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

def check_volatility_expansion(bollinger_upper, bollinger_lower):
    """
    Checks if Bollinger Bands are expanding (widening).
    We compare the band width of the current period vs the previous period.
    """
    if len(keltner_breakout_strategy.data) < 2:
        return False
    
    current_width = bollinger_upper.iloc[-1] - bollinger_lower.iloc[-1]
    prev_width = bollinger_upper.iloc[-2] - bollinger_lower.iloc[-2]
    
    return current_width > prev_width

def divergence_logic():
    # Check if we are currently in a bullish divergence state
    return check_bullish_divergence(keltner_breakout_strategy.data)

# Initialize indicators
keltner_upper = keltner_breakout_strategy.I(ta.ATR, keltner_breakout_strategy.data.High, length=20, multiplier=2)
keltner_middle = keltner_breakout_strategy.I(ta.SMA, keltner_breakout_strategy.data.Close, length=20)
keltner_lower = keltner_breakout_strategy.I(ta.SMA, keltner_breakout_strategy.data.Close, length=20)

# Correct Keltner calculation: Upper = Middle + (ATR * Multiplier), Lower = Middle - (ATR * Multiplier)
keltner_upper = keltner_breakout_strategy.I(ta.ATR, keltner_breakout_strategy.data.High, length=20, multiplier=2)
keltner_middle = keltner_breakout_strategy.I(ta.SMA, keltner_breakout_strategy.data.Close, length=20)
keltner_lower = keltner_breakout_strategy.I(ta.SMA, keltner_breakout_strategy.data.Close, length=20)
keltner_upper = keltner_breakout_strategy.I(lambda x, y: x + (y * 2), keltner_middle, keltner_upper, timeperiod=1) # Simplified logic below

# Let's use standard TA-Lib for Keltner Channel components more robustly
# Keltner Channel = SMA + (ATR * Multiplier)
keltner_atr = keltner_breakout_strategy.I(ta.ATR, keltner_breakout_strategy.data.High, length=20, multiplier=2)
keltner_sma = keltner_breakout_strategy.I(ta.SMA, keltner_breakout_strategy.data.Close, length=20)
keltner_upper = keltner_breakout_strategy.I(lambda x, y, z: x + (y * z), keltner_sma, keltner_atr, timeperiod=1)
keltner_lower = keltner_breakout_strategy.I(lambda x, y, z: x - (y * z), keltner_sma, keltner_atr, timeperiod=1)

# Bollinger Bands
bb_upper = keltner_breakout_strategy.I(ta.ATR, keltner_breakout_strategy.data.High, length=20, multiplier=2)
bb_sma = keltner_breakout_strategy.I(ta.SMA, keltner_breakout_strategy.data.Close, length=20)
bb_lower = keltner_breakout_strategy.I(ta.ATR, keltner_breakout_strategy.data.Close, length=20, multiplier=2)
bb_upper = keltner_breakout_strategy.I(lambda x, y, z: x + (y * z), bb_sma, bb_upper, timeperiod=1)
bb_lower = keltner_breakout_strategy.I(lambda x, y, z: x - (y * z), bb_sma, bb_lower, timeperiod=1)

# Re-calculate correctly using talib functions directly for robustness
# Keltner
kc_atr = keltner_breakout_strategy.I(ta.ATR, keltner_breakout_strategy.data.High, length=20, multiplier=2)
kc_sma = keltner_breakout_strategy.I(ta.SMA, keltner_breakout_strategy.data.Close, length=20)
kc_upper = keltner_breakout_strategy.I(lambda x, y, z: x + (y * z), kc_sma, kc_atr, timeperiod=1)
kc_lower = keltner_breakout_strategy.I(lambda x, y, z: x - (y * z), kc_sma, kc_atr, timeperiod=1)

# Bollinger
bb_atr = keltner_breakout_strategy.I(ta.ATR, keltner_breakout_strategy.data.High, length=20, multiplier=2)
bb_sma = keltner_breakout_strategy.I(ta.SMA, keltner_breakout_strategy.data.Close, length=20)
bb_upper = keltner_breakout_strategy.I(lambda x, y, z: x + (y * z), bb_sma, bb_atr, timeperiod=1)
bb_lower = keltner_breakout_strategy.I(lambda x, y, z: x - (y * z), bb_sma, bb_atr, timeperiod=1)

# Divergence check (using RSI as the indicator for simplicity in code, as manual swing high/low is complex in pure backtesting without specific libraries)
rsi = keltner_breakout_strategy.I(ta.rsi, keltner_breakout_strategy.data.Close, length=14)

def divergence_check():
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
def run_strategy():
    # Condition A: Volatility Expansion
    current_bb_width = bb_upper - bb_lower
    prev_bb_width = bb_upper.shift(1) - bb_lower.shift(1)
    volatility_expanded = current_bb_width > prev_bb_width
    
    # Condition B: Bullish Divergence
    bullish_div = divergence_check()
    
    # Trigger: Price closes above Keltner Upper
    break_out = keltner_breakout_strategy.data.Close > kc_upper
    
    # Enter Long if all conditions met
    if break_out and bullish_div and volatility_expanded:
        # Calculate risk
        # Stop loss at Keltner Lower or fixed % below entry
        entry_price = keltner_breakout_strategy.data.Close
        stop_loss_price = kc_lower
        
        position_size = 1000000.0  # Fixed size as per requirement
        # Ensure integer size
        position_size = int(round(position_size))
        
        self.buy(size=position_size, comment="Moon Dev 🌙 Breakout Entry", order_type=bt.Order.Limit)

# Entry Logic (Corrected for standard backtesting interface)
def run_strategy_corrected():
    # Condition A: Volatility Expansion
    current_bb_width = bb_upper - bb_lower
    prev_bb_width = bb_upper.shift(1) - bb_lower.shift(1)
    volatility_expanded = current_bb_width > prev_bb_width
    
    # Condition B: Bullish Divergence
    bullish_div = divergence_check()
    
    # Trigger: Price closes above Keltner Upper
    break_out = keltner_breakout_strategy.data.Close > kc_upper
    
    # Enter Long if all conditions met
    if break_out and bullish_div and volatility_expanded:
        # Calculate risk
        # Stop loss at Keltner Lower or fixed % below entry
        entry_price = keltner_breakout_strategy.data.Close
        stop_loss_price = kc_lower
        
        position_size = 1000000.0  # Fixed size as per requirement
        # Ensure integer size
        position_size = int(round(position_size))
        
        self.buy(size=position_size, comment="Moon Dev 🌙 Breakout Entry", order_type=bt.Order.Limit)

# Exit Logic
def run_exit():
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

kc_atr = keltner_breakout_strategy.I(ta.ATR, keltner_breakout_strategy.data.High, length=20, multiplier=2)
kc_sma = keltner_breakout_strategy.I(ta.SMA, keltner_breakout_strategy.data.Close, length=20)
kc_upper = keltner_breakout_strategy.I(lambda x, y, z: x + (y * z), kc_sma, kc_atr, timeperiod=1)
kc_lower = keltner_breakout_strategy.I(lambda x, y, z: x - (y * z), kc_sma, kc_atr, timeperiod=1)
kc_middle = kc_sma

bb_atr = keltner_breakout_strategy.I(ta.ATR, keltner_breakout_strategy.data.High, length=20, multiplier=2)
bb_sma = keltner_breakout_strategy.I(ta.SMA, keltner_breakout_strategy.data.Close, length=20)
bb_upper = keltner_breakout_strategy.I(lambda x, y, z: x + (y * z), bb_sma, bb_atr, timeperiod=1)
bb_lower = keltner_breakout_strategy.I(lambda x, y, z: x - (y * z), bb_sma, bb_atr, timeperiod=1)

rsi = keltner_breakout_strategy.I(ta.rsi, keltner_breakout_strategy.data.Close, length=14)

def divergence_check():
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

def run_strategy():
    # Condition A: Volatility Expansion
    current_bb_width = bb_upper - bb_lower
    prev_bb_width = bb_upper.shift(1) - bb_lower.shift(1)
    volatility_expanded = current_bb_width > prev_bb_width
    
    # Condition B: Bullish Divergence
    bullish_div = divergence_check()
    
    # Trigger: Price closes above Keltner Upper
    break_out = keltner_breakout_strategy.data.Close > kc_upper
    
    # Enter Long if all conditions met
    if break_out and bullish_div and volatility_expanded:
        position_size = 1000000.0
        position_size = int(round(position_size))
        self.buy(size=position_size, comment="Moon Dev 🌙 Breakout Entry", order_type=bt.Order.Limit)

def run_exit():
    if self.position:
        # Exit if price closes below Keltner Middle
        if keltner_breakout_strategy.data.Close < kc_middle:
            self.sell(comment="Moon Dev 🌙 Trend Failure Exit")
        
        # Trailing Stop
        if keltner_breakout_strategy.data.Close < kc_lower:
            self.sell(comment="Moon Dev 🌙 Trailing Stop Hit")

keltner_breakout_strategy.run_strategy = run_strategy
keltner_breakout_strategy.run_exit = run_exit

# Run backtest
stats = bt.run(keltner_breakout_strategy)

# Print full stats
print("\n🌙 Moon Dev Backtest Complete 🚀\n")
print(stats)
print("\n📊 Strategy Performance:\n")
print(stats._strategy)