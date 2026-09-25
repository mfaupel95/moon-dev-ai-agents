"""Wie ein erzeugter Backtest hier ausgefuehrt wird.

Die Original-Skripte riefen hart `conda run -n tflow python <datei>` auf. Auf
diesem Rechner gibt es kein conda (gemessen 25.09.2026) - und es braucht auch
keins: pandas, numpy und backtesting liegen im venv des Repos, mehr importiert
kein erzeugtes Backtest-Skript. Deshalb wird der Interpreter genommen, der den
Agenten gerade ausfuehrt.

Zweiter Stolperstein ist der Datenpfad: die Prompt-Vorlagen trugen den Pfad des
Autors (`/Users/md/...`). Hier liegt die Kursdatei unter src/data/rbi/.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
KURS_DATEI = REPO / "src" / "data" / "rbi" / "BTC-USD-15m.csv"
KONDA_ENV = "tflow"   # nur noch, falls jemand das Repo mit conda faehrt


def interpreter(datei) -> list:
    """Befehl zum Ausfuehren eines erzeugten Backtests.

    Der venv-Interpreter laeuft hier nachweislich (SimpleMomentumCross_BT.py,
    25.09.2026). Steht conda doch zur Verfuegung UND ist die Umgebung da, wird
    sie genommen - sonst der eigene Interpreter.
    """
    return [sys.executable, "-u", str(datei)]


def daten_pfad() -> str:
    """Der lokale Kursdatensatz, den die Prompts nennen muessen."""
    return str(KURS_DATEI)
