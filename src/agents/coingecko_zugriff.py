"""CoinGecko-Zugriff mit 429-Backoff, fuer `new_or_top_agent` (T-261).

ANLASS (T-261): Im Log des Agenten stehen 6x "No market data available" und
zwei AI-Timeouts; gespeichert wurden Analysen (Namecoin, Primecoin), die ohne
echte Daten entstanden sind.

GEMESSENE URSACHE am 04.10.2026 ohne Pro-Key: die oeffentliche CoinGecko-API
gibt rund fuenf Aufrufe je Minute frei, danach antwortet sie mit 429 und
`Retry-After: 60` (Beleg: /tmp t261_limit.py - 5x 200, dann 429 nach 14 s).
Ein Zyklus des Agenten braucht 2 Listenabrufe plus 2 je Coin - er laeuft also
planmaessig ins Limit. Der alte Code im Agenten pruefte 429 nur einmal, tat
nach 15 s einen zweiten Versuch und verarbeitete danach die LEERE Antwort
weiter: `market_data_df` blieb unset, `analyze_coin()` speicherte trotzdem.

DIE DREI REGELN, die dieses Modul durchsetzt:
1. Ein 429 wird befolgt (Retry-After), aber gedeckelt - der Agent soll einen
   langsamen Zyklus haben, keinen haengenden. Der Treiber killt nach 300 s
   Schonfrist die GUI-Kinder; ein 600-s-Warteblock waere genau das.
2. Bleibt das Limit nach allen Versuchen bestehen, kommt `None` zurueck. Der
   Aufrufer VERWORF den Zyklus - es wird nichts gespeichert. Lieber eine
   leere Stunde als eine erfundene Empfehlung.
3. Jeder Aufruf hat einen eigenen Timeout. Ohne Timeout haengt `requests` bei
   eingefrorenem DNS oder Netz genauso wie der LLM-Aufruf (T-260).
"""

from __future__ import annotations

import time

import requests

# Versuche NACH dem ersten: [0] sofort, dann diese Wartezeiten als Rueckfall.
FRISTS = (20, 45, 90)          # s
FRIST_MAX_S = 120             # s: Deckel fuer ein unverschaemt langes Retry-After
NETTO_FRIST_S = 25            # s: eigener HTTP-Timeout
HEADER = {"User-Agent": "moondev-newortop/1.0 (BrainFiles)"}

# Echtheitszeichen fuer "hat Marktdaten": analyze_coin() verlangt genau das,
# bevor es eine Empfehlung schreibt. Ein leerer oder fehlender Wert heisst
# "keine Analyse" (T-261) - nicht "Analyse mit Default".
DATEN_SCHLUESSEL = "price"


class Zugriff:
    """Datenquelle mit Backoff. `kopf` traegt den Pro-Key, falls vorhanden."""

    def __init__(self, basis: str, api_key: str | None = None,
                 fristen=FRISTS, melder=None):
        self.basis = basis.rstrip("/")
        self.kopf = dict(HEADER)
        if api_key:
            self.kopf["x-cg-pro-api-key"] = api_key
        self.fristen = tuple(fristen)
        self._melder = melder or (lambda text: print(text))
        self.aufrufe = 0
        self.ratenlimits = 0

    # -- Meldungen ----------------------------------------------------------
    def _melde(self, text: str) -> None:
        try:
            self._melder(text)
        except Exception:                                        # noqa: BLE001
            pass  # eine kaputte Meldung darf den Zyklus nicht kippen

    # -- Zugriff ------------------------------------------------------------
    def hole(self, pfad: str, params: dict) -> dict | None:
        """GET gegen die Basis-URL. Liefert das JSON-Dict oder None.

        None heisst: Rate-Limit, Netzfehler oder unerwarteter Code. Der
        Aufrufer muss den Zyklus dann verwerfen - kein Teil-Ergebnis.
        """
        url = self.basis + pfad
        letzter = ""
        for versuch, wartezeit in enumerate((0,) + self.fristen):
            if wartezeit:
                time.sleep(wartezeit)
            try:
                antwort = requests.get(url, params=params, timeout=NETTO_FRIST_S,
                                        headers=self.kopf)
            except Exception as e:                                # noqa: BLE001
                self._melde(f"HTTP-Fehler {pfad}: {e}")
                return None
            self.aufrufe += 1
            if antwort.status_code == 200:
                try:
                    return antwort.json()
                except ValueError:
                    self._melde(f"HTTP 200 {pfad}, aber keine JSON-Antwort")
                    return None
            if antwort.status_code == 429:
                self.ratenlimits += 1
                letzter = str(antwort.headers.get("Retry-After") or wartezeit or "")
                if versuch >= len(self.fristen):
                    self._melde(
                        "Rate-Limit bleibt nach %d Versuchen (Retry-After %s) - "
                        "Zyklus wird verworfen, nichts wird gespeichert (T-261)"
                        % (versuch + 1, letzter or "?"))
                    return None
                self._melde("Rate-Limit 429 - warte %0.0f s (Versuch %d/%d)"
                            % (_wartezeit(letzter, wartezeit), versuch + 1,
                               len(self.fristen)))
                continue
            self._melde("HTTP %d %s: %s"
                        % (antwort.status_code, pfad, antwort.text[:120]))
            return None
        return None


def _wartezeit(retry_after: str, rueckfall: float) -> float:
    """Wartezeit aus dem Retry-After, gedeckelt; sonst der eigene Rueckfall."""
    try:
        wert = float(retry_after)
    except (TypeError, ValueError):
        wert = float(rueckfall or FRISTS[0])
    return max(1.0, min(wert, FRIST_MAX_S))


def hat_marktdaten(coin: dict) -> bool:
    """TRUE nur bei echten Marktdaten.

    Geprueft wird der Kurs: 0, None und fehlende Schluessel sind "keine Daten".
    `analyze_coin()` ruft das VOR dem LLM - so entsteht keine Analyse mehr,
    die auf nichts beruht (T-261).
    """
    if not isinstance(coin, dict):
        return False
    md = coin.get("market_data")
    if not isinstance(md, dict):
        return False
    preis = (md.get("current_price") or {}).get("usd")
    try:
        return preis is not None and float(preis) > 0
    except (TypeError, ValueError):
        return False


if __name__ == "__main__":
    import json  # noqa: PLC0415
    import sys  # noqa: PLC0415

    z = Zugriff("https://api.coingecko.com/api/v3")
    d = z.hole("/coins/markets", {"vs_currency": "usd", "order": "market_cap_desc",
                                   "per_page": "3", "sparkline": "false",
                                   "price_change_percentage": "24h"})
    if d is None:
        print("Ergebnis: None (Zyklus verwerfen) - Aufrufe %d, Rate-Limits %d"
              % (z.aufrufe, z.ratenlimits))
        sys.exit(1)
    print("Ergebnis: %d Eintraege, Aufrufe %d, Rate-Limits %d"
          % (len(d), z.aufrufe, z.ratenlimits))
    # Gegenprobe hat_marktdaten: mit Daten / ohne / Nullkurs / kaputt
    for name, probe in (
        ("echt", {"market_data": {"current_price": {"usd": 1.5}}}),
        ("leer", {}),
        ("null", {"market_data": {"current_price": {"usd": 0}}}),
        ("text", {"market_data": {"current_price": {"usd": "abc"}}}),
        ("kein dict", "kaputt"),
    ):
        print("  hat_marktdaten(%-10s) = %s" % (name, hat_marktdaten(probe)))
    print(json.dumps({k: v for k, v in list(d[0].items())[:3]}, indent=1)[:200])
