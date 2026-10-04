"""T-262: GUI-Kinder im gemeinsamen Registrierungsordner eintragen.

Der TASK-Vorschlag lautete: in `kind_umgebung()` (oder direkt nach Popen)
`from moondev_reg import registriere; registriere()` aufrufen. Das ist an der
genannten Stelle FALSCH und an der zweiten Stelle halb:

1. `kind_umgebung()` baut nur ein DICT fuer die Kindumgebung - dort kann man
   keinen Prozess registrieren, es laeuft gar kein Code.
2. `registriere()` ohne Argument registriert die PID des AUFRUFENDEN Prozesses,
   also die GUI. Geschuetzt waere dann das Fenster - nicht der Agent, den die
   GUI startet. Genau der wird vom Waisenputzer des Hauses nach 300 s beendet
   (das ist der gemeldete Fehler).

RICHTIG: Der Waisenputzer schuetzt nicht nur die exakte PID. `_baum()` nimmt
den ganzen Prozessbaum ueber ParentProcessId. Registriert wird deshalb die
PID des Kindes; ein Enkel darunter (venv-Startprogramm -> Interpreter) fällt
mit.

Diese Datei ist eine Kopie des Haus-Wegzeugs
`Agenten/Handel/moondev_reg.py` (identisch bis auf dieses Docstring-Bild und den
Pfadkommentar). Sie ist bewusst eine KOPIE und kein Import: das Fremd-Repo
darf nicht vom Hausverzeichnis abhaengig sein - die GUI laeuft auch dann, wenn
`Agenten/Handel/` nicht vorhanden ist.

Gegenprobe im `__main__`: registriert, alle PIDs gelesen, unregistriert.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

# Gemeinsamer Ordner mit dem Haus-Treiber (moondev_dauerlauf.py liest ihn):
#   $TEMP/moondev_agenten/<pid>.moon
# Windows: %TEMP%. Mehrere Prozesse schreiben gleichzeitig; jeder nur seine
# eigene Datei, also keine Kollision.
_TEMP = (os.getenv("TEMP") or os.getenv("TMP")
         or os.path.expanduser("~") + "\\AppData\\Local\\Temp")
ORDNER = Path(_TEMP) / "moondev_agenten"


def _pid_datei(pid: int | None = None) -> Path:
    return ORDNER / ("%d.moon" % (pid if pid is not None else os.getpid()))


def registriere(pid: int | None = None) -> Path:
    """PID in den gemeinsamen Ordner eintragen; gibt den Pfad zurueck.

    `pid` wird von der GUI benutzt: sie registriert das KIND, nicht sich
    selbst. Ohne Argument (Agentenaufruf) ist es die eigene PID.
    """
    ziel = pid if pid is not None else os.getpid()
    try:
        ORDNER.mkdir(parents=True, exist_ok=True)
        _pid_datei(ziel).write_text(
            "pid=%d\nstart=%.3f\n" % (ziel, time.time()), encoding="utf-8")
    except OSError:
        return _pid_datei(ziel)   # Agent stirbt ohne Registrierung, das ist ok
    return _pid_datei(ziel)


def abmelde(pid: int | None = None) -> None:
    """Eintrag entfernen - beim geordneten Stopp, damit keine Leichen bleiben.

    Ein beendeter Prozess wird ohne diese Funktion als 'registriert' weiter
    gefuehrt; die PID wird irgendwann neu vergeben und der Treiber schuetzt
    dann einen Fremden. Der Haus-Treiber prueft die PID UND liest die Start-
    zeit, ein alter Eintrag faellt also auf - sauberer ist aber abmelden.
    """
    try:
        _pid_datei(pid).unlink(missing_ok=True)
    except OSError:
        pass


def alle_registrierte_pids() -> set:
    """Alle PIDs, die sich im gemeinsamen Ordner eingetragen haben."""
    ergebnis: set = set()
    if not ORDNER.is_dir():
        return ergebnis
    for p in ORDNER.glob("*.moon"):
        try:
            zeilen = p.read_text(encoding="utf-8", errors="replace").splitlines()
            if zeilen and zeilen[0].startswith("pid="):
                ergebnis.add(int(zeilen[0].split("=", 1)[1]))
        except (OSError, ValueError, IndexError):
            continue
    return ergebnis


if __name__ == "__main__":
    pfad = registriere()
    print("Registriert als PID %d - Datei: %s" % (os.getpid(), pfad))
    print("Alle registrierten PIDs:", sorted(alle_registrierte_pids()))
    assert os.getpid() in alle_registrierte_pids(), "eigene PID fehlt"
    abmelde()
    print("Abgemeldet - eigene PID noch da?",
          os.getpid() in alle_registrierte_pids())
