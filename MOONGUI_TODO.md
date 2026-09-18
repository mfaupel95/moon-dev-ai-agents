# MoonDev-GUI — To-do

Stand: 18.09.2026. Offene Punkte und Ideen rund um
Werkstatt/Repos/moon-dev-ai-agents/moongui.py (Schaltzentrale:
Boersen, Orderflaeche, Wallet, Agenten, RBI-Swarm, LLM, READMEs).

## Offen
- [ ] Zwei Autostart-Wege: die geplante Aufgabe MaxHirn-MoonDev-GUI
      UND die Startup-Verknuepfung MoonDev-GUI.vbs rufen denselben
      Wrapper. Der erkennt eine laufende GUI und tut nichts
      ('laeuft schon' im Wrapper-Log und im Bus-Journal) - doppelt ist
      es trotzdem, einer der beiden Wege sollte gehen.

- [ ] Cloud-Keys aktivieren: GUI-LLM-Umschalter auf "Cloud-Key" stellen
      (OPENAI_KEY/ANTHROPIC_KEY/DEEPSEEK_KEY in der Repo-.env fehlen noch)
      => dann laufen auch whale_agent, sniper_agent, copybot_agent,
         trading_agent, million_agent, research_agent, focus_agent
- [ ] RBI-Laeufer laufen lokal (qwen35-8k) aber langsam:
      Research->Backtest->Implement dauert viele Minuten je Idee;
      ggf. OLLAMA_MODEL auf qwen36-35b-a3b (groesser, langsamer) stellen
      oder Ideen-Filter einbauen
- [ ] Order-Schutzlimits pruefen (aktuell 0.0002 BTC OKX / 0.001 XBT
      Kraken / 0.0005 BTC Binance): nur hochsetzen wenn Live-Betrieb
      mit groesseren Betraegen geplant ist

## Erledigt
- [x] GUI gebaut (moongui.py, 7 Tabs: Boersen, Orderflaeche, Wallet,
      Agenten, RBI-Swarm, LLM, READMEs)
- [x] Boersen-Anbindung OKX/Kraken/Binance (read-only, echte Ticker)
- [x] Solana-Wallet-Balance (public RPC, keine Keys)
- [x] Agenten-Tab: 30 Module starten/stoppen (python -m src.agents.<mod>)
- [x] RBI-Swarm-Tab: Kennzahlen, Strategieordner, Ideen anhaengen,
      Laeufer starten
- [x] README-Tab: alle 22 READMEs des Repos durchblaettern
- [x] LLM-Umschalter: lokal/Ollama vs. Cloud-Key (schreibt OLLAMA_MODEL/
      OLLAMA_BASE_URL in die .env)
- [x] RBI-Laeufer auf lokale Ollama-Modelle umgestellt (rbi_agent.py:
      RESEARCH/BACKTEST/DEBUG/PACKAGE_CONFIG -> ollama/qwen35-8k;
      ollama_model.py: URL-Normalisierung /api vs /v1)
- [x] Autostart-Wrapper (Agenten\Routinen\moondev-gui.ps1) + Startup-
      Verknuepfung MoonDev-GUI.vbs - ohne Admin, das ist der Weg, der die
      GUI seit dem 17.09. wirklich startet; der Wrapper meldet an den Bus
      (routine/moondev-gui) und erkennt eine schon laufende GUI
- [x] Geplante Aufgabe MaxHirn-MoonDev-GUI, registriert am 18.09.2026
      (Anmeldung +2 Min, MultipleInstances IgnoreNew, StartWhenAvailable,
      RunLevel Limited; einmal ausgeloest, Ergebniscode 0)
      ACHTUNG: die Registrierung BRAUCHT Erhoehung - der erste Versuch am
      17.09.2026 um 00:51 endete mit 'Zugriff verweigert'
      (Beleg Agenten\Routinen\logs\moondev-gui-aufgabe.log). Deshalb stand
      hier bis zum 18.09.2026 ein [x] fuer einen Task, den es nicht gab.