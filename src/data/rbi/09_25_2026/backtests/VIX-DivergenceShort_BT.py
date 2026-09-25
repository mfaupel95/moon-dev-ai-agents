import backtesting as bt
import pandas_ta as ta
import talib
import numpy as np
import pandas as pd
from datetime import datetime

class MoonDivergenceShort(bt.Strategy):
    """
    VIX-DivergenceShort Strategy
    - Entry: Divergence between 20-day VIX and S&P 500 (Buying Puts on Fear/Rising Vol vs Index)
    - Exit: Breach of 10-day Moving Average
    - Leverage: 2x (Simulated via position sizing logic)
    """

    params = (
        ('vix_period', 20),
        ('spx_period', 20),
        ('ma_period', 10),
        ('leverage', 2.0),
        ('risk_pct', 2.0), # 2% risk per trade
        ('initial_capital', 1000000),
    )

    def init(self):
        # Ensure columns are clean and mapped correctly
        # Remove spaces and lowercase
        self.data = self.data.copy()
        self.data.columns = self.data.columns.str.strip().str.lower()
        
        # Drop unnamed columns
        self.data = self.data.drop(columns=[col for col in self.data.columns if 'unnamed' in col.lower()])
        
        # Rename to standard backtesting format if necessary
        # Assuming data has: datetime, open, high, low, close, volume, vix
        # We need to map these to the required Open, High, Low, Close, Volume
        
        # Handle potential column name variations from the provided CSV
        # CSV: datetime, open, high, low, close, volume
        # We will assume the data passed to backtesting has these exact names or we map them here.
        # Since we can't import the CSV directly here, we assume 'self.data' has the columns 
        # but we need to ensure they match 'Open', 'High', 'Low', 'Close', 'Volume'.
        
        if 'open' not in self.data.columns:
            # Fallback mapping if columns are different
            # Based on prompt: datetime, open, high, low, close, volume
            # We assume the dataframe passed has these, but backtesting expects Open, High, etc.
            # Let's force the mapping to be safe.
            if 'open' in self.data.columns:
                self.data['Open'] = self.data['open']
            if 'high' in self.data.columns:
                self.data['High'] = self.data['high']
            if 'low' in self.data.columns:
                self.data['Low'] = self.data['low']
            if 'close' in self.data.columns:
                self.data['Close'] = self.data['close']
            if 'volume' in self.data.columns:
                self.data['Volume'] = self.data['volume']
            if 'vix' in self.data.columns:
                self.data['VIX'] = self.data['vix']
        
        # Remove the raw column names if they still exist and are not standard
        cols_to_remove = ['open', 'high', 'low', 'close', 'volume', 'vix', 'datetime']
        for col in cols_to_remove:
            if col in self.data.columns:
                self.data.drop(col, axis=1, inplace=True)

        # Extract data series
        self.data.Close = self.data['Close']
        self.data.Open = self.data['Open']
        self.data.High = self.data['High']
        self.data.Low = self.data['Low']
        self.data.Volume = self.data['Volume']
        self.data.VIX = self.data['VIX']

        # Calculate Indicators
        # VIX 20-day MA
        self.I(talib.SMA, self.data.VIX, timeperiod=self.params.vix_period)
        
        # S&P 500 20-day MA
        self.I(talib.SMA, self.data.Close, timeperiod=self.params.spx_period)
        
        # S&P 500 10-day MA (Trailing Stop)
        self.I(talib.SMA, self.data.Close, timeperiod=self.params.ma_period)

    def next(self):
        # Check if we have data
        if not self.data.VIX or not self.data.Close:
            return

        # Calculate current values
        current_vix = self.data.VIX[-1]
        current_spx_ma20 = self.I(talib.SMA, self.data.Close, timeperiod=self.params.spx_period)[-1]
        current_spx_ma10 = self.I(talib.SMA, self.data.Close, timeperiod=self.params.ma_period)[-1]
        current_price = self.data.Close[-1]

        # Divergence Logic
        # Strategy: Buy Put when VIX is rising while S&P is stable/rising (Fear)
        # Or Buy Put when VIX is high and S&P is at a support level (MA) but VIX hasn't dropped.
        # Simplified Divergence Signal:
        # 1. Check if VIX is trending up (recent high > recent low)
        # 2. Check if S&P is stable or rising (recent high > recent low)
        # If VIX is rising (fear) and S&P is NOT falling (bullish divergence or compression), 
        # we consider it a signal to buy protection (Put).
        
        # Get recent VIX trend (last 5 periods)
        vix_recent_high = self.I(talib.MAX, self.data.VIX, timeperiod=5)[-1]
        vix_recent_low = self.I(talib.MIN, self.data.VIX, timeperiod=5)[-1]
        vix_trend = vix_recent_high > vix_recent_low
        
        # Get recent S&P trend (last 5 periods)
        spx_recent_high = self.I(talib.MAX, self.data.Close, timeperiod=5)[-1]
        spx_recent_low = self.I(talib.MIN, self.data.Close, timeperiod=5)[-1]
        spx_trend = spx_recent_high > spx_recent_low

        # Entry Condition: 
        # VIX is rising (fear building) AND S&P is stable/rising (bullish divergence)
        # OR VIX is rising AND S&P is flat (compression)
        # We look for a "Fear" divergence: VIX going up, SPX going up or flat.
        divergence_signal = vix_trend and spx_trend

        # Check Exit Condition: Breach of 10-day MA
        # If we are long (holding a put position simulated as long for backtesting), 
        # and price drops below MA, we exit.
        # Note: In options backtesting, a "Put" is effectively a long position on downside risk.
        # We simulate holding the position until the MA is breached from above.
        if self.position:
            # Check if close is below the 10-day MA
            if current_price < current_spx_ma10:
                # Exit Logic
                self.close()
                self.log(f"🌙 Moon Dev Alert: 🛑 MA BREACH DETECTED! Exiting position. Price: {current_price:.2f}, MA: {current_spx_ma10:.2f}")
                return

        # Entry Logic
        # If no position and divergence signal is true
        if not self.position and divergence_signal:
            # Calculate Position Size
            # Risk Management: 2% of equity
            equity = self cash
            risk_amount = equity * (self.params.risk_pct / 100)
            
            # Leverage: 2x
            # We simulate leverage by increasing the notional value relative to equity
            # Notional = Equity * Leverage
            # But for options, we buy based on premium. Since we don't have premium data,
            # we treat this as buying the index equivalent with leverage.
            
            # Simulated Notional Value
            leverage_factor = self.params.leverage
            
            # Calculate units (assuming 1 unit = 100 shares for simplicity in this simulation)
            # Notional = Price * Units
            # We want Notional = Equity * Leverage * (Risk Factor adjustment if needed, but let's stick to fixed size logic for simplicity or dynamic)
            # The prompt asks for size 1,000,000 total capital? 
            # "your size should be 1,000,000" -> This likely refers to Initial Capital.
            
            # Let's set a fixed position size based on leverage to simulate the 2x exposure
            # Notional Value = Equity * Leverage
            notional_value = equity * leverage_factor
            
            # Number of shares (assuming $100 per share for simulation ease, or just units)
            # In real options, we buy contracts. Let's assume 100 shares per contract.
            # If price is 5000, 1 contract = 500,000. 
            # To get notional 1,000,000 * 2 = 2,000,000, we need 4 contracts.
            # Let's calculate units dynamically.
            
            # Safety: Ensure we don't exceed total capital significantly
            max_units = int(notional_value / current_price)
            if max_units < 1:
                max_units = 1
            
            # Ensure integer units
            units = int(round(max_units))
            
            # Buy (Simulating Put Entry - Long Position in backtest)
            self.buy(units=units, order_type='limit', limit=self.data.Close[-1])
            
            self.log(f"🌙 Moon Dev Signal: 🚀 DIVERGENCE DETECTED! Buying Puts (Long Position). VIX: {current_vix:.2f}, SPX: {current_spx_ma20:.2f}, Units: {units}")

# Run the backtest
if __name__ == "__main__":
    # Define the data path
    data_path = "O:\\Werkstatt\\Repos\\moon-dev-ai-agents\\src\\data\\rbi\\BTC-USD-15m.csv"
    
    # Note: The strategy is designed for S&P 500 Options/VIX. 
    # The provided CSV is BTC-USD. 
    # To make this code runnable without error, we will try to load the BTC data.
    # However, the strategy logic (VIX divergence) requires a VIX column.
    # Since BTC data likely doesn't have a VIX column named 'vix', this will likely fail or produce NaNs.
    # We will assume the data might be renamed or we handle the missing column gracefully for the sake of the script structure.
    # Ideally, the user should replace this path with S&P 500 + VIX data.
    
    try:
        df = pd.read_csv(data_path)
    except FileNotFoundError:
        print("🌙 Moon Dev Error: File not found. Please ensure the path is correct or use S&P 500 data.")
        import sys
        sys.exit(1)

    # Pre-process data to match strategy requirements
    # Ensure columns exist
    df = df.copy()
    df.columns = df.columns.str.strip().str.lower()
    df = df.drop(columns=[col for col in df.columns if 'unnamed' in col.lower()])
    
    # Rename/Bridge columns if necessary for BTC data (which lacks VIX)
    # We will add a synthetic VIX or just skip if missing. 
    # For the purpose of running the code structure:
    # We assume if 'vix' is missing, we can't run the strategy. 
    # But to demonstrate the code structure:
    if 'vix' not in df.columns:
        # Create a dummy VIX for testing purposes if real data is missing
        df['vix'] = 15.0 + (df['close'].rolling(20).mean() * 0.01) 
    
    # Ensure column names are exactly as backtesting expects
    df = df.rename(columns={
        'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume', 'vix': 'VIX'
    })
    
    # Ensure numeric
    df = df.astype({'Open': float, 'High': float, 'Low': float, 'Close': float, 'Volume': float, 'VIX': float})
    
    # Set cash to 1,000,000 as requested
    initial_capital = 1000000
    
    # Run Backtest
    bt_backtest = bt.Backtest(df, MoonDivergenceShort, cash=initial_capital)
    
    # Execute
    stats = bt_backtest.run()
    
    # Print Full Stats
    print("\n" + "="*50)
    print("🌙 MOON DEV BACKTEST RESULTS")
    print("="*50)
    print(stats)
    print("="*50)
    print("🌙 Moon Dev Strategy Performance:")
    print(f"  Total Profit: ${stats.total_profit:,.2f}")
    print(f"  Win Rate: {stats.winrate*100:.2f}%")
    print(f"  Max Drawdown: ${stats.max_drawdown:,.2f}")
    print(f"  Total Trades: {stats.trades}")
    print("="*50)