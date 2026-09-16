"""Nachweis: die Moon-Dev-Agenten laufen ueber das lokale Ollama.

Prueft drei Dinge am lebenden System (Ollama auf 127.0.0.1:11434):

  1. Die ModelFactory bekommt eine Ollama-Verbindung und nennt das
     Standardmodell aus OLLAMA_MODEL (.env) - nicht das frueher verdrahtete
     "llama3.2", das hier nie installiert war.
  2. Ein echter Aufruf kommt beantwortet zurueck (kein Schluessel, kein Netz
     ausser localhost).
  3. Ein Agent, der einen bezahlten Anbieter anfragt (hier "claude", ohne
     Schluessel), faellt lokal weiter statt None zu bekommen.

Aufruf aus der Repo-Wurzel:
    .venv\Scripts\python.exe src\models\test_ollama_lokal.py
"""
import sys
from pathlib import Path

# Repo-Wurzel auf den Pfad, damit `src.models...` importierbar ist.
WURZEL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(WURZEL))

from src.models.model_factory import ModelFactory  # noqa: E402

FRAGE = "Antworte nur mit dem Wort PONG."
SYSTEM = "Du bist ein knapper Testassistent. Antworte mit genau einem Wort."


def main():
    fabrik = ModelFactory()

    assert "ollama" in fabrik._models, (
        "Keine Ollama-Verbindung - laeuft der Dienst auf 127.0.0.1:11434?")
    lokal = fabrik._models["ollama"]
    print("\n[1] Standardmodell: %s" % lokal.model_name)
    assert not lokal.model_name.startswith("llama3.2"), \
        "Es steht noch das alte Standardmodell llama3.2 in der Config"

    antwort = lokal.generate_response(SYSTEM, FRAGE, temperature=0.0)
    print("[2] Antwort auf %r: %r" % (FRAGE, antwort))
    assert antwort and antwort.strip(), "Leere Antwort vom lokalen Modell"
    assert "PONG" in antwort.upper(), "Antwort ohne PONG: %r" % antwort

    ersatz = fabrik.get_model("claude", "claude-3-haiku-20240307")
    print("[3] Rueckfall fuer 'claude': %s" % ersatz)
    assert ersatz is not None, "Kein Rueckfall - Aufruf waere gescheitert"
    assert ersatz.model_type == "ollama", \
        "Rueckfall zeigt nicht auf Ollama: %s" % ersatz.model_type

    print("\nAlles gruen: die Agenten laufen lokal ueber Ollama/%s." % lokal.model_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
