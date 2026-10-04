"""Hängende Netzaufrufe abbrechen, damit der Treiber den Agenten neu startet.

ANLASS (T-260): Der `kraken_agent` lief am 29.09.2026 18:20 bis zum Neustart am
01.10.2026 00:45 als Prozess weiter und schrieb keine einzige Zeile - das Log
endete mitten in einer normalen Runde, ohne Traceback. `timeout=120` in
`llm_lokal()` wirkt dabei nicht: wenn Ollama oder das OS-Netz einfriert, steckt
der Aufruf im Syscall und der Timeout greift nicht.

WARUM NICHT `threading.Timer` MIT `raise` (der Vorschlag in TASKS.md):
gemessen am 04.10.2026 - die Exception entsteht im Timer-THREAD, der
main-Thread laeuft weiter und macht den naechsten Zyklus. Ein Timer kann einen
anderen Thread nicht beenden; `_raise` erzeugt nur eine unbenutzte Traceback in
der Thread-Ausgabe (Beleg: /tmp wd_test.py, Hauptthread lebte weiter).

FUNKTIONIERENDE FORM: der Timer ruft `os._exit()` auf - das beendet den GANZEN
Prozess (alle Threads, keine Puffer, keine `finally`-Bloecke). Exit-Code 1 ist
bewusst: der Haus-Treiber (`moondev_dauerlauf.zyklus`) protokolliert einen
Absturz mit dem Log-Tail nur, wenn der Code weder None noch 0 ist - ein
beendeter Agent, der mit 0 herausgeht, saehe wie ein sauberer Lauf aus.

Nutzung:

    with begrenze_zyklus("kraken", ZYKLUS_GRENZE_S):
        ein_zyklus()

oder manuell:

    uhr = ZyklusUhr("kraken", ZYKLUS_GRENZE_S).starten()
    try:
        ein_zyklus()
    finally:
        uhr.anhalten()

`ZYKLUS_GRENZE_S` wird nicht geraten, sondern aus dem Zeitbudget hergeleitet
(siehe `budget_s`): LLM-Timeout x ANZAHL_URTEILE plus Reserve. Ein Watchdog, der
lange laufen darf als sein Zyklus, haengt genau so lange mit.
"""

from __future__ import annotations

import os
import sys
import threading
import time

# Reserve ueber dem eigenen Zeitbudget des Zyklus. Muss gross genug sein, dass
# ein GESUNDER Lauf nicht abgeschossen wird: ein zu enger Watchdog ist schlimmer
# als keiner, weil er Dauerbetrieb in eine Neustartschleife verwandelt.
RESERVE_FAKTOR = 4
MIN_GRENZE_S = 120          # nie unter zwei Minuten - der Start braucht schon 20 s


def _jetzt() -> float:
    return time.monotonic()


def budget_s(zeitbudget_s: float) -> float:
    """Watchdog-Schwelle aus dem Zeitbudget des Zyklus herleiten."""
    return max(MIN_GRENZE_S, float(zeitbudget_s) * RESERVE_FAKTOR)


class ZyklusUhr:
    """Timer, der den Prozess beendet, wenn der Zyklus zu lang dauert."""

    def __init__(self, name: str, grenze_s: float, melder=None):
        self.name = name
        self.grenze_s = float(grenze_s)
        self.start = _jetzt()
        self._timer: threading.Timer | None = None
        self._ausgeloest = False
        self._melder = melder or _standard_melder

    # -- Zustand ------------------------------------------------------------
    @property
    def laeuft(self) -> bool:
        """FALSE, sobald der Watchdog gefeuert hat."""
        return not self._ausgeloest

    def verbleibend_s(self) -> float:
        """Restzeit bis zum Abbruch (<= 0 heisst: Grenze erreicht oder
        ueberschritten)."""
        return self.grenze_s - (_jetzt() - self.start)

    def ueberfaellig(self) -> bool:
        """TRUE, wenn der Zyklus sein Budget ueberschritten hat - fuer eine
        UEBERWACHUNG ohne Abbruch."""
        return self.verbleibend_s() <= 0

    # -- Laufzeit -----------------------------------------------------------
    def starten(self) -> "ZyklusUhr":
        if self._timer is not None:
            raise RuntimeError("Uhr '%s' laeuft schon" % self.name)
        self._timer = threading.Timer(self.grenze_s, self._feuer)
        self._timer.daemon = True
        self._timer.start()
        return self

    def anhalten(self) -> None:
        """Timer loeschen (nach dem Zyklus)."""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _feuer(self) -> None:
        if self._ausgeloest:
            return
        self._ausgeloest = True
        self._melder(self.name, self.grenze_s)
        # Ganzer Prozess, nicht nur der Timer-Thread: ein haengender Syscall
        # laesst sich aus der Hand nicht mehr nehmen.
        sys.stderr.flush()
        sys.stdout.flush()
        os._exit(1)


def _standard_melder(name: str, grenze_s: float) -> None:
    sys.stderr.write(
        "\n[watchdog] %s: Zyklus laeuft ueber der Grenze %.0f s - Abbruch, "
        "der Treiber startet neu (T-260)\n" % (name, grenze_s))
    sys.stderr.flush()


class begrenze_zyklus:
    """Kontextmanager: `with begrenze_zyklus("kraken", 900): ein_zyklus()`."""

    def __init__(self, name: str, zeitbudget_s: float = 900.0,
                 grenze_s: float | None = None, melder=None):
        self.uhr = ZyklusUhr(name, grenze_s if grenze_s is not None
                            else budget_s(zeitbudget_s), melder)

    def __enter__(self) -> ZyklusUhr:
        return self.uhr.starten()

    def __exit__(self, *_) -> bool:
        self.uhr.anhalten()
        return False


if __name__ == "__main__":
    # Selbsttest ohne Netz - belegt beides:
    #   zu lang   -> Exit-Code 1 (Abbruch hat gewirkt)
    #   zu kurz   -> Exit-Code 0 (der Timer hat NICHT geschossen)
    import sys as _s
    arg = _s.argv[1] if len(_s.argv) > 1 else "lang"
    dauer, grenze = (5.0, 1.0) if arg == "lang" else (0.2, 30.0)
    print("Selbsttest '%s': Zyklus %.1f s, Grenze %.1f s" % (arg, dauer, grenze),
          flush=True)
    with begrenze_zyklus("selbsttest", grenze_s=grenze):
        time.sleep(dauer)
    print("Selbsttest '%s' ok - der Zyklus blieb unter der Grenze" % arg)
    _s.exit(0)
