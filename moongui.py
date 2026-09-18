"""
🌙 MOON GUI
===========
Moon-Dev-Stack Schaltzentrale fuer Moon-Dev-Code + moon-dev-ai-agents.

- 47 Agenten aus src/agents/ in einer Bibliothek (Terminal, Start/Stop im Thread)
- Börsen-Adapter OKX / Kraken / Binance (oeffentliche Daten + bestätigte Orders)
- Wallet: Solana-Balance (oeffentlicher RPC), private Keys NIE gespeichert
- LLM-Auswahl: lokal (Ollama, schluessellos) oder optional Cloud-Key
- Ein-Klick-Start der 7 hausüblichen Beobachtungs-Agenten
- PDFs (Moon-Dev-Code/strategy_pdfs) — Eingang: Strategie-Dokumente

SICHERHEIT: Orders brauchen die Checkbox "Order wirklich senden" UND den
geklickten "ORDER SENDEN"-Button (Fenster wird nicht minimiert). Private
Schluessel werden nur gelesen, nie gespeichert oder angezeigt. Order-Limit
hart auf 0.0002 BTC bei OKX, 0.001 XBT bei Kraken, 0.0005 BTC bei Binance.

Start:  .venv\\Scripts\\pythonw.exe moongui.py   (oder python moongui.py)
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ---------------------------------------------------------------- Pfade
REPO = Path(__file__).resolve().parent
AGENTS_DIR = REPO / "src" / "agents"
PDF_DIR = REPO.parent / "Moon-Dev-Code" / "strategy_pdfs"
VENV_PY = REPO / ".venv" / "Scripts" / "python.exe"
if not VENV_PY.exists():
    VENV_PY = Path(sys.executable)
LOG_DIR = REPO / "moongui_logs"
LOG_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------- Konstanten
AGENT_MODULES = sorted(
    p.stem for p in AGENTS_DIR.glob("*_agent.py") if p.stem not in {"base_agent", "api"}
)
ORDER_LIMITS = {"OKX": 0.0002, "Kraken": 0.001, "Binance": 0.0005}
LLM_PRESETS = {
    "qwen35-8k:latest": ("ollama", "http://127.0.0.1:11434/v1"),
    "qwen36-35b-a3b:latest": ("ollama", "http://127.0.0.1:11434/v1"),
    "glm4:9b-chat:latest": ("ollama", "http://127.0.0.1:11434/v1"),
    "Cloud-Key (OpenAI/Anthropic)": ("cloud", ""),
}
HAUS_AGENTEN = {
    "funding_agent": "Funding-Raten (Beobachtung, Hyperliquid)",
    "kraken_agent": "Kraken-EUR-Paare + lokales LLM-Urteil",
    "listingarb_agent": "Hohes Volumen, nicht auf Binance",
    "new_or_top_agent": "Neue / Top-Coins (oeffentlich)",
    "liquidation_agent": "Zwangsschluesse (Liquidationen)",
    "coingecko_agent": "CoinGecko-Marktdaten",
    "whale_agent": "Whale-Watcher (braucht Cloud-Key)",
}

# ---------------------------------------------------------------- Daten-Adapter (nur stdlib)
_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
}


def _http_json(url, headers=None, payload=None, timeout=12):
    import urllib.request

    data = json.dumps(payload).encode() if payload is not None else None
    hdrs = dict(_UA)
    if payload is not None:
        hdrs["Content-Type"] = "application/json"
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def okx_tickers():
    d = _http_json("https://www.okx.com/api/v5/market/tickers?instType=SPOT")
    rows = []
    for t in d.get("data", []):
        try:
            rows.append(
                {
                    "instrument": t["instId"],
                    "last": float(t["last"]),
                    "open24h": float(t["open24h"]),
                    "high24h": float(t["high24h"]),
                    "low24h": float(t["low24h"]),
                    "vol24h": float(t.get("volCcy24h") or 0),
                }
            )
        except (KeyError, ValueError):
            continue
    return rows


def okx_kurs(instrument):
    d = _http_json(f"https://www.okx.com/api/v5/market/ticker?instId={instrument}")
    return float(d["data"][0]["last"])


def okx_order(key, secret, passphrase, instrument, side, sz):
    """OKX-V2-Signatur: Timestamp + Methode + Pfad + Body, base64-HMAC-SHA256."""
    import base64
    import hashlib
    import hmac

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    path = "/api/v5/trade/order"
    body = json.dumps(
        {"instId": instrument, "tdMode": "cash", "side": side, "ordType": "market", "sz": str(sz)}
    )
    msg = f"{ts}POST{path}{body}"
    sig = base64.b64encode(hmac.new(secret.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    return _http_json(
        "https://www.okx.com" + path,
        headers={
            "OK-ACCESS-KEY": key,
            "OK-ACCESS-SIGN": sig,
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
        },
        payload=json.loads(body),
    )


def kraken_tickers():
    d = _http_json("https://api.kraken.com/0/public/Ticker?pair=XBTUSD,ETHUSD")
    rows, names = [], {"XXBTZUSD": "XBTUSD", "XETHZUSD": "ETHUSD"}
    for code, t in d.get("result", {}).items():
        try:
            rows.append(
                {
                    "instrument": names.get(code, code),
                    "last": float(t["c"][0]),
                    "open24h": None,
                    "high24h": float(t["h"][1]),
                    "low24h": float(t["l"][1]),
                    "vol24h": float(t["v"][1]),
                }
            )
        except (KeyError, ValueError):
            continue
    return rows


def kraken_order(key, secret, pair, side, volume):
    """Kraken-V0-Signatur: SHA256(nonce+body), HMAC-SHA512(secret, path+sha)."""
    import base64
    import hashlib
    import hmac
    import urllib.request
    from urllib.parse import urlencode

    path = "/0/private/AddOrder"
    nonce = str(int(time.time() * 1000))
    body = {"nonce": nonce, "pair": pair, "type": side, "ordertype": "market", "volume": str(volume)}
    enc = (nonce + urlencode(body)).encode()
    sha = hashlib.sha256(enc).digest()
    sig = hmac.new(base64.b64decode(secret), path.encode() + sha, hashlib.sha512).digest()
    req = urllib.request.Request(
        "https://api.kraken.com" + path,
        data=urlencode(body).encode(),
        headers={
            "API-Key": key,
            "API-Sign": base64.b64encode(sig).decode(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode())


def binance_tickers():
    raw = _http_json("https://api.binance.com/api/v3/ticker/24hr")
    rows = []
    for t in raw:
        if not t["symbol"].endswith("USDT"):
            continue
        try:
            rows.append(
                {
                    "instrument": t["symbol"],
                    "last": float(t["lastPrice"]),
                    "open24h": float(t["openPrice"]),
                    "high24h": float(t["highPrice"]),
                    "low24h": float(t["lowPrice"]),
                    "vol24h": float(t["quoteVolume"]),
                }
            )
        except (KeyError, ValueError):
            continue
    return rows


def binance_order(key, secret, symbol, side, qty):
    import base64
    import hashlib
    import hmac
    from urllib.parse import urlencode

    params = {"symbol": symbol, "side": side, "type": "MARKET", "quantity": str(qty)}
    params["timestamp"] = str(int(time.time() * 1000))
    q = urlencode(params)
    params["signature"] = hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    return _http_json("https://api.binance.com/api/v3/order?" + urlencode(params))


def solana_balance(address):
    d = _http_json(
        "https://api.mainnet-beta.solana.com",
        payload={"jsonrpc": "2.0", "id": 1, "method": "getBalance", "params": [address]},
    )
    return d.get("result", {}).get("value", 0) / 1e9


def ollama_modelle():
    try:
        d = _http_json("http://127.0.0.1:11434/api/tags", timeout=4)
        return [m["name"] for m in d.get("models", [])]
    except Exception:
        return []


# ---------------------------------------------------------------- RBI (Research-Backtest-Implement)
RBI_DIR = AGENTS_DIR.parent / "data" / "rbi"
RBI_STRATEGIE_ORDNER = ["FINAL_WINNING_STRATEGIES", "AI_GENERATED_STRATEGIES", "AI_OPTIMIZED_STRATEGIES"]
RBI_LAEUFER = ["rbi_agent", "rbi_agent_v2", "rbi_agent_v2_simple", "rbi_batch_backtester"]


def rbi_kennzahlen():
    if not RBI_DIR.exists():
        return {"tage_ordner": 0, "backtests": 0, "ideen": 0, "agenten_md": 0}
    tage = [p for p in RBI_DIR.iterdir() if p.is_dir() and p.name[0].isdigit()]
    bt = sum(1 for _ in RBI_DIR.rglob("*_BT.py")) + sum(1 for _ in RBI_DIR.rglob("*_bt.py"))
    ideen = 0
    ip = RBI_DIR / "ideas.txt"
    if ip.exists():
        ideen = sum(1 for ln in ip.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip() and not ln.startswith("#"))
    agenten_md = sum(1 for _ in (RBI_DIR / ".claude" / "agents").rglob("*.md")) if (RBI_DIR / ".claude" / "agents").exists() else 0
    return {"tage_ordner": len(tage), "backtests": bt, "ideen": ideen, "agenten_md": agenten_md}


def rbi_agent_katalog():
    """Liest alle Subagent-Definitionen (.claude/agents/**/*.md) - Name + erste Beschreibungszeile."""
    out = []
    base = RBI_DIR / ".claude" / "agents"
    if not base.exists():
        return out
    for p in sorted(base.rglob("*.md")):
        if p.name in ("README.md", "MIGRATION_SUMMARY.md"):
            continue
        try:
            txt = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        beschreibung = ""
        for ln in txt.splitlines():
            ln = ln.strip()
            if ln.startswith("description:"):
                beschreibung = ln.split(":", 1)[1].strip().strip('"')
                break
        if not beschreibung:
            for ln in txt.splitlines():
                if ln.strip() and not ln.startswith(("---", "#", "name:")):
                    beschreibung = ln.strip()[:100]
                    break
        out.append((str(p.relative_to(base)), beschreibung))
    return out


def rbi_strategie_dateien(unterordner):
    d = RBI_DIR / unterordner
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file())


def rbi_idee_anhaengen(text):
    ip = RBI_DIR / "ideas.txt"
    with open(ip, "a", encoding="utf-8") as f:
        f.write(text.strip() + "\n")


# ---------------------------------------------------------------- App
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.work = queue.Queue()
        self.threads = {}  # mod -> [Popen, logpfad]
        self._busy = False

        root.title("MoonDev-GUI")
        root.geometry("1180x760")
        root.configure(bg="#101418")

        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background="#101418", foreground="#d8e0e8", fieldbackground="#1a2130")
        st.configure("TNotebook", background="#101418", borderwidth=0)
        st.configure("TNotebook.Tab", background="#232c3d", foreground="#cfe3ff", padding=(14, 6))
        st.map("TNotebook.Tab", background=[("selected", "#2f4a7a")])
        st.configure("TButton", background="#2a3a55", foreground="#e8f0ff", padding=(10, 5))
        st.map("TButton", background=[("active", "#3a557f"), ("disabled", "#1c2330")])
        st.configure("Treeview", background="#141b28", fieldbackground="#141b28", foreground="#d8e0e8", rowheight=24)
        st.configure("Treeview.Heading", background="#232c3d", foreground="#cfe3ff")

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        self._readmes = self._find_readmes()
        self._rbi_kz = rbi_kennzahlen()
        self._rbi_katalog = rbi_agent_katalog()
        self._build_boersen(nb)
        self._build_wallet(nb)
        self._build_agents(nb)
        self._build_rbi(nb)
        self._build_llm(nb)
        self._build_pdfs(nb)
        self._build_readme(nb)

        self._poll()
        self._auto_ticker()

    # ---------------- Börsen-Tab
    def _build_boersen(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="Börsen")

        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Börse:").pack(side="left")
        self.exchange_var = tk.StringVar(value="OKX")
        for name in ("OKX", "Kraken", "Binance"):
            ttk.Radiobutton(top, text=name, variable=self.exchange_var, value=name, command=self._ticker_exchange).pack(
                side="left", padx=6
            )
        self.markt_var = tk.StringVar(value="SPOT")
        ttk.Label(top, text="Markt:").pack(side="left", padx=(16, 2))
        ttk.Combobox(top, textvariable=self.markt_var, values=["SPOT", "SWAP"], width=8, state="readonly").pack(side="left")
        ttk.Button(top, text="Aktualisieren", command=self._ticker_exchange).pack(side="right")
        self.auto_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Auto (15 s)", variable=self.auto_var).pack(side="right", padx=8)

        self.tree = ttk.Treeview(tab, columns=("inst", "last", "chg", "high", "low", "vol"), show="headings")
        for c, t, w in (
            ("inst", "Instrument", 180),
            ("last", "Kurs", 110),
            ("chg", "24h %", 90),
            ("high", "Hoch", 110),
            ("low", "Tief", 110),
            ("vol", "24h Vol", 130),
        ):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="e" if c != "inst" else "w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=4)
        self.tree.bind("<Double-Button-1>", self._tree_click)

        mid = ttk.Frame(tab)
        mid.pack(fill="x", padx=8, pady=4)
        ttk.Label(mid, text="Klicke eine Zeile -> Instrument übernehmen. Order:").pack(side="left")
        self.order_inst = tk.StringVar(value="BTC-USDT")
        self.order_inst_e = ttk.Entry(mid, textvariable=self.order_inst, width=16)
        self.order_inst_e.pack(side="left", padx=6)
        ttk.Label(mid, text="Seite:").pack(side="left")
        self.order_side = tk.StringVar(value="buy")
        ttk.Combobox(mid, textvariable=self.order_side, values=("buy", "sell"), width=6, state="readonly").pack(side="left")
        ttk.Label(mid, text="Menge:").pack(side="left", padx=(12, 2))
        self.order_qty = tk.StringVar(value="0.0001")
        ttk.Entry(mid, textvariable=self.order_qty, width=10).pack(side="left")
        ttk.Label(mid, text="Key:").pack(side="left", padx=(12, 2))
        self.order_key = ttk.Entry(mid, width=26)
        self.order_key.pack(side="left")
        ttk.Label(mid, text="Secret:").pack(side="left", padx=(12, 2))
        self.order_secret = ttk.Entry(mid, width=26, show="*")
        self.order_secret.pack(side="left")
        ttk.Label(mid, text="Passphrase (OKX):").pack(side="left", padx=(12, 2))
        self.order_pass = ttk.Entry(mid, width=12, show="*")
        self.order_pass.pack(side="left")

        arm = ttk.Frame(tab)
        arm.pack(fill="x", padx=8, pady=2)
        self.arm_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(arm, text="⚠ Order wirklich senden (Hard-Limit je Börse eingebaut)", variable=self.arm_var).pack(side="left")
        self.send_btn = ttk.Button(arm, text="ORDER SENDEN", command=self._send_order)
        self.send_btn.pack(side="left", padx=10)

        self.boersen_log = self._make_log(tab, 7)

        self.boersen_fuss = ttk.Label(tab, text="", foreground="#89a5c9")
        self.boersen_fuss.pack(anchor="w", padx=10)
        return tab

    def _build_wallet(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="Wallet")
        row = ttk.Frame(tab)
        row.pack(fill="x", padx=8, pady=8)
        ttk.Label(row, text="Solana-Adresse:").pack(side="left")
        self.wallet_addr = ttk.Entry(row, width=54)
        self.wallet_addr.pack(side="left", padx=6)
        ttk.Button(row, text="Balance abfragen", command=self._sol_balance).pack(side="left")
        self.wallet_status = ttk.Label(tab, text="Keine Abfrage", foreground="#89a5c9")
        self.wallet_status.pack(anchor="w", padx=10)
        ttk.Label(
            tab,
            text="\nPrivat-Keys werden NIE gespeichert oder angezeigt — nur für Transaktionen\nim Börsen-Tab kurz gelesen und sofort verworfen.",
            foreground="#6f8aa8",
        ).pack(anchor="w", padx=10, pady=6)
        return tab

    def _build_agents(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="Agenten")
        haus = ttk.LabelFrame(tab, text="Ein-Klick-Start (hausübliche Beobachtungs-Agenten)")
        haus.pack(fill="x", padx=8, pady=6)
        for i, (mod, desc) in enumerate(HAUS_AGENTEN.items()):
            b = ttk.Button(haus, text=mod, command=lambda m=mod: self._toggle_agent(m))
            b.grid(row=i // 4, column=(i % 4) * 3, columnspan=2, sticky="w", padx=4, pady=2)
            ttk.Label(haus, text=desc, foreground="#7d93ad").grid(row=i // 4, column=(i % 4) * 3 + 2, sticky="w")
        alle = ttk.LabelFrame(tab, text=f"Agenten-Bibliothek ({len(AGENT_MODULES)}) — Doppelklick = starten/stoppen")
        alle.pack(fill="both", expand=True, padx=8, pady=6)
        frames = ttk.Frame(alle)
        frames.pack(fill="both", expand=True, padx=4, pady=4)
        self.agent_tree = ttk.Treeview(frames, columns=("mod",), show="tree")
        self.agent_tree.heading("#0", text="Modul")
        self.agent_tree.pack(side="left", fill="both", expand=True)
        for m in AGENT_MODULES:
            self.agent_tree.insert("", "end", text=m, values=(m,))
        self.agent_tree.bind(
            "<Double-Button-1>",
            lambda e: self._toggle_agent(self.agent_tree.item(self.agent_tree.focus())["text"]),
        )
        right = ttk.Frame(frames)
        right.pack(side="left", fill="y", padx=6)
        ttk.Button(right, text="▶ Start", command=self._start_selected_agent).pack(fill="x", pady=2)
        ttk.Button(right, text="■ Stop", command=self._stop_selected_agent).pack(fill="x", pady=2)
        self.agent_log = self._make_log(tab, 8)
        return tab

    def _build_llm(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="LLM-Einstellungen")
        lf = ttk.LabelFrame(tab, text="Sprachmodell für alle Agenten")
        lf.pack(fill="x", padx=8, pady=8)
        self.llm_var = tk.StringVar(value="qwen35-8k:latest")
        for name in LLM_PRESETS:
            ttk.Radiobutton(lf, text=name, variable=self.llm_var, value=name).pack(anchor="w", padx=8, pady=2)
        ttk.Button(lf, text="Umgebung aktualisieren", command=self._apply_env).pack(anchor="w", padx=8, pady=6)
        self.env_status = ttk.Label(tab, text="", foreground="#89a5c9")
        self.env_status.pack(anchor="w", padx=10)
        ttk.Label(
            tab,
            text="\nLokales Ollama ist der Hausstandard (kein Schlüssel).\nOLLAMA_MODEL/OLLAMA_BASE_URL werden in .env geschrieben —\nvorhandene Werte bleiben erhalten, sofern nicht hier umgestellt.",
            foreground="#6f8aa8",
        ).pack(anchor="w", padx=10)
        return tab

    def _build_rbi(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="RBI-Swarm")

        kopf = ttk.LabelFrame(tab, text="Research-Backtest-Implement (src/data/rbi) — Kennzahlen")
        kopf.pack(fill="x", padx=8, pady=6)
        self.rbi_kz_label = ttk.Label(kopf, text=self._rbi_kz_text(), foreground="#cfe3ff")
        self.rbi_kz_label.pack(anchor="w", padx=8, pady=4)

        laeufer = ttk.LabelFrame(tab, text="RBI-Läufer starten (Research→Backtest→Implement, lokal mit Ollama qwen35-8k)")
        laeufer.pack(fill="x", padx=8, pady=6)
        for i, mod in enumerate(RBI_LAEUFER):
            ttk.Button(laeufer, text=mod, command=lambda m=mod: self._toggle_rbi(m)).grid(row=0, column=i, padx=4, pady=4, sticky="w")
        ttk.Label(
            laeufer,
            text="ℹ Läuft jetzt komplett lokal: Ollama qwen35-8k, kein API-Key nötig (inkl. Backtest/Implement via Modell-Factory).",
            foreground="#c9a04a",
        ).grid(row=1, column=0, columnspan=4, sticky="w", padx=4, pady=(0, 4))

        mitte = ttk.PanedWindow(tab, orient="horizontal")
        mitte.pack(fill="both", expand=True, padx=8, pady=6)

        links = ttk.LabelFrame(mitte, text=f"Subagenten-Katalog ({len(self._rbi_katalog)})")
        mitte.add(links, weight=1)
        self.rbi_agent_list = ttk.Treeview(links, columns=("desc",), show="tree")
        self.rbi_agent_list.pack(fill="both", expand=True, padx=4, pady=4)
        for name, desc in self._rbi_katalog:
            self.rbi_agent_list.insert("", "end", text=name, values=(desc,))
        self.rbi_agent_list.bind("<<TreeviewSelect>>", self._show_rbi_agent)
        self.rbi_agent_detail = scrolledtext.ScrolledText(
            links, height=5, bg="#0c1118", fg="#d8e0e8", font=("Consolas", 9), wrap="word"
        )
        self.rbi_agent_detail.pack(fill="x", padx=4, pady=(0, 4))

        rechts = ttk.LabelFrame(mitte, text="Strategie-Ergebnisse")
        mitte.add(rechts, weight=1)
        self.rbi_ordner_var = tk.StringVar(value=RBI_STRATEGIE_ORDNER[0])
        row = ttk.Frame(rechts)
        row.pack(fill="x", padx=4, pady=4)
        ttk.Combobox(row, textvariable=self.rbi_ordner_var, values=RBI_STRATEGIE_ORDNER, state="readonly", width=28).pack(side="left")
        ttk.Button(row, text="Laden", command=self._refresh_rbi_strategien).pack(side="left", padx=6)
        self.rbi_strategie_list = tk.Listbox(rechts, bg="#141b28", fg="#d8e0e8", selectbackground="#2f4a7a")
        self.rbi_strategie_list.pack(fill="both", expand=True, padx=4, pady=4)
        ttk.Button(rechts, text="Datei öffnen", command=self._open_rbi_strategie).pack(pady=4)
        self._refresh_rbi_strategien()

        idee = ttk.LabelFrame(tab, text="Neue Idee an ideas.txt anhängen (RBI-Agent verarbeitet sie im nächsten Lauf)")
        idee.pack(fill="x", padx=8, pady=6)
        self.rbi_idee_entry = ttk.Entry(idee, width=100)
        self.rbi_idee_entry.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(idee, text="Anhängen", command=self._append_rbi_idee).pack(side="left", padx=6)

        self.rbi_log = self._make_log(tab, 6)
        return tab

    def _rbi_kz_text(self):
        k = self._rbi_kz
        return (
            f"{k['tage_ordner']} Tages-Läufe  |  {k['backtests']} Backtest-Dateien  |  "
            f"{k['ideen']} offene Ideen in ideas.txt  |  {k['agenten_md']} Claude-Subagenten-Definitionen"
        )

    def _show_rbi_agent(self, _evt=None):
        sel = self.rbi_agent_list.selection()
        if not sel:
            return
        name = self.rbi_agent_list.item(sel[0])["text"]
        desc = self.rbi_agent_list.item(sel[0])["values"][0]
        self.rbi_agent_detail.delete("1.0", "end")
        self.rbi_agent_detail.insert("1.0", f"{name}\n\n{desc}")

    def _refresh_rbi_strategien(self):
        self.rbi_strategie_list.delete(0, "end")
        for name in rbi_strategie_dateien(self.rbi_ordner_var.get()):
            self.rbi_strategie_list.insert("end", name)

    def _open_rbi_strategie(self):
        sel = self.rbi_strategie_list.curselection()
        if not sel:
            return
        p = RBI_DIR / self.rbi_ordner_var.get() / self.rbi_strategie_list.get(sel[0])
        os.startfile(p)

    def _append_rbi_idee(self):
        text = self.rbi_idee_entry.get().strip()
        if not text:
            return
        rbi_idee_anhaengen(text)
        self.rbi_idee_entry.delete(0, "end")
        self._rbi_kz = rbi_kennzahlen()
        self.rbi_kz_label.configure(text=self._rbi_kz_text())
        self._log(self.rbi_log, f"➕ Idee angehängt: {text[:80]}")

    def _toggle_rbi(self, mod):
        self._toggle_agent(mod, log_widget=self.rbi_log)

    def _build_pdfs(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="Strategie-PDFs")
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text=str(PDF_DIR), foreground="#89a5c9").pack(side="left")
        ttk.Button(top, text="Ordner öffnen", command=lambda: os.startfile(PDF_DIR)).pack(side="right")
        self.pdf_list = tk.Listbox(tab, bg="#141b28", fg="#d8e0e8", selectbackground="#2f4a7a")
        self.pdf_list.pack(fill="both", expand=True, padx=8, pady=4)
        ttk.Button(tab, text="PDF öffnen", command=self._open_pdf).pack(pady=4)
        self._refresh_pdfs()
        return tab

    # ---------------- README-Tab: alle README-Dateien des Repos
    def _find_readmes(self):
        found = []
        for p in REPO.rglob("README*"):
            if ".venv" in p.parts or ".git" in p.parts or "moongui_logs" in p.parts:
                continue
            try:
                rel = p.relative_to(REPO)
                size = len(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
            found.append((str(rel), size, str(p)))
        return sorted(found)

    def _build_readme(self, nb):
        tab = ttk.Frame(nb)
        nb.add(tab, text="READMEs")
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text=f"{len(self._readmes)} README-Dateien im Repo — Klick zeigt Inhalt", foreground="#89a5c9").pack(side="left")
        self.readme_search = tk.StringVar()
        ttk.Entry(top, textvariable=self.readme_search, width=28).pack(side="left", padx=8)
        ttk.Button(top, text="Filter", command=self._refresh_readmes).pack(side="left")
        frames = ttk.Frame(tab)
        frames.pack(fill="both", expand=True, padx=8, pady=4)
        self.readme_list = tk.Listbox(frames, bg="#141b28", fg="#d8e0e8", selectbackground="#2f4a7a")
        self.readme_list.pack(side="left", fill="y", padx=(0, 6))
        self.readme_view = scrolledtext.ScrolledText(
            frames, bg="#0c1118", fg="#d8e0e8", insertbackground="#d8e0e8",
            font=("Consolas", 9), wrap="word",
        )
        self.readme_view.pack(side="left", fill="both", expand=True)
        self.readme_list.bind("<<ListboxSelect>>", self._show_readme)
        self._refresh_readmes()
        return tab

    def _refresh_readmes(self):
        self.readme_list.delete(0, "end")
        q = self.readme_search.get().strip().lower()
        for rel, size, _ in self._readmes:
            if q and q not in rel.lower():
                continue
            self.readme_list.insert("end", f"{rel}  ({size // 1024} KB)")
        if self.readme_list.size():
            self.readme_list.selection_set(0)
            self._show_readme()

    def _show_readme(self, _evt=None):
        sel = self.readme_list.curselection()
        if not sel:
            return
        rel = self.readme_list.get(sel[0]).split("  (")[0]
        path = REPO / rel
        try:
            txt = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            txt = f"Fehler beim Lesen: {e}"
        self.readme_view.delete("1.0", "end")
        self.readme_view.insert("1.0", f"── {rel} ─────────────────────\n\n" + txt)

    # ---------------- Log
    def _make_log(self, parent, height):
        log = scrolledtext.ScrolledText(
            parent, height=height, bg="#0c1118", fg="#b8d4a0",
            insertbackground="#b8d4a0", font=("Consolas", 9), state="disabled", wrap="word",
        )
        log.pack(fill="both", expand=False, padx=8, pady=4)
        return log

    def _log(self, widget, msg):
        try:
            widget.configure(state="normal")
            widget.insert("end", f"{datetime.now():%H:%M:%S}  {msg}\n")
            widget.see("end")
            widget.configure(state="disabled")
        except Exception:
            pass

    # ---------------- Ticker
    def _ticker_exchange(self):
        if self._busy:
            return
        self._busy = True
        ex = self.exchange_var.get()
        threading.Thread(target=self._fetch_tickers, args=(ex,), daemon=True).start()

    def _fetch_tickers(self, ex):
        try:
            rows = {"OKX": okx_tickers, "Kraken": kraken_tickers, "Binance": binance_tickers}[ex]()
        except Exception as e:
            self.work.put(("ticker_err", ex, str(e)))
            return
        rows.sort(key=lambda r: r["vol24h"], reverse=True)
        self.work.put(("tickers", ex, rows[:200]))

    def _auto_ticker(self):
        if self.auto_var.get():
            self._ticker_exchange()
        self.root.after(15000, self._auto_ticker)

    def _apply_tickers(self, ex, rows):
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            chg = ""
            if r.get("open24h"):
                chg = f"{(r['last'] / r['open24h'] - 1) * 100:+.2f}"
            self.tree.insert(
                "", "end",
                values=(
                    r["instrument"], f"{r['last']:,.4f}", chg,
                    f"{r.get('high24h') or 0:,.2f}", f"{r.get('low24h') or 0:,.2f}",
                    f"{r['vol24h']:,.0f}",
                ),
            )
        self.boersen_fuss.configure(
            text=f"{ex}: {len(rows)} Instrumente — Doppelklick übernimmt das Instrument in die Orderzeile"
        )
        self._busy = False

    # ---------------- Order
    def _tree_click(self, _):
        sel = self.tree.selection()
        if sel:
            inst = self.tree.item(sel[0])["values"][0]
            self.order_inst.set(inst)

    def _send_order(self):
        ex = self.exchange_var.get()
        if not self.arm_var.get():
            self._log(self.boersen_log, "⚠ Abgebrochen: Checkbox 'Order wirklich senden' ist nicht aktiv.")
            return
        inst = self.order_inst.get().strip()
        side = self.order_side.get()
        try:
            qty = float(self.order_qty.get())
        except ValueError:
            self._log(self.boersen_log, "⚠ Menge ist keine Zahl.")
            return
        limit = ORDER_LIMITS[ex]
        if ex == "OKX":
            order_inst = inst if inst.endswith("-USDT") else "BTC-USDT"
            if qty > limit:
                self._log(self.boersen_log, f"⚠ OKX-Limit {limit} BTC überschritten -> abgebrochen. Menge: {qty}")
                return
            self._log(self.boersen_log, f"🚀 Sende OKX-Marktorder {side} {qty} {order_inst} …")
            threading.Thread(
                target=self._run_order,
                args=("OKX", okx_order, self.order_key.get(), self.order_secret.get(),
                      self.order_pass.get(), order_inst, side, qty),
                daemon=True,
            ).start()
        elif ex == "Kraken":
            pair = "XBTUSD" if inst in ("BTC-USDT", "BTC-USD", "XBTUSD") else inst
            if qty > limit:
                self._log(self.boersen_log, f"⚠ Kraken-Limit {limit} XBT überschritten -> abgebrochen. Menge: {qty}")
                return
            self._log(self.boersen_log, f"🚀 Sende Kraken-Marktorder {side} {qty} {pair} …")
            threading.Thread(
                target=self._run_order,
                args=("Kraken", kraken_order, self.order_key.get(), self.order_secret.get(), pair, side, qty),
                daemon=True,
            ).start()
        elif ex == "Binance":
            symbol = inst if inst.endswith("USDT") else "BTCUSDT"
            if qty > limit:
                self._log(self.boersen_log, f"⚠ Binance-Limit {limit} BTC überschritten -> abgebrochen. Menge: {qty}")
                return
            self._log(self.boersen_log, f"🚀 Sende Binance-Marktorder {side} {qty} {symbol} …")
            threading.Thread(
                target=self._run_order,
                args=("Binance", binance_order, self.order_key.get(), self.order_secret.get(), symbol, side, qty),
                daemon=True,
            ).start()
        self.arm_var.set(False)  # nach einem Sende-Klick wieder scharf stellen

    def _run_order(self, name, fn, *args):
        try:
            res = fn(*args)
            self.work.put(("order_ok", name, res))
        except Exception as e:
            self.work.put(("order_err", name, f"{type(e).__name__}: {e}"))

    # ---------------- Wallet
    def _sol_balance(self):
        addr = self.wallet_addr.get().strip()
        if len(addr) < 32:
            self.wallet_status.configure(text="⚠ Ungültige Adresse (Base58, ~44 Zeichen)")
            return
        self.wallet_status.configure(text="Abfrage läuft …")
        threading.Thread(target=self._sol_worker, args=(addr,), daemon=True).start()

    def _sol_worker(self, addr):
        try:
            bal = solana_balance(addr)
            self.work.put(("sol", f"Solana-Balance: {bal:.4f} SOL"))
        except Exception as e:
            self.work.put(("sol", f"Fehler: {e}"))

    # ---------------- Agenten
    def _start_selected_agent(self):
        sel = self.agent_tree.selection()
        if sel:
            self._toggle_agent(self.agent_tree.item(sel[0])["text"])

    def _stop_selected_agent(self):
        sel = self.agent_tree.selection()
        if sel:
            self._toggle_agent(self.agent_tree.item(sel[0])["text"])

    def _toggle_agent(self, mod, log_widget=None):
        log_widget = log_widget or self.agent_log
        if mod in self.threads:
            p, logp = self.threads.pop(mod)
            try:
                p.terminate()
            except Exception:
                pass

            def _waiter():
                try:
                    p.wait(timeout=6)
                    if p.poll() is None:
                        p.kill()
                except Exception:
                    pass

            threading.Thread(target=_waiter, daemon=True).start()
            self._log(log_widget, f"■ {mod} wird beendet …")
            return
        env = dict(os.environ)
        env["OLLAMA_MODEL"] = "qwen35-8k"
        env["OLLAMA_BASE_URL"] = "http://127.0.0.1:11434/v1"
        logp = LOG_DIR / f"{mod}.log"
        with open(logp, "w", encoding="utf-8") as f:
            f.write(f"# {mod} gestartet {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        p = subprocess.Popen(
            [str(VENV_PY), "-u", "-m", f"src.agents.{mod}"],
            cwd=str(REPO), env=env, stdout=open(logp, "ab"), stderr=subprocess.STDOUT,
        )
        self.threads[mod] = [p, logp]
        self._log(log_widget, f"▶ {mod} gestartet (PID {p.pid}) — Log: {logp}")

    # ---------------- LLM
    def _apply_env(self):
        name = self.llm_var.get()
        kind, url = LLM_PRESETS[name]
        envp = REPO / ".env"
        lines = envp.read_text(encoding="utf-8").splitlines() if envp.exists() else []
        out = [ln for ln in lines if not (ln.startswith("OLLAMA_MODEL") or ln.startswith("OLLAMA_BASE_URL"))]
        if kind == "ollama":
            out.append(f"OLLAMA_MODEL={name}")
            out.append(f"OLLAMA_BASE_URL={url}")
        else:
            out.append("# Cloud-Key-Modus: OLLAMA_MODEL leer -> Agenten fallen auf Cloud-Key zurück")
        envp.write_text("\n".join(out) + "\n", encoding="utf-8")
        self.env_status.configure(text=f".env aktualisiert. {name} aktiv für nächste Agenten-Starts.")

    # ---------------- PDFs
    def _refresh_pdfs(self):
        self.pdf_list.delete(0, "end")
        for p in sorted(PDF_DIR.glob("*.pdf")):
            self.pdf_list.insert("end", p.name)

    def _open_pdf(self):
        sel = self.pdf_list.curselection()
        if sel:
            os.startfile(PDF_DIR / self.pdf_list.get(sel[0]))

    # ---------------- Event-Loop
    def _poll(self):
        try:
            while True:
                msg = self.work.get_nowait()
                kind = msg[0]
                if kind == "tickers":
                    self._apply_tickers(msg[1], msg[2])
                elif kind == "ticker_err":
                    self._log(self.boersen_log, f"⚠ {msg[1]}: {msg[2]}")
                elif kind == "order_ok":
                    self._log(self.boersen_log, f"✅ Order-Response: {json.dumps(msg[2])[:300]}")
                elif kind == "order_err":
                    self._log(self.boersen_log, f"❌ {msg[1]}: {msg[2]}")
                elif kind == "sol":
                    self.wallet_status.configure(text=msg[1])
        except queue.Empty:
            pass
        # Agent-Prozesse ueberwachen
        for mod in list(self.threads.keys()):
            p, logp = self.threads[mod]
            if p.poll() is not None:
                del self.threads[mod]
                self._log(self.agent_log, f"■ {mod} beendet (Code {p.returncode}) — Log: {logp}")
        self.root.after(150, self._poll)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()