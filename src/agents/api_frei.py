"""Freie Datenquellen fuer die Agenten, deren Quelle api.moondev.com:8000 tot ist.

Die Klasse `MoonDevAPI` hier hat DIESELBE Schnittstelle wie die in `api.py`
(gleiche Methodennamen, gleiche DataFrame-Spalten), holt die Daten aber aus
oeffentlichen Boersen-Endpunkten - ohne Schluessel, ohne Konto. Sie versucht
zuerst die echte MoonDev-API und schaltet nur um, wenn die nicht antwortet.

Gemessen am 24.09.2026 (dieser Rechner, ohne Schluessel):

  get_funding_data     -> Binance /fapi/v1/premiumIndex           (910 Symbole, ein Aufruf)
  get_oi_data          -> Binance /fapi/v1/openInterest + markPrice (je Symbol)
  get_oi_total         -> dieselbe Quelle, Summe der Liste
  get_liquidation_data -> OKX /api/v5/public/liquidation-orders    (je Instrument)
     (Binance /fapi/v1/allForceOrders antwortet 404 - der Endpunkt ist weg)

NICHT ersetzbar und bewusst None: `get_copybot_follow_list` und
`get_recent_transactions`. Das sind MoonDevs EIGENE Kopierhandels-Daten - dafuer
gibt es keine oeffentliche Quelle. Ein leerer DataFrame waere schlimmer als
None: die Agenten pruefen auf None und ueberspringen den Zyklus.
"""

import os
import time

import pandas as pd
import requests

BINANCE = "https://fapi.binance.com"
OKX = "https://www.okx.com"
FRIST = 20

# Instrumente fuer die Liquidationsdaten (OKX verlangt uly oder instId je
# Aufruf). BTC/ETH/SOL sind die drei groessten USDT-Swaps; mehr Aufrufe
# kosten nur Zeit.
LIQ_ULY = ("BTC-USDT", "ETH-USDT", "SOL-USDT")

# Symbole fuer die Open-Interest-Reihe. Der Wal-Agent liest BTCUSDT und
# ETHUSDT; die uebrigen dienen dem Gesamtwert.
OI_SYMBOLE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT")

_CTVAL = {}


def _json(url, params=None, name=""):
    """GET mit klarer Fehlermeldung; gibt (daten, fehler) zurueck."""
    try:
        r = requests.get(url, params=params, timeout=FRIST,
                         headers={"User-Agent": "moondev-frei/1.0"})
        r.raise_for_status()
        return r.json(), None
    except Exception as e:                                     # noqa: BLE001
        return None, "%s: %s" % (name or url, e)


def _okx(pfad, params=None, name=""):
    d, f = _json(OKX + pfad, params, name or pfad)
    if f or not isinstance(d, dict) or d.get("code") != "0":
        return None
    return d.get("data") or []


def _ctval():
    """Kontraktwert je SWAP-Instrument (sz ist in Kontrakten, nicht in Muenzen)."""
    if _CTVAL:
        return _CTVAL
    for d in (_okx("/api/v5/public/instruments",
                   {"instType": "SWAP"}, "instruments") or []):
        try:
            _CTVAL[d["instId"]] = float(d.get("ctVal") or 0)
        except (TypeError, ValueError, KeyError):
            continue
    return _CTVAL


class MoonDevAPI:
    """Ersatz fuer `api.py:MoonDevAPI` - erst moondev, sonst oeffentliche Quellen."""

    def __init__(self, api_key=None, base_url="http://api.moondev.com:8000"):
        self.api_key = api_key or os.getenv("MOONDEV_API_KEY")
        self.base_url = base_url
        self._moondev = None
        self._moondev_geprueft = False
        print("🌐 Freie Datenquellen aktiv (api.moondev.com ist tot, "
              "gemessen 24.09.2026)")

    # --- MoonDev-Erstversuch ------------------------------------------------
    def _moondev_api(self):
        """Die echte Klasse, nur wenn der Host wirklich antwortet."""
        if self._moondev_geprueft:
            return self._moondev
        self._moondev_geprueft = True
        try:
            from src.agents.api import MoonDevAPI as Echt
        except Exception:                                      # noqa: BLE001
            return None
        try:
            requests.get(self.base_url, timeout=5)
        except Exception as e:                                 # noqa: BLE001
            print("ℹ️  MoonDev-API nicht erreichbar (%s) - oeffentliche "
                  "Quellen" % e)
            return None
        self._moondev = Echt(api_key=self.api_key, base_url=self.base_url)
        return self._moondev

    # --- Funding ------------------------------------------------------------
    def get_funding_data(self):
        """Spalten: event_time, symbol, funding_rate, yearly_funding_rate.

        Binance liefert den laufenden 8-Stunden-Satz aller Symbole in EINEM
        Aufruf. yearly_funding_rate ist in Prozent (3 Zahlungen/Tag x 365),
        wie in der Original-CSV.
        """
        if self._moondev_api() is not None:
            return self._moondev.get_funding_data()
        d, f = _json(BINANCE + "/fapi/v1/premiumIndex", None, "premiumIndex")
        if f or not isinstance(d, list):
            print("💥 Funding nicht abrufbar: %s" % f)
            return None
        zeilen = []
        for s in d:
            try:
                satz = float(s.get("lastFundingRate") or 0)
            except (TypeError, ValueError):
                continue
            zeilen.append({
                "event_time": int(s.get("time") or 0),
                "symbol": s.get("symbol"),
                "funding_rate": satz,
                "yearly_funding_rate": satz * 3 * 365 * 100.0,
            })
        df = pd.DataFrame(zeilen)
        print("✨ %d Funding-Saetze (Binance, frei)" % len(df))
        return df if not df.empty else None

    # --- Open Interest ------------------------------------------------------
    def _markt(self):
        d, _ = _json(BINANCE + "/fapi/v1/premiumIndex", None, "premiumIndex")
        if not isinstance(d, list):
            return {}
        return {s.get("symbol"): s for s in d}

    def _ein_oi(self, symbol, markt):
        d, f = _json(BINANCE + "/fapi/v1/openInterest", {"symbol": symbol},
                     "openInterest %s" % symbol)
        if f or not isinstance(d, dict):
            return None
        preis = float((markt.get(symbol) or {}).get("markPrice") or 0)
        return {"symbol": symbol,
                "openInterest": float(d.get("openInterest") or 0),
                "price": preis,
                "time": int(d.get("time") or 0)}

    def get_oi_data(self):
        """Spalten: symbol, openInterest, price, time (wie die Original-CSV)."""
        if self._moondev_api() is not None:
            return self._moondev.get_oi_data()
        markt = self._markt()
        zeilen = [z for z in (self._ein_oi(s, markt) for s in OI_SYMBOLE) if z]
        if not zeilen:
            print("💥 Kein Open Interest abrufbar")
            return None
        df = pd.DataFrame(zeilen)
        print("✨ %d Open-Interest-Zeilen (Binance, frei)" % len(df))
        return df

    def get_oi_total(self):
        """Offenes Interesse in USD, summiert ueber die Symbol-Liste."""
        df = self.get_oi_data()
        if df is None or df.empty:
            return None
        gesamt = float((df["openInterest"] * df["price"]).sum())
        return pd.DataFrame([{
            "timestamp": int(df["time"].max()),
            "total_oi": gesamt,
        }])

    # --- Liquidationen ------------------------------------------------------
    def get_liquidation_data(self, limit=10000):
        """Spalten der Original-CSV, in DIESER Reihenfolge (der Agent setzt die
        Namen selbst): symbol, side, type, time_in_force, quantity, price,
        price2, status, filled_qty, total_qty, timestamp, usd_value.

        side folgt der Boersen-Konvention: 'SELL' = eine LONG-Position wurde
        zwangsgeschlossen, 'BUY' = eine SHORT-Position. Genau so liest es
        liquidation_agent.py.
        """
        if self._moondev_api() is not None:
            return self._moondev.get_liquidation_data(limit=limit)
        ct = _ctval()
        zeilen = []
        for uly in LIQ_ULY:
            for block in (_okx("/api/v5/public/liquidation-orders",
                               {"instType": "SWAP", "uly": uly,
                                "state": "filled", "limit": 100}, uly) or []):
                inst = block.get("instId") or ""
                symbol = uly.replace("-", "")            # BTC-USDT -> BTCUSDT
                for d in (block.get("details") or []):
                    try:
                        sz = float(d.get("sz") or 0)
                        preis = float(d.get("bkPx") or 0)
                        ts = int(d.get("ts") or d.get("time") or 0)
                    except (TypeError, ValueError):
                        continue
                    menge = sz * (ct.get(inst) or 0)     # Kontrakte -> Muenzen
                    seite = (d.get("side") or "").upper()
                    if seite not in ("SELL", "BUY"):
                        continue
                    zeilen.append([
                        symbol, seite, "LIMIT", "IOC",
                        menge, preis, preis, "FILLED",
                        menge, menge, ts, menge * preis,
                    ])
        if not zeilen:
            print("💥 Keine Liquidationsdaten abrufbar (OKX)")
            return None
        zeilen.sort(key=lambda z: z[10])
        if limit:
            zeilen = zeilen[-int(limit):]
        df = pd.DataFrame(zeilen)
        print("✨ %d Liquidationszeilen (OKX, frei)" % len(df))
        return df

    # --- nicht ersetzbar ----------------------------------------------------
    def get_copybot_follow_list(self):
        print("ℹ️  Kopierhandels-Liste ist MoonDevs eigene Datenbank - "
              "keine oeffentliche Quelle vorhanden")
        return None

    def get_recent_transactions(self, *a, **k):
        print("ℹ️  recent_txs ist MoonDevs eigene Datenbank - "
              "keine oeffentliche Quelle vorhanden")
        return None

    def get_token_addresses(self):
        # Neue Token-Adressen gibt es oeffentlich (DexScreener/Pump.fun), aber
        # keiner der fuenf datenlosen Agenten liest diese Reihe.
        print("ℹ️  get_token_addresses: keine freie Quelle verdrahtet")
        return None


if __name__ == "__main__":
    a = MoonDevAPI()
    t0 = time.time()
    for name in ("get_funding_data", "get_oi_data", "get_oi_total",
                 "get_liquidation_data"):
        df = getattr(a, name)()
        print("  %-22s %s" % (name, "None" if df is None else
                              "%d Zeilen, Spalten %s" % (len(df),
                                                         list(df.columns)[:5])))
    print("Dauer %.1f s" % (time.time() - t0))