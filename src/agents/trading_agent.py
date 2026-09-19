"""
🌙 Moon Dev's LLM Trading Agent
Handles all LLM-based trading decisions
"""

# Keep only these prompts
TRADING_PROMPT = """
You are Moon Dev's AI Trading Assistant 🌙

Analyze the provided market data and strategy signals (if available) to make a trading decision.

Market Data Criteria:
1. Price action relative to MA20 and MA40
2. RSI levels and trend
3. Volume patterns
4. Recent price movements

{strategy_context}

Respond in this exact format:
1. First line must be one of: BUY, SELL, or NOTHING (in caps)
2. Then explain your reasoning, including:
   - Technical analysis
   - Strategy signals analysis (if available)
   - Risk factors
   - Market conditions
   - Confidence level (as a percentage, e.g. 75%)

Remember: 
- Moon Dev always prioritizes risk management! 🛡️
- Never trade USDC or SOL directly
- Consider both technical and strategy signals
"""

ALLOCATION_PROMPT = """
You are Moon Dev's Portfolio Allocation Assistant 🌙

Given the total portfolio size and trading recommendations, allocate capital efficiently.
Consider:
1. Position sizing based on confidence levels
2. Risk distribution
3. Keep cash buffer as specified
4. Maximum allocation per position

Format your response as a Python dictionary:
{
    "token_address": allocated_amount,  # In USD
    ...
    "USDC_ADDRESS": remaining_cash  # Always use USDC_ADDRESS for cash
}

Remember:
- Total allocations must not exceed total_size
- Higher confidence should get larger allocations
- Never allocate more than {MAX_POSITION_PERCENTAGE}% to a single position
- Keep at least {CASH_PERCENTAGE}% in USDC as safety buffer
- Only allocate to BUY recommendations
- Cash must be stored as USDC using USDC_ADDRESS: {USDC_ADDRESS}
"""

import anthropic
import os
import pandas as pd
import json
import urllib.request
from termcolor import colored, cprint
from dotenv import load_dotenv
from datetime import datetime, timedelta
import time

# Local imports
from src.config import *

# Haus-Erweiterung (19.09.2026): nice_funcs verlangt BIRDEYE_API_KEY beim
# Import und ohlcv_collector zieht Birdeye-Daten. Der Papier-Modus braucht
# beides nicht. Lazy importieren (nur bei Live-Freigabe) und bei fehlendem
# Key einen Papier-Ersatz verwenden.
n = None
collect_all_tokens = None

def _lade_birdeye():
    """Importiert nice_funcs/ohlcv_collector; None, wenn nicht verfuegbar."""
    global n, collect_all_tokens
    if n is not None:
        return n, collect_all_tokens
    try:
        from src import nice_funcs as _n
        from src.data.ohlcv_collector import collect_all_tokens as _c
        n = _n
        collect_all_tokens = _c
    except Exception:                                        # noqa: BLE001
        n = None
        collect_all_tokens = None
    return n, collect_all_tokens

# Load environment variables
load_dotenv()

# Haus-Erweiterung (19.09.2026): Papier-Modus + Freigabesperre.
#   - PAPIER=True (Vorgabe): execute_allocations/handle_exits protokollieren
#     nur, es wird NICHTS gekauft oder verkauft.
#   - Freigabesperre: Agenten/Handel/moondev_trading_freigabe.json mit
#     {"handel_erlaubt": true} schaltet den Live-Weg frei. Ohne die Datei oder
#     bei false bleibt der Agent im Papier-Modus. Die Datei liegt im Haus, der
#     Repo-Klon traegt keine Freigabe.
PAPIER = True

def _freigabe_erlaubt():
    """True, wenn die Haus-Freigabedatei handel_erlaubt=true sagt."""
    try:
        pfad = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))),
            "Agenten", "Handel", "moondev_trading_freigabe.json")
        with open(pfad, encoding="utf-8") as f:
            return bool(json.load(f).get("handel_erlaubt", False))
    except Exception:                                        # noqa: BLE001
        return False


def _indikatoren(kerzen):
    """MA20/MA40/RSI/Volumen-Trend aus Close-Kerzen (deterministisch).

    Kerzen aufsteigend (aelteste zuerst). Liefert ein kompaktes dict, das
    ins Modell geht - nicht die rohen Kerzen (Kontextgrenze qwen35-8k).
    """
    if not kerzen:
        return {}
    try:
        schluesse = [float(k.get("c") or k.get("close")) for k in kerzen]
    except (TypeError, ValueError):
        return {}
    def mittelwerte(n):
        if len(schluesse) < n:
            return None
        return sum(schluesse[-n:]) / n
    ma20 = mittelwerte(20)
    ma40 = mittelwerte(40)
    kurs = schluesse[-1]
    hoch = max(schluesse[-24:]) if len(schluesse) >= 2 else kurs
    tief = min(schluesse[-24:]) if len(schluesse) >= 2 else kurs
    # Wilder-MA-RSI(14) ueber die letzten 15 Kurse (naeherungsweise)
    rsi = None
    if len(schluesse) >= 15:
        gewinne = verluste = 0.0
        for i in range(len(schluesse) - 14, len(schluesse)):
            diff = schluesse[i] - schluesse[i - 1]
            if diff > 0:
                gewinne += diff
            elif diff < 0:
                verluste += -diff
        if gewinne + verluste > 0:
            rsi = 100 - (100 / (1 + (gewinne / verluste)))
    volumen = [float(k.get("v") or k.get("volume") or 0) for k in kerzen]
    vol_summe = sum(volumen)
    vol_mitte = sum(volumen[-6:]) / max(len(volumen[-6:]), 1)
    vol_frueh = sum(volumen[:6]) / max(len(volumen[:6]), 1)
    trend_vol = (vol_mitte / vol_frueh - 1) if vol_frueh else None
    return {
        "kurs": kurs,
        "ma20": ma20, "ma40": ma40,
        "24h_hoch": hoch, "24h_tief": tief,
        "rsi14": round(rsi, 1) if rsi is not None else None,
        "kurs_zu_ma20": (kurs / ma20 - 1) if ma20 else None,
        "kurs_zu_ma40": (kurs / ma40 - 1) if ma40 else None,
        "volumen_trend_6zu6": round(trend_vol, 3) if trend_vol is not None else None,
        "volumen_summe": vol_summe,
        "kerzen_anzahl": len(schluesse),
    }


def _papier_marktdaten(anzahl_kerzen=48, zeitgrenze=30):
    """Marktdaten ohne Birdeye: MONITORED_TOKENS mit echten 1h-Kerzen.

    Die oeffentliche swap-api.pump.fun/v2/coins/<mint>/candles liefert echte
    OHLCV-Kerzen (open/high/low/close/volume) - daraus kann das Modell
    MA/RSI/Volume ableiten. Holen fuer jeden MONITORED_TOKEN (config);
    Tokens ohne Kerzen (tot, z. B. AI16Z/GG) werden uebersprungen. Kein
    Schluessel, keine Orders - nur Daten fuer den Papier-Analysis-Prompt.
    Analyse und Allocation sehen damit dieselben Tokens.
    """
    import time as _zeit
    aus = {}
    # Symbol-Map aus der coins-Liste (der Einzel-Meta-Endpoint ist 404).
    symbol_map = {}
    try:
        list_url = ("https://frontend-api-v3.pump.fun/coins"
                    "?offset=0&limit=200&sort=market_cap&order=DESC")
        lanfrage = urllib.request.Request(
            list_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(lanfrage, timeout=zeitgrenze) as lantwort:
            ldata = json.loads(lantwort.read().decode("utf-8", "replace"))
        lcs = ldata if isinstance(ldata, list) else (ldata.get("coins") or [])
        for lc in lcs:
            lm = (lc.get("mint") or "").strip()
            if lm:
                symbol_map[lm] = lc.get("symbol") or "?"
    except Exception:                                          # noqa: BLE001
        pass
    for mint in MONITORED_TOKENS:
        mint = (mint or "").strip()
        if (not mint) or mint == USDC_ADDRESS:
            continue
        try:
            kerzen_url = ("https://swap-api.pump.fun/v2/coins/%s/candles"
                          "?interval=1h&createdTs=%d"
                          % (mint, int(_zeit.time() * 1000)))
            anfrage = urllib.request.Request(
                kerzen_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(anfrage, timeout=zeitgrenze) as antwort:
                kerzen = json.loads(antwort.read().decode("utf-8", "replace"))
        except Exception:                                     # noqa: BLE001
            continue
        if not (isinstance(kerzen, list) and kerzen):
            continue                                    # Token ohne Historie
        kerzen = list(kerzen)[-anzahl_kerzen:]
        symbol = symbol_map.get(mint, "?")
        aus[mint] = {"symbol": symbol, "name": "?", "marktwert_usd": None}
        # Kerzen aufsteigend (aelteste zuerst) wie collect_token_data.
        kerzen = list(reversed(kerzen))
        aus[mint]["indikatoren"] = _indikatoren(kerzen)
        aus[mint]["ohlcv_letzte8"] = [{
            "o": k.get("open"), "h": k.get("high"),
            "l": k.get("low"), "c": k.get("close"),
            "v": k.get("volume"),
        } for k in kerzen[-8:]]
    return aus


class TradingAgent:
    def __init__(self):
        # Native Ollama-API (kein ANTHROPIC_KEY noetig). WICHTIG: der /v1-
        # OpenAI-Adapter ignoriert "think": false, qwen35 liefert dann einen
        # LEEREN content. Deshalb direkt POST an /api/chat mit think:false
        # (Haus-Muster llm_lokal.py, gemessen 19.09.2026).
        self.ollama_url = (os.getenv("OLLAMA_BASE_URL") or
                           "http://127.0.0.1:11434/api/chat").replace("/v1", "/api/chat")
        self.modell = os.getenv("OLLAMA_MODEL") or "qwen35-8k:latest"
        self.recommendations_df = pd.DataFrame(columns=['token', 'action', 'confidence', 'reasoning'])
        print("🤖 Moon Dev's LLM Trading Agent initialized! (Papier=%s, Modell=%s)"
              % (PAPIER, self.modell))

    def _chat_ollama(self, messages, max_tokens, temperature):
        """Ein nativer /api/chat-Aufruf; liefert den content-String (nie leer)."""
        koerper = json.dumps({
            "model": self.modell,
            "messages": messages,
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }).encode("utf-8")
        anfrage = urllib.request.Request(
            self.ollama_url, data=koerper,
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(anfrage, timeout=300) as antwort:
            roh = json.loads(antwort.read().decode("utf-8", "replace"))
        inhalt = (roh.get("message") or {}).get("content") or ""
        return inhalt.strip() or "NOTHING"

    def analyze_market_data(self, token, market_data):
        """Analyze market data using Claude"""
        try:
            # Skip analysis for excluded tokens
            if token in EXCLUDED_TOKENS:
                print(f"⚠️ Skipping analysis for excluded token: {token}")
                return None
            
            # Prepare strategy context
            strategy_context = ""
            if 'strategy_signals' in market_data:
                strategy_context = f"""
Strategy Signals Available:
{json.dumps(market_data['strategy_signals'], indent=2)}
                """
            else:
                strategy_context = "No strategy signals available."
            
            message = self._chat_ollama(
                max_tokens=AI_MAX_TOKENS,
                temperature=AI_TEMPERATURE,
                messages=[
                    {
                        "role": "user", 
                        "content": f"{TRADING_PROMPT.format(strategy_context=strategy_context)}\n\nMarket Data to Analyze:\n{market_data}"
                    }
                ]
            )
            
            # Parse the response - handle both string and list responses
            response = message
            if isinstance(response, list):
                # Extract text from TextBlock objects if present
                response = '\n'.join([
                    item.text if hasattr(item, 'text') else str(item)
                    for item in response
                ])
            
            lines = response.split('\n')
            action = lines[0].strip() if lines else "NOTHING"
            
            # Extract confidence from the response (assuming it's mentioned as a percentage)
            confidence = 0
            for line in lines:
                if 'confidence' in line.lower():
                    # Extract number from string like "Confidence: 75%"
                    try:
                        confidence = int(''.join(filter(str.isdigit, line)))
                    except:
                        confidence = 50  # Default if not found
            
            # Add to recommendations DataFrame with proper reasoning
            reasoning = '\n'.join(lines[1:]) if len(lines) > 1 else "No detailed reasoning provided"
            self.recommendations_df = pd.concat([
                self.recommendations_df,
                pd.DataFrame([{
                    'token': token,
                    'action': action,
                    'confidence': confidence,
                    'reasoning': reasoning
                }])
            ], ignore_index=True)
            
            print(f"🎯 Moon Dev's AI Analysis Complete for {token[:4]}!")
            return response
            
        except Exception as e:
            print(f"❌ Error in AI analysis: {str(e)}")
            # Still add to DataFrame even on error, but mark as NOTHING with 0 confidence
            self.recommendations_df = pd.concat([
                self.recommendations_df,
                pd.DataFrame([{
                    'token': token,
                    'action': "NOTHING",
                    'confidence': 0,
                    'reasoning': f"Error during analysis: {str(e)}"
                }])
            ], ignore_index=True)
            return None
    
    def allocate_portfolio(self):
        """Get AI-recommended portfolio allocation"""
        try:
            cprint("\n💰 Calculating optimal portfolio allocation...", "cyan")
            max_position_size = usd_size * (MAX_POSITION_PERCENTAGE / 100)
            cprint(f"🎯 Maximum position size: ${max_position_size:.2f} ({MAX_POSITION_PERCENTAGE}% of ${usd_size:.2f})", "cyan")
            
            # Get allocation from AI
            message = self._chat_ollama(
                max_tokens=AI_MAX_TOKENS,
                temperature=AI_TEMPERATURE,
                messages=[{
                    "role": "user", 
                    "content": f"""You are Moon Dev's Portfolio Allocation AI 🌙

Given:
- Total portfolio size: ${usd_size}
- Maximum position size: ${max_position_size} ({MAX_POSITION_PERCENTAGE}% of total)
- Minimum cash (USDC) buffer: {CASH_PERCENTAGE}%
- Available tokens: {MONITORED_TOKENS}
- USDC Address: {USDC_ADDRESS}

Provide a portfolio allocation that:
1. Never exceeds max position size per token
2. Maintains minimum cash buffer
3. Returns allocation as a JSON object with token addresses as keys and USD amounts as values
4. Uses exact USDC address: {USDC_ADDRESS} for cash allocation

Example format:
{{
    "token_address": amount_in_usd,
    "{USDC_ADDRESS}": remaining_cash_amount  # Use exact USDC address
}}"""
                }]
            )
            
            # Parse the response
            allocations = self.parse_allocation_response(message)
            if not allocations:
                return None
                
            # Fix USDC address if needed
            if "USDC_ADDRESS" in allocations:
                amount = allocations.pop("USDC_ADDRESS")
                allocations[USDC_ADDRESS] = amount
                
            # Validate allocation totals
            total_allocated = sum(allocations.values())
            if total_allocated > usd_size:
                cprint(f"❌ Total allocation ${total_allocated:.2f} exceeds portfolio size ${usd_size:.2f}", "red")
                return None
                
            # Print allocations
            cprint("\n📊 Portfolio Allocation:", "green")
            for token, amount in allocations.items():
                token_display = "USDC" if token == USDC_ADDRESS else token
                cprint(f"  • {token_display}: ${amount:.2f}", "green")
                
            return allocations
            
        except Exception as e:
            cprint(f"❌ Error in portfolio allocation: {str(e)}", "red")
            return None

    def execute_allocations(self, allocation_dict):
        """Execute the allocations using AI entry for each position"""
        try:
            print("\n🚀 Moon Dev executing portfolio allocations...")
            
            for token, amount in allocation_dict.items():
                # Skip USDC and other excluded tokens
                if token in EXCLUDED_TOKENS:
                    print(f"💵 Keeping ${amount:.2f} in {token}")
                    continue
                    
                print(f"\n🎯 Processing allocation for {token}...")

                # Haus-Sperre (19.09.2026): ohne Freigabe nicht kaufen. Steht
                # VOR dem n-Zugriff - n ist None ohne Birdeye, die
                # Balance-Abfrage wuerde sonst crashen, bevor die Sperre greift.
                if PAPIER or not _freigabe_erlaubt():
                    print(f"📝 PAPIER: wuerde {token} fuer ${amount:.2f} kaufen "
                          f"(Freigabe fehlt)")
                    continue

                try:
                    # Get current position value
                    current_position = n.get_token_balance_usd(token)
                    target_allocation = amount
                    
                    print(f"🎯 Target allocation: ${target_allocation:.2f} USD")
                    print(f"📊 Current position: ${current_position:.2f} USD")
                    
                    if current_position < target_allocation:
                        print(f"✨ Executing entry for {token}")
                        n.ai_entry(token, amount)
                        print(f"✅ Entry complete for {token}")
                    else:
                        print(f"⏸️ Position already at target size for {token}")
                    
                except Exception as e:
                    print(f"❌ Error executing entry for {token}: {str(e)}")
                
                time.sleep(2)  # Small delay between entries
                
        except Exception as e:
            print(f"❌ Error executing allocations: {str(e)}")
            print("🔧 Moon Dev suggests checking the logs and trying again!")

    def handle_exits(self):
        """Check and exit positions based on SELL or NOTHING recommendations"""
        cprint("\n🔄 Checking for positions to exit...", "white", "on_blue")
        
        for _, row in self.recommendations_df.iterrows():
            token = row['token']
            
            # Skip excluded tokens (USDC and SOL)
            if token in EXCLUDED_TOKENS:
                continue
                
            action = row['action']
            
            # Haus-Sperre (19.09.2026): ohne Freigabe nicht schliessen. Steht
            # VOR dem n-Zugriff - n ist None ohne Birdeye.
            if PAPIER or not _freigabe_erlaubt():
                cprint(f"📝 PAPIER: wuerde {token} schliessen (Freigabe fehlt)",
                       "white", "on_yellow")
                continue

            # Check if we have a position
            current_position = n.get_token_balance_usd(token)
            
            if current_position > 0 and action in ["SELL", "NOTHING"]:
                cprint(f"\n🚫 AI Agent recommends {action} for {token}", "white", "on_yellow")
                cprint(f"💰 Current position: ${current_position:.2f}", "white", "on_blue")
                try:
                    cprint(f"📉 Closing position with chunk_kill...", "white", "on_cyan")
                    n.chunk_kill(token, max_usd_order_size, slippage)
                    cprint(f"✅ Successfully closed position", "white", "on_green")
                except Exception as e:
                    cprint(f"❌ Error closing position: {str(e)}", "white", "on_red")
            elif current_position > 0:
                cprint(f"✨ Keeping position for {token} (${current_position:.2f}) - AI recommends {action}", "white", "on_blue")

    def parse_allocation_response(self, response):
        """Parse the AI's allocation response and handle both string and TextBlock formats"""
        try:
            # Handle TextBlock format from Claude 3
            if isinstance(response, list):
                response = response[0].text if hasattr(response[0], 'text') else str(response[0])
            
            print("🔍 Raw response received:")
            print(response)
            
            # Find the JSON block between curly braces
            start = response.find('{')
            end = response.rfind('}') + 1
            if start == -1 or end == 0:
                raise ValueError("No JSON object found in response")
            
            json_str = response[start:end]
            
            # More aggressive JSON cleaning
            json_str = (json_str
                .replace('\n', '')          # Remove newlines
                .replace('    ', '')        # Remove indentation
                .replace('\t', '')          # Remove tabs
                .replace('\\n', '')         # Remove escaped newlines
                .replace(' ', '')           # Remove all spaces
                .strip())                   # Remove leading/trailing whitespace
            
            print("\n🧹 Cleaned JSON string:")
            print(json_str)
            
            # Parse the cleaned JSON
            allocations = json.loads(json_str)
            
            print("\n📊 Parsed allocations:")
            for token, amount in allocations.items():
                print(f"  • {token}: ${amount}")
            
            # Validate amounts are numbers
            for token, amount in allocations.items():
                if not isinstance(amount, (int, float)):
                    raise ValueError(f"Invalid amount type for {token}: {type(amount)}")
                if amount < 0:
                    raise ValueError(f"Negative allocation for {token}: {amount}")
            
            return allocations
            
        except Exception as e:
            print(f"❌ Error parsing allocation response: {str(e)}")
            print("🔍 Raw response:")
            print(response)
            return None

    def parse_portfolio_allocation(self, allocation_text):
        """Parse portfolio allocation from text response"""
        try:
            # Clean up the response text
            cleaned_text = allocation_text.strip()
            if "```json" in cleaned_text:
                # Extract JSON from code block if present
                json_str = cleaned_text.split("```json")[1].split("```")[0]
            else:
                # Find the JSON object between curly braces
                start = cleaned_text.find('{')
                end = cleaned_text.rfind('}') + 1
                json_str = cleaned_text[start:end]
            
            # Parse the JSON
            allocations = json.loads(json_str)
            
            print("📊 Parsed allocations:")
            for token, amount in allocations.items():
                print(f"  • {token}: ${amount}")
            
            return allocations
            
        except json.JSONDecodeError as e:
            print(f"❌ Error parsing allocation JSON: {e}")
            print(f"🔍 Raw text received:\n{allocation_text}")
            return None
        except Exception as e:
            print(f"❌ Unexpected error parsing allocations: {e}")
            return None

    def run(self):
        """Run the trading agent (implements BaseAgent interface)"""
        self.run_trading_cycle()

    def run_trading_cycle(self, strategy_signals=None):
        """Run one complete trading cycle"""
        try:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cprint(f"\n⏰ AI Agent Run Starting at {current_time}", "white", "on_green")
            
            # Collect OHLCV data (Birdeye) oder Papier-Ersatz (Pump.fun)
            cprint("📊 Collecting market data...", "white", "on_blue")
            _lade_birdeye()
            market_data = {}
            if PAPIER or not _freigabe_erlaubt():
                # Papier: oeffentliche Pump.fun-Daten statt Birdeye.
                try:
                    market_data = _papier_marktdaten()
                    cprint(f"📊 Papier-Marktdaten: {len(market_data)} Launches "
                           f"(Pump.fun)", "white", "on_blue")
                except Exception:                            # noqa: BLE001
                    cprint("⚠️ Papier-Marktdaten fehlen (Pump.fun nicht erreichbar)",
                           "white", "on_yellow")
            else:
                try:
                    market_data = collect_all_tokens() if collect_all_tokens else {}
                except Exception:                            # noqa: BLE001
                    cprint("⚠️ Keine Marktdaten (Birdeye fehlt)",
                           "white", "on_yellow")
                    market_data = {}
            
            # Analyze each token's data
            for token, data in market_data.items():
                cprint(f"\n🤖 AI Agent Analyzing Token: {token}", "white", "on_green")
                
                # Include strategy signals in analysis if available
                if strategy_signals and token in strategy_signals:
                    cprint(f"📊 Including {len(strategy_signals[token])} strategy signals in analysis", "cyan")
                    data['strategy_signals'] = strategy_signals[token]
                
                analysis = self.analyze_market_data(token, data)
                print(f"\n📈 Analysis for contract: {token}")
                print(analysis)
                print("\n" + "="*50 + "\n")
            
            # Show recommendations summary
            cprint("\n📊 Moon Dev's Trading Recommendations:", "white", "on_blue")
            summary_df = self.recommendations_df[['token', 'action', 'confidence']].copy()
            print(summary_df.to_string(index=False))
            
            # Handle exits first
            self.handle_exits()
            
            # Then proceed with new allocations
            cprint("\n💰 Calculating optimal portfolio allocation...", "white", "on_blue")
            allocation = self.allocate_portfolio()
            
            if allocation:
                cprint("\n💼 Moon Dev's Portfolio Allocation:", "white", "on_blue")
                print(json.dumps(allocation, indent=4))
                
                cprint("\n🎯 Executing allocations...", "white", "on_blue")
                self.execute_allocations(allocation)
                cprint("\n✨ All allocations executed!", "white", "on_blue")
            else:
                cprint("\n⚠️ No allocations to execute!", "white", "on_yellow")
            
            # Clean up temp data
            cprint("\n🧹 Cleaning up temporary data...", "white", "on_blue")
            try:
                for file in os.listdir('temp_data'):
                    if file.endswith('_latest.csv'):
                        os.remove(os.path.join('temp_data', file))
                cprint("✨ Temp data cleaned successfully!", "white", "on_green")
            except Exception as e:
                cprint(f"⚠️ Error cleaning temp data: {str(e)}", "white", "on_yellow")
            
        except Exception as e:
            cprint(f"\n❌ Error in trading cycle: {str(e)}", "white", "on_red")
            cprint("🔧 Moon Dev suggests checking the logs and trying again!", "white", "on_blue")

def main():
    """Main function to run the trading agent every 15 minutes"""
    cprint("🌙 Moon Dev AI Trading System Starting Up! 🚀", "white", "on_blue")
    
    agent = TradingAgent()
    INTERVAL = SLEEP_BETWEEN_RUNS_MINUTES * 60  # Convert minutes to seconds
    
    while True:
        try:
            agent.run_trading_cycle()
            
            next_run = datetime.now() + timedelta(minutes=SLEEP_BETWEEN_RUNS_MINUTES)
            cprint(f"\n⏳ AI Agent run complete. Next run at {next_run.strftime('%Y-%m-%d %H:%M:%S')}", "white", "on_green")
            
            # Sleep until next interval
            time.sleep(INTERVAL)
                
        except KeyboardInterrupt:
            cprint("\n👋 Moon Dev AI Agent shutting down gracefully...", "white", "on_blue")
            break
        except Exception as e:
            cprint(f"\n❌ Error: {str(e)}", "white", "on_red")
            cprint("🔧 Moon Dev suggests checking the logs and trying again!", "white", "on_blue")
            # Still sleep and continue on error
            time.sleep(INTERVAL)

if __name__ == "__main__":
    main() 