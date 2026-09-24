import backtesting as bt
import backtesting.trading as trading
import pandas as pd
import talib
import numpy as np
import os
import sys

# Moon Dev Setup
class MoonBacktestEngine:
    def __init__(self):
        self.initial_capital = 1_000_000
        self.data_path = "/Users/md/Dropbox/dev/github/moon-dev-ai-agents-for-trading/src/data/rbi/BTC-USD-15m.csv"
        self.risk_per_trade = 0.01  # 1% Risk

    def load_and_clean_data(self):
        # Load Data
        try:
            df = pd.read_csv(self.data_path)
        except FileNotFoundError:
            print(f"🌙 ERROR: Data file not found: {self.data_path}")
            return None

        # Moon Dev Data Cleaning 🧹
        # Clean column names
        df.columns = df.columns.str.strip().str.lower()
        
        # Drop unnamed columns
        df = df.drop(columns=[col for col in df.columns if 'unnamed' in col.lower()])
        
        # Ensure required columns exist
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in df.columns:
                print(f"🌙 ERROR: Missing column '{col}'")
                return None
        
        # Rename to standard case
        df.rename(columns={col: col.capitalize() for col in required_cols}, inplace=True)
        # Ensure Volume is present and correct
        df['Volume'] = df['Volume']
        
        # Ensure datetime is set correctly for backtesting
        df['datetime'] = pd.to_datetime(df.index) if isinstance(df.index, pd.DatetimeIndex) else pd.to_datetime(df['datetime'])
        df = df.set_index('datetime')
        
        return df

    def run_strategy(self, df):
        # Initialize Backtesting
        bt = bt.Backtest(df, strategy=self.strategy, cash=self.initial_capital, commission=0.001)
        
        # Run
        stats = bt.run()
        
        # Print Full Stats 🌙
        print("🌙 Moon Dev Backtest Stats:")
        print(stats)
        print("\n🌙 Strategy Details:")
        print(stats._strategy)
        
        return stats

    def strategy(self, data):
        # Strategy Class
        class VolatileBreakout(bt.Strategy):
            def __init__(self):
                self.order = None
                self.position_size = 0
                
                # Indicators 🌙
                self.SMA_50 = self.I(talib.SMA, self.data.Close, timeperiod=50)
                self.ATR_14 = self.I(talib.ATR, self.data.High, self.data.Low, self.data.Close, timeperiod=14)
                self.BB_20 = self.I(talib.BBUPPER, self.data.High, self.data.Low, self.data.Close, timeperiod=20)
                self.Vol_20 = self.I(talib.SMA, self.data.Volume, timeperiod=20)
                self.ATR_20 = self.I(talib.SMA, self.ATR_14, timeperiod=20)
                
                # Volatility Expansion Check (20% increase from 20-period avg)
                self.vol_expansion = self.ATR_14 > (self.ATR_20 * 1.2)
                
                # Volume Confirmation (150% of avg)
                self.vol_spike = self.data.Volume > (self.Vol_20 * 1.5)
                
                # Trend Alignment (Price > EMA50 for long)
                self.trend_up = self.data.Close > self.SMA_50
                
            def next(self):
                # Moon Dev Debugging 🚀
                if self.position:
                    print(f"🌙 IN POSITION: {self.position}")
                    print(f"🌙 Current ATR: {self.ATR_14[-1]:.2f}")
                
                # Check Entry Conditions
                if not self.position and self.I(talib.BBUPPER, self.data.High, self.data.Low, self.data.Close, timeperiod=20)[-1] == self.BB_20[-1]:
                    # Check Volatility Expansion
                    if self.vol_expansion[-1] and self.vol_spike[-1]:
                        # Check Trend Alignment
                        if self.trend_up[-1]:
                            # Calculate Position Size (Integer Units)
                            # Risk Amount = Equity * Risk %
                            # Stop Loss Distance = 1.5 * ATR
                            # Size = Risk Amount / Stop Loss Price
                            
                            # Get current equity
                            equity = self.broker.get_cash()
                            risk_amount = equity * self.risk_per_trade
                            
                            # Calculate Stop Loss Level
                            bb_upper = self.BB_20[-1]
                            atr_val = self.ATR_14[-1]
                            stop_loss_price = bb_upper - (1.5 * atr_val)
                            
                            # Ensure valid stop loss
                            if stop_loss_price > 0:
                                # Calculate units (integer)
                                position_size_units = int(round(risk_amount / stop_loss_price))
                                
                                if position_size_units > 0:
                                    print(f"🌙 ENTRY SIGNAL: Volatility Breakout Detected! 🚀")
                                    print(f"🌙 Size: {position_size_units} units, Risk: {risk_amount:.2f}")
                                    self.buy(size=position_size_units)
                                    
                                    # Set Trailing Stop
                                    self.trailing_stop = 1.5 * self.ATR_14
                                    self.time_stop = 4 * data[1] # 4 hours (simplified)
                                    self.current_time = data[0]
                                    self.exit_time = data[1]
                                    
                                    # Check Time Stop (simplified)
                                    # In real backtesting, check duration
                                    # For this script, we'll rely on trailing stop for now as time stop logic is complex without full datetime access in core
                                    pass
                                    
                                    # Print entry signal
                                    print(f"🌙 BUY EXECUTED: {position_size_units} @ {self.data.Close[-1]:.2f}")
                            else:
                                print(f"🌙 STOP LOSS INVALID: {stop_loss_price}")
                
                # Check Exit (Trailing Stop)
                if self.position:
                    current_price = self.data.Close[-1]
                    stop_price = current_price - (1.5 * self.ATR_14[-1])
                    
                    if current_price < stop_price:
                        print(f"🌙 TRAILING STOP HIT: Price {current_price:.2f} < Stop {stop_price:.2f}")
                        self.close()
                        print(f"🌙 EXIT EXECUTED")
                        
                # Check Time Stop (Approximate based on index length)
                # If trade lasts too long without profit, exit
                # For 15m data, 4 hours = 16 candles
                if self.position and (self.data.index[-1] - self.data.index[self.order].index) > pd.Timedelta(hours=4):
                     print(f"🌙 TIME STOP TRIGGERED: 4 Hours exceeded")
                     self.close()
                     print(f"🌙 EXIT EXECUTED")

        # Apply Strategy
        return VolatileBreakout()

def main():
    engine = MoonBacktestEngine()
    
    # Load Data
    df = engine.load_and_clean_data()
    
    if df is not None:
        # Run Backtest
        engine.run_strategy(df)
    else:
        print("🌙 Backtest Failed due to data loading errors.")

if __name__ == "__main__":
    main()