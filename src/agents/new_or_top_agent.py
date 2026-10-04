"""
🌙 Moon Dev's New & Top Coins Agent 🔍

This agent goes through and analyzes all of the new tokens that have been listed in the coin gecko and then also analyzes the top movers of the last 24 hours on coin gecko and then makes recommendations based off that data. 

=================================
📚 QUICK START GUIDE
=================================
1. Set up environment variables in .env:
   - COINGECKO_API_KEY
   - ANTHROPIC_KEY (for Claude)
   - DEEPSEEK_KEY (for DeepSeek)

2. Choose AI model by setting MODEL_OVERRIDE at top of file:
   ```python
   # Use config.py's AI_MODEL (Default)
   MODEL_OVERRIDE = "0"  
   
   # For DeepSeek Chat (Faster, more concise)
   MODEL_OVERRIDE = "deepseek-chat"  
   
   # For DeepSeek Reasoner (Better reasoning, more detailed)
   MODEL_OVERRIDE = "deepseek-reasoner"
   ```

   🔍 Model Comparison:
   - Claude (from config.py): Balanced analysis, good for general use
   - DeepSeek Chat: Faster responses, more concise analysis
   - DeepSeek Reasoner: Better for complex market analysis, 
     provides more detailed reasoning

   To switch models:
   1. Get your DeepSeek API key from: https://platform.deepseek.com
   2. Add it to .env as DEEPSEEK_KEY="your_key_here"
   3. Set MODEL_OVERRIDE to your preferred model
   4. Restart the agent

3. Run the agent:
   python src/agents/new_or_top_agent.py

4. Check results in src/data/coingecko_results:
   - top_gainers_losers.csv (Raw data of top performers)
   - new_coins.csv (Latest 200 added coins)
   - ai_picks.csv (AI analysis and recommendations)
   - ai_buys.csv (Only BUY recommendations)

The agent runs every hour and:
- Fetches top 30 gainers and losers
- Gets latest 200 new coins
- Analyzes each coin with AI
- Saves BUY/SELL/DO NOTHING recommendations

=================================
🤖 AI ANALYSIS PROMPT
=================================
You can modify this prompt to customize the AI analysis:
"""

AI_PROMPT = """
Please analyze this cryptocurrency and provide a clear BUY, SELL, or DO NOTHING recommendation.

Coin Information:
• Name: {name}
• Symbol: {symbol}
• Source: {source_type}

Market Data (USD):
• Current Price: ${price:,.8f}
• 24h Open: ${open:,.8f}
• 24h High: ${high:,.8f}
• 24h Low: ${low:,.8f}
• 24h Volume: ${volume:,.2f}
• Market Cap Rank: #{market_cap_rank}
• 24h Change: {change:,.2f}%
• 7d Change: {change_7d:,.2f}%
• 30d Change: {change_30d:,.2f}%

Community Data:
{community_data}

IMPORTANT: Start your response with one of these recommendations:
RECOMMENDATION: BUY
RECOMMENDATION: SELL
RECOMMENDATION: DO NOTHING

Then provide your detailed analysis.
"""

"""
Main Agent Code Below
=================================
"""

import os
import requests
import pandas as pd
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
import anthropic
import openai
from typing import Dict, List
import time
from termcolor import colored, cprint
import random
import src.config as config

# Zugriffsschicht mit 429-Backoff (T-261). Ohne sie verarbeitete der
# Agent die LEEREN Antworten des Rate-Limits weiter und speicherte
# Empfehlungen ohne Marktdaten.
from src.agents.coingecko_zugriff import Zugriff, hat_marktdaten
from src.agents.zyklus_watchdog import begrenze_zyklus

# Load environment variables
load_dotenv()

# Model override settings
# Set to "0" to use config.py's AI_MODEL setting
# Available models:
# - "deepseek-chat" (DeepSeek's V3 model - fast & efficient)
# - "deepseek-reasoner" (DeepSeek's R1 reasoning model)
# - "0" (Use config.py's AI_MODEL setting)
MODEL_OVERRIDE = "deepseek-chat"  # Set to "0" to disable override

# DeepSeek API settings
DEEPSEEK_BASE_URL = "https://api.deepseek.com"  # Base URL for DeepSeek API

# 🤖 Agent Model Selection
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")
AI_MODEL = OLLAMA_MODEL or (MODEL_OVERRIDE if MODEL_OVERRIDE != "0" else config.AI_MODEL)

# Configuration
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
BASE_URL = "https://api.coingecko.com/api/v3" if not COINGECKO_API_KEY else "https://pro-api.coingecko.com/api/v3"
RESULTS_DIR = Path("src/data/coingecko_results")
DELAY_BETWEEN_REQUESTS = 12  # Seconds between API calls (oeffentliche API: Rate-Limit)
# GEMESSEN 04.10.2026: die oeffentliche API laesst ~5 Aufrufe/Minute zu, der
# Zyklus braucht aber 2 + 2 je Coin. 12 s zwischen zwei Coins ist zu wenig;
# der Zugriff wartet selbst (coingecko_zugriff), dieser Wert gilt nur fuer
# den Abstand zwischen zwei vollstaendigen Coin-Abrufen.
DELAY_BETWEEN_REQUESTS = 15
LLM_FRIST_S = 120           # s: eigener Timeout fuer den Modellaufruf
MAX_COINS = 3               # je Lauf; 6 Coins = 14 Aufrufe > Limit


def llm_lokal(prompt):
    """Native Ollama-API (/api/chat, think:false). Der /v1-OpenAI-Weg liefert
    bei qwen35-8k LEEREN content (Antwort landet im reasoning-Feld), gemessen
    16.09.2026; /api/chat mit think:false antwortet zuverlaessig."""
    import json
    import urllib.request
    basis = (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/api").rstrip("/")
    if not basis.endswith("/api"):
        basis += "/api"
    koerper = json.dumps({
        "model": OLLAMA_MODEL or AI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False, "think": False,
        "options": {"temperature": 0.7, "num_predict": 500},
    }).encode("utf-8")
    anfrage = urllib.request.Request(basis + "/chat", data=koerper,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(anfrage, timeout=LLM_FRIST_S) as antwort:
        daten = json.loads(antwort.read().decode("utf-8", "replace"))
    inhalt = (daten.get("message") or {}).get("content") or ""
    if not inhalt.strip():
        raise RuntimeError("leere Antwort von %s (Modell %s) - "
                           "das Modell denkt nur in reasoning" % (basis, OLLAMA_MODEL))
    return inhalt

# Output files
TOP_GAINERS_LOSERS_FILE = RESULTS_DIR / "top_gainers_losers.csv"
NEW_COINS_FILE = RESULTS_DIR / "new_coins.csv"
AI_PICKS_FILE = RESULTS_DIR / "ai_picks.csv"
AI_BUYS_FILE = RESULTS_DIR / "ai_buys.csv"  # New file for buy signals

# Create results directory
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Fun emoji sets for different actions
SPINNER_EMOJIS = ['🌍', '🌎', '🌏']  # Earth spinning
MOON_PHASES = ['🌑', '🌒', '🌓', '🌔', '🌕', '🌖', '🌗', '🌘']  # Moon phases
ROCKET_SEQUENCE = ['🚀', '💫', '✨', '💫', '🌟']  # Rocket launch
ERROR_EMOJIS = ['💥', '🚨', '⚠️', '❌', '🔥']  # Error indicators
SUCCESS_EMOJIS = ['✨', '🎯', '🎨', '🎪', '🎭', '🎪']  # Success indicators

def print_spinner(message: str, emoji_set: List[str], color: str = 'white', bg_color: str = 'on_blue'):
    """Print a spinning emoji animation with message"""
    for emoji in emoji_set:
        print(f"\r{emoji} {colored(message, color, bg_color)}", end='', flush=True)
        time.sleep(0.2)
    print()  # New line after animation

def print_fancy(message: str, color: str = 'white', bg_color: str = 'on_blue', emojis: List[str] = None):
    """Print a message with random emojis from set"""
    if emojis:
        emoji = random.choice(emojis)
        cprint(f"{emoji} {message} {emoji}", color, bg_color)
    else:
        cprint(message, color, bg_color)

class NewOrTopAgent:
    """Agent for analyzing new and top performing coins"""
    
    def __init__(self):
        self.headers = {
            "Content-Type": "application/json"
        }
        if COINGECKO_API_KEY:
            self.headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
        # Eine Instanz fuer den ganzen Zyklus: sie zaehlt Aufrufe und
        # Rate-Limits und befolgt Retry-After (T-261).
        self.zugriff = Zugriff(
            BASE_URL, COINGECKO_API_KEY,
            melder=lambda t: print_fancy(t, 'yellow', 'on_grey', ERROR_EMOJIS))
        
        # Initialize AI client based on model
        if OLLAMA_MODEL:
            # Lokal ueber Ollama (OpenAI-kompatible API), wie in .env vorgesehen
            self.ai_client = openai.OpenAI(
                api_key="ollama",
                base_url=(os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1").replace("/api", "/v1")
            )
            print(f"🌙 Using local Ollama model: {OLLAMA_MODEL}")
        elif "deepseek" in AI_MODEL.lower():
            deepseek_key = os.getenv("DEEPSEEK_KEY")
            if deepseek_key:
                self.ai_client = openai.OpenAI(
                    api_key=deepseek_key,
                    base_url=os.getenv("DEEPSEEK_BASE_URL") or DEEPSEEK_BASE_URL
                )
                print(f"🚀 Using DeepSeek model: {AI_MODEL}")
            else:
                raise ValueError("🚨 DEEPSEEK_KEY not found in environment variables!")
        else:
            self.ai_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_KEY"))
            print(f"🤖 Using Claude model: {AI_MODEL}")
            
        print_fancy("🌙 Moon Dev's New & Top Coins Agent Initialized! 🌟", 'white', 'on_magenta', SUCCESS_EMOJIS)
        
    def get_top_gainers(self) -> pd.DataFrame:
        """Get only top gainers (positive performers)"""
        try:
            print_spinner("🚀 Fetching top gainers...", ROCKET_SEQUENCE, 'cyan', 'on_blue')
            # Oeffentlicher Endpunkt statt Pro-API (16.09.2026).
            # Der Zugriff befolgt 429 mit Retry-After; kommt nichts, wird
            # der Zyklus verworfen statt mit leeren Daten weiterzulaufen.
            data = self.zugriff.hole(
                "/coins/markets",
                {
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": "100",
                    "sparkline": "false",
                    "price_change_percentage": "24h"
                })

            if data is not None:
                
                # Nur Gewinner, nach 24h-Aenderung sortiert; head(3) wegen
                # Rate-Limit der oeffentlichen API (Pro-Key hebt es auf)
                gainers = pd.DataFrame(data)
                
                if not gainers.empty:
                    gainers = gainers[gainers['price_change_percentage_24h_in_currency'] > 0] \
                        .sort_values('price_change_percentage_24h_in_currency', ascending=False) \
                        .head(3)
                    gainers = gainers.rename(columns={
                        'current_price': 'usd',
                        'total_volume': 'usd_24h_vol',
                        'price_change_percentage_24h_in_currency': 'usd_24h_change',
                    })
                    gainers['type'] = 'gainer'
                    gainers['timestamp'] = datetime.now().isoformat()
                    # Add CoinGecko URL
                    gainers['coingecko_url'] = gainers['id'].apply(lambda x: f"https://www.coingecko.com/en/coins/{x}")
                    gainers.to_csv(TOP_GAINERS_LOSERS_FILE, index=False)
                    
                    # Print each gainer with its price change
                    print_fancy("\n🚀 Top Gainers Found:", 'white', 'on_green')
                    for _, coin in gainers.iterrows():
                        gain_str = f"+{coin['usd_24h_change']:,.2f}%" if 'usd_24h_change' in coin else 'N/A'
                        price_str = f"${coin['usd']:,.8f}" if 'usd' in coin else 'N/A'
                        print_fancy(f"{coin['name']} ({coin['symbol'].upper()}): {gain_str} @ {price_str}", 'green', 'on_grey', ['💰', '🚀', '📈'])
                    
                    return gainers
                else:
                    print_fancy("No gainers found in this cycle", 'yellow', 'on_grey')
                    return pd.DataFrame()
                
            else:
                print_fancy("Top gainers: keine Daten (Rate-Limit oder "
                            "Netzfehler) - Zyklus verworfen (T-261)",
                            'white', 'on_red', ERROR_EMOJIS)
                return pd.DataFrame()
                
        except Exception as e:
            print_fancy(f"Error: {str(e)}", 'white', 'on_red', ERROR_EMOJIS)
            return pd.DataFrame()
            
    def get_new_coins(self) -> pd.DataFrame:
        """Get recently added coins"""
        try:
            print_spinner("Scanning for new coins...", MOON_PHASES, 'yellow', 'on_blue')
            # "Neue Coins" existiert nur in der Pro-API; oeffentlicher Ersatz:
            # die kleinsten 100 nach Marktkapitalisierung (16.09.2026)
            data = self.zugriff.hole(
                "/coins/markets",
                {
                    "vs_currency": "usd",
                    "order": "market_cap_asc",
                    "per_page": "100",
                    "sparkline": "false"
                })

            if data is not None:
                df = pd.DataFrame(data)
                df = df.head(3)
                df['timestamp'] = datetime.now().isoformat()
                # Add CoinGecko URL
                df['coingecko_url'] = df['id'].apply(lambda x: f"https://www.coingecko.com/en/coins/{x}")
                df.to_csv(NEW_COINS_FILE, index=False)
                
                print_fancy(f"Discovered {len(df)} new cosmic tokens! 🪐", 'cyan', 'on_grey', SUCCESS_EMOJIS)
                return df
                
            else:
                print_fancy("New coins: keine Daten (Rate-Limit oder "
                            "Netzfehler) - Zyklus verworfen (T-261)",
                            'white', 'on_red', ERROR_EMOJIS)
                return pd.DataFrame()
                
        except Exception as e:
            print_fancy(f"Error: {str(e)}", 'white', 'on_red', ERROR_EMOJIS)
            return pd.DataFrame()
            
    def get_coin_data(self, coin_id: str) -> Dict:
        """Detaildaten eines Coins - oder {}.

        LEERES DICT heisst "keine Daten": der Aufrufer ueberspringt den Coin
        und speichert NICHTS. Der alte Code hat nach einem 429 noch einmal
        versucht, die leere Antwort aber als Erfolg behandelt - daraus kamen
        die gespeicherten Analysen ohne Marktdaten (T-261).
        """
        try:
            print_spinner(f"Analyzing {coin_id}...", ROCKET_SEQUENCE, 'yellow', 'on_blue')

            # OHLCV und Hauptdaten: jeder Zugriff mit 429-Backoff. Fehlt eins,
            # wird der Coin uebersprungen - ein OHLCV-ohne-Kurs (oder umgekehrt)
            # waere eine halbe Wahrheit im Prompt.
            ohlcv_data = self.zugriff.hole(
                f"/coins/{coin_id}/ohlc",
                {"vs_currency": "usd", "days": "1"})
            if ohlcv_data is None:
                print_fancy(f"{coin_id}: OHLCV nicht abrufbar - Coin "
                            f"uebersprungen (T-261)", 'white', 'on_red', ERROR_EMOJIS)
                return {}

            coin_data = self.zugriff.hole(
                f"/coins/{coin_id}",
                {
                    "localization": False,
                    "tickers": True,
                    "market_data": True,
                    "community_data": True,
                    "developer_data": False  # No longer needed
                })
            if coin_data is None:
                print_fancy(f"{coin_id}: Coin-Daten nicht abrufbar - Coin "
                            f"uebersprungen (T-261)", 'white', 'on_red', ERROR_EMOJIS)
                return {}

            # ECHTHEITSWEG: ohne Kurs gibt es keine Analyse (T-261).
            if not hat_marktdaten(coin_data):
                print_fancy(f"{coin_id}: Antwort ohne Kurs - Coin uebersprungen (T-261)",
                            'white', 'on_red', ERROR_EMOJIS)
                return {}
                
            # Ohne OHLCV-Zeilen gibt es kein DataFrame - und ohne DataFrame
            # gibt es keine Analyse. Beides wird hier entschieden, nicht
            # weiter oben (T-261).
            if not ohlcv_data:
                print_fancy(f"{coin_id}: OHLCV leer - Coin uebersprungen (T-261)",
                            'white', 'on_red', ERROR_EMOJIS)
                return {}

            ohlcv_df = pd.DataFrame(ohlcv_data,
                                    columns=['timestamp', 'open', 'high', 'low', 'close'])
            latest_ohlcv = ohlcv_df.iloc[-1]
            md = coin_data.get('market_data') or {}

            market_data = {
                'price': (md.get('current_price') or {}).get('usd'),
                'open': latest_ohlcv['open'],
                'high': latest_ohlcv['high'],
                'low': latest_ohlcv['low'],
                'close': latest_ohlcv['close'],
                'volume': (md.get('total_volume') or {}).get('usd', 0),
                'market_cap_rank': coin_data.get('market_cap_rank', 'N/A'),
                'change_24h': md.get('price_change_percentage_24h', 0),
                'change_7d': md.get('price_change_percentage_7d', 0),
                'change_30d': md.get('price_change_percentage_30d', 0)
            }

            coin_data['market_data_df'] = pd.DataFrame([market_data])
            coin_data['ohlcv_df'] = ohlcv_df

            print_fancy(f"✨ Intel gathered on {coin_id}!", 'green', 'on_grey', SUCCESS_EMOJIS)
            return coin_data

        except Exception as e:
            print_fancy(f"Error: {str(e)}", 'white', 'on_red', ERROR_EMOJIS)
            return {}
            
    def analyze_coin(self, coin_data: Dict, source_type: str) -> str:
        """Analyze a coin using AI"""
        try:
            name = coin_data.get('name')
            symbol = coin_data.get('symbol', '').upper()
            
            # Clear visual break before new analysis
            print("\n" + "=" * 80)
            print_fancy("🤖 STARTING NEW AI ANALYSIS 🤖", 'white', 'on_magenta', ROCKET_SEQUENCE)
            print("=" * 80)
            
            # Show which coin we're analyzing
            print_fancy(f"Token: {name} ({symbol})", 'cyan', 'on_grey')
            price_str = f"${coin_data.get('market_data', {}).get('current_price', {}).get('usd', 0):,.8f}"
            print_fancy(f"Current Price: {price_str}", 'cyan', 'on_grey')
            print("=" * 80 + "\n")
            
            market_df = coin_data.get('market_data_df')
            if market_df is None or market_df.empty:
                print_fancy("No market data available!", 'white', 'on_red', ERROR_EMOJIS)
                return "Error: No market data available"
                
            market_data = market_df.iloc[0]
            
            # Format coin data for analysis
            prompt = AI_PROMPT.format(
                name=name,
                symbol=symbol,
                source_type=source_type,
                price=market_data['price'],
                open=market_data['open'],
                high=market_data['high'],
                low=market_data['low'],
                volume=market_data['volume'],
                market_cap_rank=market_data['market_cap_rank'],
                change=market_data['change_24h'],
                change_7d=market_data['change_7d'],
                change_30d=market_data['change_30d'],
                community_data=json.dumps(coin_data.get('community_data', {}), indent=2)
            )
            
            print_fancy("🧠 AI Agent Processing...", 'yellow', 'on_blue', SPINNER_EMOJIS)
            
            # Get AI response.
            # ACHTUNG (T-261): die alte Bedingung war
            # `if "deepseek" in AI_MODEL.lower() or OLLAMA_MODEL:` - OLLAMA_MODEL
            # ist aber ein String, der auch None sein kann; im Betrieb ist die
            # Bedingung immer wahr, der tote Anthropic-Zweig blieb erhalten.
            # Massgeblich ist der WEG, nicht der Modellname.
            if OLLAMA_MODEL:
                # Lokal: native Ollama-API - /v1 liefert leeren content
                analysis = llm_lokal(prompt)
            else:
                response = self.ai_client.messages.create(
                    model=AI_MODEL,
                    max_tokens=500,
                    temperature=0.7,
                    messages=[{
                        "role": "user",
                        "content": prompt
                    }]
                )
                analysis = response.content[0].text
                
            # Extract and display recommendation prominently
            recommendation = self.extract_recommendation(analysis)
            change_str = f"{market_data['change_24h']:+.2f}%"
            
            # Show recommendation with dramatic spacing
            print("\n" + "🎯 " * 20)
            if recommendation == "BUY":
                print_fancy(f"RECOMMENDATION FOR {name} ({symbol}):", 'white', 'on_green', ['💰', '🚀'])
                print_fancy(f"BUY @ {price_str} ({change_str})", 'white', 'on_green', ['💰', '🚀', '📈'])
            elif recommendation == "SELL":
                print_fancy(f"RECOMMENDATION FOR {name} ({symbol}):", 'white', 'on_red', ['💸', '📉'])
                print_fancy(f"SELL @ {price_str} ({change_str})", 'white', 'on_red', ['💸', '🔻', '📉'])
            else:
                print_fancy(f"RECOMMENDATION FOR {name} ({symbol}):", 'white', 'on_blue', ['🎯', '⏳'])
                print_fancy(f"DO NOTHING @ {price_str} ({change_str})", 'white', 'on_blue', ['🎯', '⏳', '🔄'])
            print("🎯 " * 20 + "\n")
            
            # End of analysis marker
            print("=" * 80)
            print_fancy("AI ANALYSIS COMPLETE", 'white', 'on_magenta', SUCCESS_EMOJIS)
            print("=" * 80 + "\n")
            
            return analysis
            
        except Exception as e:
            print_fancy(f"Error in AI analysis: {str(e)}", 'white', 'on_red', ERROR_EMOJIS)
            return "Error in analysis"
            
    def extract_recommendation(self, analysis: str) -> str | None:
        """BUY/SELL/DO NOTHING aus dem Text - oder None.

        None unterscheidet "das Modell sagt: nichts tun" (DO NOTHING, ein
        echtes Urteil) von "es kam kein Urteil zustande" (T-261). Vorher
        gab es beides als DO NOTHING zurueck, und jeder Timeout landete
        als scheinbar gueltige Empfehlung in der CSV.
        """
        if not analysis or analysis.startswith("Error"):
            return None
        if "RECOMMENDATION: BUY" in analysis:
            return "BUY"
        elif "RECOMMENDATION: SELL" in analysis:
            return "SELL"
        elif "RECOMMENDATION: DO NOTHING" in analysis:
            return "DO NOTHING"
        # Antwort ohne die Kennung: das Modell hat die Vorgabe nicht beachtet.
        # Das ist KEIN Urteil.
        return None
        
    def save_analysis(self, result: Dict):
        """Save a single analysis result to CSV"""
        df = pd.DataFrame([result])
        
        # Save to main picks file
        if os.path.exists(AI_PICKS_FILE):
            df.to_csv(AI_PICKS_FILE, mode='a', header=False, index=False)
        else:
            df.to_csv(AI_PICKS_FILE, index=False)
        
        # If it's a BUY recommendation, also save to buys file
        if result['recommendation'] == "BUY":
            if os.path.exists(AI_BUYS_FILE):
                df.to_csv(AI_BUYS_FILE, mode='a', header=False, index=False)
            else:
                df.to_csv(AI_BUYS_FILE, index=False)
            print_fancy(f"💰 Added {result['name']} to AI Buys!", 'white', 'on_green', ['💰', '🚀', '📈'])
        else:
            print_fancy(f"💾 Saved analysis for {result['name']}", 'white', 'on_green', SUCCESS_EMOJIS)
            
    def run_analysis(self):
        """Run complete analysis cycle"""
        print_spinner("🚀 Initiating Moon Dev Analysis Sequence...", ROCKET_SEQUENCE, 'white', 'on_magenta')
        
        # Get only top gainers and new coins
        top_gainers_df = self.get_top_gainers()
        new_coins_df = self.get_new_coins()
        
        total_analyzed = 0
        
        # Analyze top gainers
        if not top_gainers_df.empty:
            for _, coin in top_gainers_df.iterrows():
                coin_data = self.get_coin_data(coin['id'])
                if coin_data:
                    analysis = self.analyze_coin(coin_data, "Top gainer")
                    recommendation = self.extract_recommendation(analysis)
                    if recommendation is None:
                        # KEIN Urteil (Timeout/leere Antwort) - nicht speichern.
                        # Sonst stehen Empfehlungen in der CSV, die keine sind
                        # (T-261).
                        time.sleep(DELAY_BETWEEN_REQUESTS)
                        continue
                    
                    result = {
                        'timestamp': datetime.now().isoformat(),
                        'coin_id': coin['id'],
                        'name': coin['name'],
                        'symbol': coin['symbol'],
                        'source': "Top gainer",
                        'price_usd': coin['usd'],
                        'volume_24h': coin['usd_24h_vol'],
                        'price_change_24h': coin['usd_24h_change'],
                        'recommendation': recommendation,
                        'coingecko_url': coin['coingecko_url']
                    }
                    
                    # Save each analysis immediately
                    self.save_analysis(result)
                    total_analyzed += 1
                    
                time.sleep(DELAY_BETWEEN_REQUESTS)
                
        # Analyze new coins
        if not new_coins_df.empty:
            for _, coin in new_coins_df.iterrows():
                coin_data = self.get_coin_data(coin['id'])
                if coin_data:
                    analysis = self.analyze_coin(coin_data, "Recently Added")
                    recommendation = self.extract_recommendation(analysis)
                    if recommendation is None:
                        time.sleep(DELAY_BETWEEN_REQUESTS)
                        continue
                    
                    result = {
                        'timestamp': datetime.now().isoformat(),
                        'coin_id': coin['id'],
                        'name': coin['name'],
                        'symbol': coin['symbol'],
                        'source': "Recently Added",
                        'price_usd': coin_data.get('market_data', {}).get('current_price', {}).get('usd', 0),
                        'volume_24h': coin_data.get('market_data', {}).get('total_volume', {}).get('usd', 0),
                        'recommendation': recommendation,
                        'coingecko_url': coin['coingecko_url']
                    }
                    
                    # Save each analysis immediately
                    self.save_analysis(result)
                    total_analyzed += 1
                    
                time.sleep(DELAY_BETWEEN_REQUESTS)
                
        # Print final summary
        if total_analyzed > 0:
            print_fancy("\n🎮 ANALYSIS COMPLETE 🎮", 'white', 'on_green')
            print_fancy("=" * 50, 'blue', 'on_white')
            
            # Read the full file to get summary (alte Hand-CSVs koennen
            # anderes Format haben - dann keine Zusammenfassung statt Absturz)
            try:
                results_df = pd.read_csv(AI_PICKS_FILE)
                summary = results_df['recommendation'].value_counts()
            except Exception:
                summary = {}
            
            print_fancy(f"BUY: {summary.get('BUY', 0)} 💰", 'green', 'on_grey')
            print_fancy(f"SELL: {summary.get('SELL', 0)} 📉", 'red', 'on_grey')
            print_fancy(f"DO NOTHING: {summary.get('DO NOTHING', 0)} 🎯", 'yellow', 'on_grey')
            print_fancy("=" * 50, 'blue', 'on_white')

ZYKLUS_GRENZE_S = 1800      # s: 30 min. Budget = MAX_COINS x (2 HTTP +
                            # LLM 120 s) + Wartezeiten; x2 als Reserve.
PAUSE_S = 3600              # s zwischen zwei Zyklen


def main():
    """Main function to run the agent"""
    print_fancy("\n🌙 Moon Dev's Cosmic Token Analysis Starting! 🌟", 'white', 'on_magenta', SUCCESS_EMOJIS)
    agent = NewOrTopAgent()
    print_fancy(f"Watchdog: {ZYKLUS_GRENZE_S} s je Zyklus (T-260) - haengt ein "
               f"Aufruf, bricht der Prozess ab und der Treiber startet neu",
               'cyan', 'on_grey')
    
    try:
        while True:
            # Ohne Watchdog haengt ein eingefrorener Modell- oder
            # HTTP-Aufruf den Agenten fuer immer (T-260).
            with begrenze_zyklus("new_or_top", ZYKLUS_GRENZE_S):
                agent.run_analysis()
            for emoji in MOON_PHASES:
                print_fancy(f"{emoji} Waiting for next analysis cycle...", 'cyan', 'on_blue')
                time.sleep(PAUSE_S / len(MOON_PHASES))
            
    except KeyboardInterrupt:
        print_fancy("\n👋 Agent stopped by user - Moon Dev out! 🌙", 'white', 'on_magenta')
    except Exception as e:
        print_fancy(f"\nError: {str(e)}", 'white', 'on_red', ERROR_EMOJIS)

if __name__ == "__main__":
    main()
