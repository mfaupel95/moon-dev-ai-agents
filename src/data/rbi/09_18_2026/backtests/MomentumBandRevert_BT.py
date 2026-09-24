```python
import pandas as pd
import talib
from backtesting import Backtest, Strategy
from backtesting.lib import SMA, RSI, BBANDS
from backtesting.strategy import indicators
import numpy as np

# Moon Dev's Backtest AI 🌙 Loading Strategy
# 🌙 Strategy: MomentumBandRevert
# 🚀 Size: 1,000,000 Capital
# 🌑 Risk: 1% per trade
# ✨ Path: /Users/md/Dropbox/dev/github/moon-dev-ai-agents-for-trading/src/data/rbi/BTC-USD-15m.csv

def load_data():
    data_path = '/Users/md/Dropbox/dev/github/moon-dev-ai-agents-for-trading/src/data/rbi/BTC-USD-15m.csv'
    try:
        data = pd.read_csv(data_path)
    except FileNotFoundError:
        print(f"🌙 ERROR: File not found at {data_path}")
        return None

    # 1. Clean column names by removing spaces
    data.columns = data.columns.str.strip().str.lower()
    
    # 2. Drop any unnamed columns
    data = data.drop(columns=[col for col in data.columns if 'unnamed' in col.lower()])
    
    # 3. Ensure proper column mapping
    required_cols = ['open', 'high', 'low', 'close', 'volume']
    available_cols = list(data.columns)
    
    if 'close' not in available_cols or 'volume' not in available_cols:
        print(f"🌙 ERROR: Required columns