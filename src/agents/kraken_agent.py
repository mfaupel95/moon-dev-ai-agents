"""
🌙 Moon Dev KRAKEN Agent 🔵

Kraken an den Moon-Dev-Stack anbinden (16.09.2026, Max):
- Daten: OEFFENTLICHE Kraken-API, kein Schluessel noetig: AssetPairs
  (quote=ZEUR) + Ticker (last/open/24h-Volumen) als Stapelabruf.
- Urteil: lokales Ollama (qwen35-8k), OpenAI-kompatible API - derselbe
  Weg wie in new_or_top_agent (OLLAMA_MODEL/OLLAMA_BASE_URL aus .env,
  base_url /api->/v1). Kein bezahlter Anbieter, kein Orderpfad.
- Ambition: die EUR-Paare sind dieselben, die die Haus-Spur kraken in
  Agenten/Handel beobachtet; dieser Agent gibt dazu ein zweites Urteil
  vom Sprachmodell - rein zur Beobachtung.

Starten (aus dem Repo-Root, .env-Werte kommen aus der Datei):
    python -m src.agents.kraken_agent
Laeuft als Dauerlaeufer mit stuendlichem Zyklus; Abbruch mit Strg+C.
"""

import os
import time
from datetime import datetime
from typing import Dict, List

import requests
from termcolor import cprint

# ---------------------------------------------------------------- Konfiguration

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL") or "qwen35-8k:latest"
OLLAMA_BASE = (os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434/v1").replace("/api", "/v1")
KRAKEN = "https://api.kraken.com/0/public"
KOPF = {"User-Agent": "MoonDev-kraken-agent/1.0 (BrainFiles)"}
ANZAHL_URTEILE = 5          # Wieviele Paare je Zyklus vom LLM bewertet werden
MIN_VOLUMEN_EUR = 500_000   # Kleinstpaare (0,10-EUR-Kurse) ausfiltern: erst ab
                             # 500k EUR 24h-Umsatz gilt ein Paar als liquide
MIN_KURS_EUR = 0.5            # Pennystocks unter 50 Cent bleiben aussen vor
VERZOEGERUNG = 3600          # Sekunden zwischen zwei Zyklen

PROMPT = """Du bist ein Kraken-Analyst. Bewerte dieses EUR-Handelspaar an der Boerse Kraken.

Paar: {paar}
Kurs: {kurs} EUR
24h-Aenderung: {aenderung:+.2f} %
24h-Spanne: {tief} .. {hoch} EUR
24h-Volumen: {volumen:.0f} {basis}

Antworte NUR mit genau zwei Zeilen:
RECOMMENDATION: BUY|SELL|DO NOTHING
CONFIDENCE: 0-100
"""


# ---------------------------------------------------------------- Kraken-Daten

def kraken_roe_oeffentlich(methode: str, **parameter):
    """Kraken public Endpunkt; Fehler werden geworfen, nicht geraten."""
    url = "%s/%s" % (KRAKEN, methode)
    if parameter:
        url += "?" + "&".join("%s=%s" % (k, v) for k, v in parameter.items())
    antwort = requests.get(url, headers=KOPF, timeout=20)
    antwort.raise_for_status()
    daten = antwort.json()
    if daten.get("error"):
        raise RuntimeError("Kraken: " + "; ".join(daten["error"]))
    return daten.get("result") or {}


def eur_paare() -> List[str]:
    """Alle handelbaren EUR-Paare von Kraken, sortiert."""
    d = kraken_roe_oeffentlich("AssetPairs")
    return sorted(name for name, w in d.items()
                  if w.get("quote") == "ZEUR" and w.get("status", "online") == "online")


def ticker_stand(paare: List[str]) -> Dict[str, dict]:
    """last/open/hoch/tief/volumen24h je Paar aus einem Stapelabruf."""
    ergebnis = {}
    for i in range(0, len(paare), 40):          # Kraken nimmt ~50 je Abruf
        teil = paare[i:i + 40]
        d = kraken_roe_oeffentlich("Ticker", pair=",".join(teil))
        for name, w in d.items():
            try:
                letzter = float(w["c"][0])
                offen = float(w["o"])
                ergebnis[name] = {
                    "kurs": letzter,
                    "aenderung": (letzter / offen - 1.0) * 100.0 if offen else 0.0,
                    "hoch": float(w["h"][1]),
                    "tief": float(w["l"][1]),
                    "volumen": float(w["v"][1]),
                    "basis": name.lstrip("X")[:4],
                }
            except (KeyError, TypeError, ValueError):
                continue
    return ergebnis


# ---------------------------------------------------------------- LLM-Urteil

def llm_lokal(prompt):
    """Native Ollama-API (/api/chat, think:false). Der OpenAI-/v1-Weg liefert
    bei qwen35-8k einen LEEREN content (das Modell denkt immer und legt die
    Antwort in 'reasoning' ab) - gemessen 16.09.2026; /api/chat mit
    think:false antwortet dafuer zuverlaessig. Nur Standardbibliothek."""
    import json
    import urllib.request
    koerper = json.dumps({
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "options": {"temperature": 0.2, "num_predict": 60},
    }).encode("utf-8")
    anfrage = urllib.request.Request(
        OLLAMA_BASE.replace("/v1", "") + "/api/chat", data=koerper,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(anfrage, timeout=120) as antwort:
        daten = json.loads(antwort.read().decode("utf-8", "replace"))
    return (daten.get("message") or {}).get("content") or ""


def urteil_holen(paar: str, stand: dict):
    """Lokales Ollama-Urteil. Unlesbare Antwort = nichts."""
    try:
        text = llm_lokal(PROMPT.format(
            paar=paar, kurs=stand["kurs"], aenderung=stand["aenderung"],
            tief=stand["tief"], hoch=stand["hoch"],
            volumen=stand["volumen"], basis=stand.get("basis", ""))).strip()
    except Exception as e:                                        # noqa: BLE001
        return "DO NOTHING", 0, "LLM-Fehler: %s" % e

    empfehlung = "DO NOTHING"
    for zeile in text.splitlines():
        z = zeile.strip().upper()
        if "RECOMMENDATION" in z:
            for k in ("BUY", "SELL"):
                if k in z:
                    empfehlung = k
                    break
            break
    confidence = 0
    for zeile in text.splitlines():
        z = zeile.strip().upper()
        if "CONFIDENCE" in z:
            try:
                confidence = int("".join(ch for ch in z if ch.isdigit())[:3] or 0)
            except (ValueError, IndexError):
                confidence = 0
            break
    return empfehlung, confidence, text.replace("\n", " ")[:90]


# ---------------------------------------------------------------- Zyklus

def farben_fuer(empfehlung):
    if empfehlung == "BUY":
        return "white", "on_green"
    if empfehlung == "SELL":
        return "white", "on_red"
    return "yellow", "on_grey"


def ein_zyklus():
    cprint("\n🌙 Moon Dev KRAKEN Agent - Zyklus %s"
           % datetime.now().strftime("%d.%m. %H:%M"), "white", "on_blue")
    paare = eur_paare()
    cprint("EUR-Paare gefunden: %d" % len(paare), "cyan", "on_grey")
    stände = ticker_stand(paare)
    liquide = {k: v for k, v in stände.items()
               if (v["kurs"] * v["volumen"] >= MIN_VOLUMEN_EUR
                  and v["kurs"] >= MIN_KURS_EUR)}
    uebersprungen = len(stände) - len(liquide)
    stände = liquide
    if not stände:
        cprint("❌ keine liquiden Ticker-Daten", "white", "on_red")
        return
    if uebersprungen:
        cprint("(%d Paare unter %d EUR 24h-Umsatz uebersprungen)"
               % (uebersprungen, MIN_VOLUMEN_EUR), "grey", "on_grey")

    # Die bewegtsten Paare zuerst: das LLM urteilt nur ueber die, die etwas
    # getan haben - stille Paare brauchen kein Modell.
    sortiert = sorted(stände.items(), key=lambda kv: abs(kv[1]["aenderung"]),
                      reverse=True)[:ANZAHL_URTEILE]

    for name, stand in sortiert:
        aend = stand["aenderung"]
        marker = "📈" if aend >= 1.0 else ("📉" if aend <= -1.0 else "➖")
        cprint("  %-10s %12.2f EUR  %+6.2f %%  %s"
               % (name, stand["kurs"], aend, marker), "white", "on_grey")
        empfehlung, conf, roh = urteil_holen(name, stand)
        if empfehlung != "DO NOTHING":
            cprint("    → %s (Confidence %d)  %s" % (empfehlung, conf, roh),
                   *farben_fuer(empfehlung))
        else:
            cprint("    → DO NOTHING (Confidence %d)" % conf, *farben_fuer(empfehlung))
        time.sleep(1)          # Feingefuehl gegenueber Kraken

    cprint("Zyklus fertig - naechster in 60 Minuten.", "cyan", "on_grey")


def main():
    print("🌙 Moon Dev KRAKEN Agent - Kraken angebunden (16.09.2026)")
    print("   Modell: %s  |  Boerse: Kraken EUR-Paare (oeffentlich, kein Key)" % OLLAMA_MODEL)
    try:
        while True:
            ein_zyklus()
            for _ in range(12):
                time.sleep(VERZOEGERUNG // 12)
    except KeyboardInterrupt:
        print("\n👋 gestoppt.")


if __name__ == "__main__":
    main()