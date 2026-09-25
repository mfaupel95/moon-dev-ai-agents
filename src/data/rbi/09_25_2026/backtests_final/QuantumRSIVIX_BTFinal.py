from backtesting import Backtest, Strategy
from backtesting.lib import SMA, crossover
import talib

class QuantumRSIVIX(Strategy):
    # --- Parameters (Defined by Strategy Logic) ---
    # VIX Filter: Check if VIX is trending up
    vix_period = 20
    
    # RSI Period
    rsi_period = 14
    
    # ATR Period for dynamic stops/targets
    atr_period = 14
    
    # Risk Multipliers (Defined by Strategy Logic)
    stop_loss_mult = 1.5
    take_profit_mult = 3.0
    trailing_start_mult = 2.5
    
    # Time Limit in bars (Defined by Strategy Logic)
    max_time = 5 * 24 * 4 # 5 days at 1hr bars (adjust based on your data frequency)

    def initialize(self):
        # 1. Calculate SMA for VIX Trend Filter
        # FIX: Ensure consistent library usage. Using talib for SMA here matches the RSI usage.
        # If using backtesting.lib, the argument must be 'timeperiod', not 'period'.
        self.vix_sma = self.I(talib.SMA, self.data.Close, timeperiod=self.vix_period)
        
        # 2. Calculate RSI for Divergence Detection
        self.rrsi = self.I(talib.RSI, self.data.Close, timeperiod=self.rsi_period)
        
        # 3. Calculate ATR for Dynamic Stops and Targets
        self.atr = self.I(talib.ATR, self.data.Close, timeperiod=self.atr_period)

    def next(self):
        # --- Volatility Filter (VIX Upward Trajectory) ---
        # Logic: Only trade if VIX is above its moving average or trending up.
        # Assuming simple threshold: Current VIX > SMA(VIX, 20)
        vix_trend = self.vix_sma[-1]
        vix_current = self.data.Close[-1] # Assuming 'Close' represents the VIX series in your data
        
        if vix_current <= vix_trend:
            return

        # --- Divergence Detection (RSI vs Price) ---
        # Logic: 
        # Long: Price makes lower low, RSI makes higher low (Bullish Divergence)
        # Short: Price makes higher high, RSI makes lower high (Bearish Divergence)
        
        # Identify Swing Lows (Simplified: compare to 2 bars ago)
        price_low_2 = self.data.Low[-2]
        price_low_1 = self.data.Low[-1]
        
        rsi_low_2 = self.rrsi[-2]
        rsi_low_1 = self.rrsi[-1]
        
        # Check for Bullish Divergence (Lower Price Low, Higher RSI Low)
        is_bullish_divergence = (price_low_1 < price_low_2) and (rsi_low_1 > rsi_low_2)
        
        # Check for Bearish Divergence (Higher Price High, Lower RSI High)
        # Note: Strategy spec implies looking for lows for longs, but divergence logic usually checks highs too.
        # Based on spec: "Price making lower lows while RSI makes higher lows" for Long.
        # We will trigger on the confirmation bar closing.
        
        if is_bullish_divergence:
            # Entry Condition: Close of the bar confirming the divergence
            # FIX: Ensure crossover or manual check is used correctly
            if self.data.Close[-1] >= self.data.Close[-2]: # Confirming up move or holding low
                self.buy(size=1) # Position sizing: 1 unit (Whole number as per rules)

        # --- Exit Conditions ---
        # Stop Loss: Current Entry Price - (X * ATR)
        # Take Profit: Current Entry Price + (Y * ATR)
        # Trailing Stop: Switch to 50% target logic
        
        if self.positions:
            current_price = self.data.Close[-1]
            atr_val = self.atr[-1]
            
            # Calculate dynamic targets based on VIX level (Higher VIX = Wider stops)
            # Logic: stop_loss_mult * ATR * (1 + vix_current/vix_trend) scaling could be added here if needed
            # For now, applying base multipliers as per strategy logic
            
            stop_loss_price = current_price - (self.stop_loss_mult * atr_val)
            take_profit_price = current_price + (self.take_profit_mult * atr_val)
            
            # Check Stop Loss
            if current_price <= stop_loss_price:
                self.close_all(positions=0) # Close all with 0 size (market exit)
                
            # Check Take Profit
            elif current_price >= take_profit_price:
                self.close_all(positions=0)
                
            # Check Time Limit
            if self.time_in_position >= self.max_time:
                self.close_all(positions=0)
                
            # Optional: Trailing Stop logic implementation would go here if specific trailing rules are added later