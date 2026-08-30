"""
Dashboard Terminal Visual untuk Binance USDⓈ-M Futures Bot.

Menampilkan HUD real-time bergaya MT4/MT5 di terminal dengan refresh otomatis
menggunakan library `rich`. Cocok untuk monitoring live bot dari PowerShell / CMD.

Cara pakai:
    python main.py --dashboard          # mode dashboard (refresh tiap ~5 detik)
    python main.py                      # mode log biasa (tanpa dashboard)

Atau standalone:
    python -m src.ui.dashboard
"""

from __future__ import annotations

import time
import threading
from collections import deque
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align
from rich.columns import Columns

if TYPE_CHECKING:
    from src.engine import TradingEngine

# ────────────────────────────────────────────────────────────────────────────
# Palet warna kustom (brand: hitam-emas Binance)
# ────────────────────────────────────────────────────────────────────────────
C_GOLD    = "bold yellow"
C_GREEN   = "bold bright_green"
C_RED     = "bold bright_red"
C_CYAN    = "bold cyan"
C_WHITE   = "bold white"
C_DIM     = "dim white"
C_ORANGE  = "bold dark_orange"
C_BLUE    = "bold bright_blue"
C_GRAY    = "bright_black"
C_PANEL   = "yellow"         # warna border panel
BG_DARK   = "#0d0d0d"        # latar belakang konsol (Rich tidak enforce ini)

REFRESH_INTERVAL = 3.0       # detik antar refresh dashboard
LOG_MAX_LINES    = 12        # baris log yang ditampilkan di panel bawah


# ────────────────────────────────────────────────────────────────────────────
# LogCapture: intercept logger Python → deque baris terakhir
# ────────────────────────────────────────────────────────────────────────────
import logging
import sys

class _LogCapture(logging.Handler):
    """Handler logging yang menyimpan N baris terakhir ke deque."""

    def __init__(self, maxlen: int = LOG_MAX_LINES):
        super().__init__()
        self.records: deque[str] = deque(maxlen=maxlen)
        self.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.appendleft(self.format(record))
        except Exception:
            pass


# Singleton capture handler – dipasang sekali ke root logger
_capture_handler: _LogCapture | None = None


def install_log_capture() -> _LogCapture:
    global _capture_handler
    if _capture_handler is None:
        _capture_handler = _LogCapture(maxlen=LOG_MAX_LINES)
        logging.getLogger().addHandler(_capture_handler)
    return _capture_handler


# ────────────────────────────────────────────────────────────────────────────
# DashboardState – data snapshot yang dibaca oleh renderer
# ────────────────────────────────────────────────────────────────────────────
class DashboardState:
    """Container data mentah yang dikumpulkan background thread dari engine."""

    def __init__(self):
        self._lock = threading.Lock()

        # Header
        self.symbol        = "BTCUSDT"
        self.interval      = "1H"
        self.mode          = "TESTNET"
        self.bot_version   = "v2.0-binance"

        # Market & Indikator
        self.mid_price     : float | None = None
        self.ema50         : float | None = None
        self.adx14         : float | None = None
        self.plus_di       : float | None = None
        self.minus_di      : float | None = None
        self.rsi14         : float | None = None
        self.atr14         : float | None = None
        self.vol_ratio_20  : float | None = None

        # ML
        self.ml_enabled    : bool         = False
        self.ml_threshold  : float        = 0.70
        self.ml_last_prob  : float | None = None
        self.ml_last_result: str          = "—"   # PASS / SKIP / HOLD
        self.ml_model_name : str          = "btcusdt_ml_rf_1h.onnx"

        # Posisi
        self.pos_symbol    : str | None   = None
        self.pos_side      : str | None   = None   # BUY / SELL
        self.pos_size      : float | None = None
        self.pos_entry     : float | None = None
        self.pos_sl        : float | None = None
        self.pos_tp        : float | None = None
        self.pos_float_pnl : float | None = None

        # Risk / Akun
        self.balance       : float | None = None
        self.equity        : float | None = None
        self.daily_pnl_pct : float | None = None
        self.kill_triggered: bool         = False

        # Trailing
        self.trailing_active: bool        = False

        # Timing
        self.last_run_utc  : str          = "—"
        self.next_poll_ts  : float | None = None   # unix timestamp poll berikutnya

        # Error
        self.last_error    : str          = ""

    # ------------------------------------------------------------------ #
    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                if hasattr(self, k):
                    setattr(self, k, v)

    def snapshot(self) -> "DashboardState":
        """Thread-safe salinan state."""
        import copy
        with self._lock:
            return copy.copy(self)


# ────────────────────────────────────────────────────────────────────────────
# Fungsi-fungsi builder panel (pure rendering, tidak ada I/O)
# ────────────────────────────────────────────────────────────────────────────

def _fmt_price(v: float | None, decimals: int = 2) -> str:
    if v is None:
        return "[dim]—[/dim]"
    return f"[white]{v:,.{decimals}f}[/white]"


def _fmt_pct(v: float | None, suffix: str = "%", good_positive: bool = True) -> str:
    if v is None:
        return "[dim]—[/dim]"
    pct = v * 100
    col = C_GREEN if (pct >= 0 and good_positive) else C_RED
    arrow = "▲" if pct >= 0 else "▼"
    return f"[{col}]{arrow} {abs(pct):.2f}{suffix}[/{col}]"


def _fmt_float(v: float | None, fmt: str = ".4f") -> str:
    if v is None:
        return "[dim]—[/dim]"
    return f"[white]{v:{fmt}}[/white]"


def _bullish_bearish(mid: float | None, ema: float | None) -> Text:
    if mid is None or ema is None:
        return Text("—", style=C_DIM)
    if mid > ema:
        return Text("▲ BULLISH", style=C_GREEN)
    return Text("▼ BEARISH", style=C_RED)


def _adx_label(adx: float | None) -> Text:
    if adx is None:
        return Text("—", style=C_DIM)
    if adx >= 40:
        label, style = "STRONG ▲▲", C_GREEN
    elif adx >= 22:
        label, style = "TRENDING ▲", "bold yellow"
    else:
        label, style = "WEAK / CHOP", C_DIM
    return Text(f"{adx:.1f}  {label}", style=style)


def _rsi_label(rsi: float | None) -> Text:
    if rsi is None:
        return Text("—", style=C_DIM)
    if rsi >= 65:
        return Text(f"{rsi:.1f}  OVERBOUGHT", style=C_RED)
    if rsi <= 35:
        return Text(f"{rsi:.1f}  OVERSOLD", style=C_GREEN)
    return Text(f"{rsi:.1f}  NEUTRAL", style=C_CYAN)


def _ml_result_style(result: str) -> str:
    return {
        "PASS": C_GREEN,
        "SKIP": C_RED,
        "HOLD": C_DIM,
    }.get(result, C_DIM)


# ── Panel 1: Header ────────────────────────────────────────────────────── #
def _build_header(s: DashboardState) -> Panel:
    now_utc = datetime.now(timezone.utc)
    now_wib = datetime.now()  # local time
    utc_str = now_utc.strftime("%Y-%m-%d  %H:%M:%S UTC")
    wib_str = now_wib.strftime("%H:%M:%S WIB")

    # Countdown ke poll berikutnya
    if s.next_poll_ts:
        rem = max(0.0, s.next_poll_ts - time.time())
        h, r = divmod(int(rem), 3600)
        m, sec = divmod(r, 60)
        countdown = f"[{C_CYAN}]{h:02d}:{m:02d}:{sec:02d}[/{C_CYAN}]"
    else:
        countdown = f"[{C_DIM}]—[/{C_DIM}]"

    mode_col = C_ORANGE if s.mode == "TESTNET" else C_RED
    trailing_str = (
        f"[{C_GREEN}]● ON[/{C_GREEN}]"
        if s.trailing_active
        else f"[{C_DIM}]○ OFF[/{C_DIM}]"
    )

    tbl = Table.grid(expand=True, padding=(0, 2))
    tbl.add_column(ratio=3)
    tbl.add_column(ratio=3)
    tbl.add_column(ratio=2)

    tbl.add_row(
        Text.from_markup(f"[{C_GOLD}]🤖 BINANCE PERPS BOT  [{s.bot_version}][/{C_GOLD}]"),
        Text.from_markup(f"[{C_WHITE}]⏱  {utc_str}  /  {wib_str}[/{C_WHITE}]"),
        Text.from_markup(f"[{mode_col}]◈ {s.mode}[/{mode_col}]"),
    )
    tbl.add_row(
        Text.from_markup(f"[{C_WHITE}]Pair:[/{C_WHITE}] [{C_GOLD}]{s.symbol}[/{C_GOLD}]"
                         f"  [{C_DIM}]TF: {s.interval}[/{C_DIM}]"),
        Text.from_markup(f"[{C_DIM}]Candle close in:[/{C_DIM}]  {countdown}"),
        Text.from_markup(f"[{C_DIM}]Trailing SL:[/{C_DIM}]  {trailing_str}"),
    )

    return Panel(tbl, border_style=C_PANEL, padding=(0, 1))


# ── Panel 2: Indikator Pasar ───────────────────────────────────────────── #
def _build_indicators(s: DashboardState) -> Panel:
    tbl = Table(show_header=False, box=None, expand=True, padding=(0, 1))
    tbl.add_column(style=C_DIM, width=20)
    tbl.add_column(ratio=1)

    # Harga & EMA
    price_str = _fmt_price(s.mid_price)
    ema_str   = _fmt_price(s.ema50)
    bull_bear = _bullish_bearish(s.mid_price, s.ema50)
    tbl.add_row("Last Price",  Text.from_markup(price_str))
    tbl.add_row(f"EMA{s.interval} (50)", Text.assemble(Text.from_markup(ema_str), "  ", bull_bear))
    tbl.add_row("─" * 20, "─" * 25)

    # ADX
    tbl.add_row("ADX (14)", _adx_label(s.adx14))

    # DI+ / DI-
    pdi_col = C_GREEN if (s.plus_di or 0) > (s.minus_di or 0) else C_DIM
    mdi_col = C_RED   if (s.minus_di or 0) > (s.plus_di or 0) else C_DIM
    di_str  = (
        f"[{pdi_col}]+DI {s.plus_di:.1f}[/{pdi_col}]"
        f"  [{C_DIM}]vs[/{C_DIM}]  "
        f"[{mdi_col}]-DI {s.minus_di:.1f}[/{mdi_col}]"
        if s.plus_di is not None and s.minus_di is not None
        else "[dim]—[/dim]"
    )
    tbl.add_row("Directional", Text.from_markup(di_str))
    tbl.add_row("RSI (14)",    _rsi_label(s.rsi14))

    atr_str = (
        f"[white]{s.atr14:,.2f}[/white]  [{C_DIM}](norm: {s.atr14/s.mid_price*100:.3f}%)[/{C_DIM}]"
        if s.atr14 is not None and s.mid_price
        else "[dim]—[/dim]"
    )
    tbl.add_row("ATR (14)", Text.from_markup(atr_str))

    vol_str = (
        f"[white]{s.vol_ratio_20:.2f}×[/white]  [{C_DIM}]vs SMA20[/{C_DIM}]"
        if s.vol_ratio_20 is not None
        else "[dim]—[/dim]"
    )
    tbl.add_row("Volume Ratio", Text.from_markup(vol_str))

    return Panel(tbl, title="[bold]📊 Market & Indicators[/bold]",
                 border_style="cyan", padding=(0, 1))


# ── Panel 3: ML ONNX ──────────────────────────────────────────────────── #
def _build_ml(s: DashboardState) -> Panel:
    tbl = Table(show_header=False, box=None, expand=True, padding=(0, 1))
    tbl.add_column(style=C_DIM, width=20)
    tbl.add_column(ratio=1)

    enabled_str = (
        f"[{C_GREEN}]✔ ACTIVE[/{C_GREEN}]"
        if s.ml_enabled
        else f"[{C_DIM}]✘ DISABLED[/{C_DIM}]"
    )
    tbl.add_row("Status", Text.from_markup(enabled_str))
    tbl.add_row("Model",  Text(s.ml_model_name, style="italic dim"))
    tbl.add_row("Threshold", Text(f"{s.ml_threshold:.2f}", style=C_WHITE))
    tbl.add_row("─" * 20, "─" * 25)

    # probabilitas terakhir
    if s.ml_last_prob is not None:
        bar_width = 20
        filled    = int(s.ml_last_prob * bar_width)
        bar_col   = C_GREEN if s.ml_last_prob >= s.ml_threshold else C_RED
        bar       = f"[{bar_col}]{'█' * filled}[/{bar_col}][dim]{'░' * (bar_width - filled)}[/dim]"
        prob_str  = f"{s.ml_last_prob:.3f}  {bar}"
    else:
        prob_str = "[dim]—[/dim]"

    tbl.add_row("Last p(win)", Text.from_markup(prob_str))

    result_col = _ml_result_style(s.ml_last_result)
    tbl.add_row("Signal Filter",
                Text.from_markup(f"[{result_col}]◆ {s.ml_last_result}[/{result_col}]"))

    return Panel(tbl, title="[bold]🤖 Machine Learning (ONNX)[/bold]",
                 border_style="bright_magenta", padding=(0, 1))


# ── Panel 4: Posisi & Risk ────────────────────────────────────────────── #
def _build_position(s: DashboardState) -> Panel:
    tbl = Table(show_header=False, box=None, expand=True, padding=(0, 1))
    tbl.add_column(style=C_DIM, width=20)
    tbl.add_column(ratio=1)

    if s.pos_symbol:
        side_col = C_GREEN if s.pos_side == "BUY" else C_RED
        side_arrow = "▲" if s.pos_side == "BUY" else "▼"
        tbl.add_row("Symbol",
                    Text.from_markup(f"[{C_GOLD}]{s.pos_symbol}[/{C_GOLD}]"))
        tbl.add_row("Side",
                    Text.from_markup(f"[{side_col}]{side_arrow} {s.pos_side}[/{side_col}]"))
        tbl.add_row("Size",
                    Text.from_markup(f"[white]{s.pos_size:.4f}[/white]" if s.pos_size else "—"))
        tbl.add_row("Entry Price",  Text.from_markup(_fmt_price(s.pos_entry)))
        tbl.add_row("Stop Loss",
                    Text.from_markup(f"[{C_RED}]{_fmt_price(s.pos_sl)}[/{C_RED}]"))
        tbl.add_row("Take Profit",
                    Text.from_markup(f"[{C_GREEN}]{_fmt_price(s.pos_tp)}[/{C_GREEN}]"))
        tbl.add_row("─" * 20, "─" * 25)
        # Floating PnL
        fpnl = s.pos_float_pnl
        fpnl_col = C_GREEN if (fpnl or 0) >= 0 else C_RED
        fpnl_str = f"[{fpnl_col}]{fpnl:+.2f} USDT[/{fpnl_col}]" if fpnl is not None else "[dim]—[/dim]"
        tbl.add_row("Floating PnL", Text.from_markup(fpnl_str))
    else:
        tbl.add_row("Position", Text("NO OPEN POSITION", style=C_DIM))

    tbl.add_row("─" * 20, "─" * 25)

    # Akun
    tbl.add_row("Balance",  Text.from_markup(_fmt_price(s.balance)))
    tbl.add_row("Equity",   Text.from_markup(_fmt_price(s.equity)))
    tbl.add_row("Daily PnL", Text.from_markup(_fmt_pct(s.daily_pnl_pct)))

    # Kill Switch
    if s.kill_triggered:
        ks_str = f"[{C_RED}]⚠ TRIGGERED — NEW ENTRIES BLOCKED[/{C_RED}]"
    else:
        ks_str = f"[{C_GREEN}]✔ OK  (−5% limit)[/{C_GREEN}]"
    tbl.add_row("Kill Switch", Text.from_markup(ks_str))

    return Panel(tbl, title="[bold]💰 Position & Risk Manager[/bold]",
                 border_style="green", padding=(0, 1))


# ── Panel 5: Log Feed ─────────────────────────────────────────────────── #
def _build_log(capture: _LogCapture) -> Panel:
    lines = list(capture.records)[:LOG_MAX_LINES]
    text  = Text()
    for i, line in enumerate(lines):
        # baris paling baru = terang, makin lama makin redup
        alpha = max(0, 1.0 - i * 0.12)
        style = "white" if alpha > 0.7 else ("bright_black" if alpha > 0.3 else "grey23")
        text.append(line + "\n", style=style)
    return Panel(text or Text("—", style=C_DIM),
                 title="[bold]📋 Log Feed[/bold]",
                 border_style="bright_black", padding=(0, 1))


# ── Layout assembler ──────────────────────────────────────────────────── #
def _build_layout(s: DashboardState, capture: _LogCapture) -> Layout:
    layout = Layout()

    layout.split_column(
        Layout(name="header",  size=5),
        Layout(name="middle",  ratio=1),
        Layout(name="log",     size=LOG_MAX_LINES + 2),
    )

    layout["middle"].split_row(
        Layout(name="indicators", ratio=5),
        Layout(name="ml",         ratio=4),
        Layout(name="position",   ratio=5),
    )

    layout["header"].update(_build_header(s))
    layout["indicators"].update(_build_indicators(s))
    layout["ml"].update(_build_ml(s))
    layout["position"].update(_build_position(s))
    layout["log"].update(_build_log(capture))

    return layout


# ────────────────────────────────────────────────────────────────────────────
# DashboardCollector – background thread yang pull data dari engine
# ────────────────────────────────────────────────────────────────────────────
class DashboardCollector(threading.Thread):
    """Pull data dari engine tiap REFRESH_INTERVAL detik → update DashboardState."""

    def __init__(self, engine: "TradingEngine", state: DashboardState,
                 interval: float = REFRESH_INTERVAL):
        super().__init__(daemon=True, name="DashboardCollector")
        self.engine   = engine
        self.state    = state
        self.interval = interval
        self._stop    = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        while not self._stop.is_set():
            try:
                self._collect()
            except Exception as e:
                self.state.update(last_error=str(e))
            self._stop.wait(self.interval)

    def _collect(self):
        eng   = self.engine
        cfg   = eng.client.config

        updates: dict = {
            "symbol":   cfg.symbol,
            "mode":     "TESTNET" if cfg.use_testnet else "MAINNET",
            "ml_enabled": eng.ml_filter is not None,
            "ml_threshold": eng.ml_filter.threshold if eng.ml_filter else 0.70,
            "ml_model_name": (
                eng.ml_filter.meta.get("model_name", "btcusdt_ml_rf_1h.onnx")
                if eng.ml_filter else "btcusdt_ml_rf_1h.onnx"
            ),
            "trailing_active": bool(
                eng.risk_manager.limits.use_trailing
            ),
            "kill_triggered": bool(eng.daily_state.get("kill_triggered", False)),
            "daily_pnl_pct":  eng.risk_manager.daily_pnl_pct
                               if hasattr(eng.risk_manager, "daily_pnl_pct") else None,
            "last_run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

        # ── Akun (equity / balance) ──────────────────────────────────
        try:
            acc   = eng.client.get_account_state()
            equity  = float(acc.get("totalMarginBalance") or acc.get("totalWalletBalance") or 0)
            balance = float(acc.get("totalWalletBalance") or 0)
            updates["equity"]  = equity  if equity  > 0 else None
            updates["balance"] = balance if balance > 0 else None
        except Exception:
            pass

        # ── Harga + Indikator (dari market snapshot) ────────────────
        try:
            from src.data.market_data import fetch_snapshot
            snap = fetch_snapshot(eng.client, cfg.symbol,
                                  interval=eng.interval, lookback_candles=560)
            updates["mid_price"] = snap.mid_price

            # hitung indikator lewat strategy (sudah ada method _compute_indicators)
            strat = eng.strategy
            if hasattr(strat, "_to_df") and hasattr(strat, "_compute_indicators"):
                df   = strat._to_df(snap.candles)
                df   = strat._compute_indicators(df)
                last = df.iloc[-1]

                def _safe(col):
                    v = last.get(col)
                    return float(v) if v is not None and v == v else None

                updates["ema50"]    = _safe("ema")
                updates["adx14"]    = _safe("adx")
                updates["plus_di"]  = _safe("plus_di")
                updates["minus_di"] = _safe("minus_di")
                updates["rsi14"]    = _safe("rsi")
                updates["atr14"]    = _safe("atr")

                # volume ratio vs SMA20
                import pandas as pd
                v_sma20 = float(df["v"].astype(float).rolling(20).mean().iloc[-1])
                last_v  = float(df["v"].astype(float).iloc[-1])
                if v_sma20 > 0:
                    updates["vol_ratio_20"] = last_v / v_sma20
        except Exception:
            pass

        # ── Posisi terbuka ───────────────────────────────────────────
        try:
            pos = eng.client.get_position(cfg.symbol)
            if pos:
                state_pos = eng.live_positions.get(cfg.symbol, {})
                szi = float(pos.get("szi", 0))
                updates.update({
                    "pos_symbol":    cfg.symbol,
                    "pos_side":      "BUY" if szi > 0 else "SELL",
                    "pos_size":      abs(szi),
                    "pos_entry":     float(pos.get("entryPx", 0)) or None,
                    "pos_sl":        state_pos.get("sl"),
                    "pos_tp":        state_pos.get("tp"),
                    "pos_float_pnl": float(pos.get("unrealizedPnl", 0)) or None,
                })
            else:
                updates.update({
                    "pos_symbol": None, "pos_side": None,
                    "pos_size": None, "pos_entry": None,
                    "pos_sl": None, "pos_tp": None, "pos_float_pnl": None,
                })
        except Exception:
            pass

        self.state.update(**updates)


# ────────────────────────────────────────────────────────────────────────────
# MLProbTracker – hook ke MLSignalFilter agar p(win) terakhir ter-capture
# ────────────────────────────────────────────────────────────────────────────
def patch_ml_filter(ml_filter, dash_state: DashboardState):
    """Monkeypatch allow() di MLSignalFilter untuk logging ke dashboard."""
    if ml_filter is None:
        return

    original_allow = ml_filter.allow

    def _patched_allow(candles, signal, strategy, funding_rate=None):
        p1 = ml_filter.predict_proba(candles, signal, strategy, funding_rate)
        if p1 is None:
            dash_state.update(ml_last_prob=None, ml_last_result="SKIP")
            return False
        result = "PASS" if p1 >= ml_filter.threshold else "SKIP"
        dash_state.update(ml_last_prob=p1, ml_last_result=result)
        return p1 >= ml_filter.threshold

    ml_filter.allow = _patched_allow


def patch_engine_for_dashboard(engine: "TradingEngine", dash_state: DashboardState,
                                next_poll_fn=None):
    """Patch engine supaya dashboard mendapat info signal terakhir & HOLD."""
    original_run_once = engine.run_once

    def _patched_run_once():
        # setelah run, update ml_last_result ke HOLD kalau tidak ada signal terkini
        original_run_once()
        if dash_state.ml_last_result == "—":
            dash_state.update(ml_last_result="HOLD")
        if next_poll_fn:
            dash_state.update(next_poll_ts=next_poll_fn())

    engine.run_once = _patched_run_once


# ────────────────────────────────────────────────────────────────────────────
# DashboardRunner – entry point utama
# ────────────────────────────────────────────────────────────────────────────
class DashboardRunner:
    """
    Jalankan dashboard Rich live di dalam loop utama.

    Contoh penggunaan di main.py::

        from src.ui.dashboard import DashboardRunner, install_log_capture, patch_ml_filter

        log_capture = install_log_capture()
        patch_ml_filter(ml_filter, dash_state)

        runner = DashboardRunner(engine, log_capture)
        runner.start()
        # ... jalankan loop polling ...
        runner.stop()
    """

    def __init__(self, engine: "TradingEngine", log_capture: _LogCapture,
                 refresh_interval: float = REFRESH_INTERVAL):
        self.state    = DashboardState()
        self.capture  = log_capture
        self.engine   = engine
        self.collector = DashboardCollector(engine, self.state, refresh_interval)
        self._console  = Console(force_terminal=True, highlight=False)
        self._live: Live | None = None

    def start(self):
        self.collector.start()

    def stop(self):
        self.collector.stop()
        if self._live:
            self._live.stop()

    def render_once(self) -> Layout:
        """Render frame tunggal (berguna untuk testing)."""
        return _build_layout(self.state.snapshot(), self.capture)

    def run_live(self, poll_fn, kill_switch_fn, poll_interval_s: int,
                 kill_switch_interval_s: int = 60):
        """
        Gantikan loop utama main.py: jalankan polling engine sambil
        merender dashboard Rich secara live.

        Args:
            poll_fn: callable yang menjalankan engine.run_once()
            kill_switch_fn: callable untuk monitor kill switch
            poll_interval_s: interval poll (detik, selaras boundary candle)
            kill_switch_interval_s: interval cek kill switch
        """
        from main import seconds_until_next_poll  # hindari circular import

        with Live(
            _build_layout(self.state.snapshot(), self.capture),
            console=self._console,
            refresh_per_second=1.0 / REFRESH_INTERVAL,
            screen=True,
        ) as live:
            self._live = live
            while True:
                # Update next poll countdown
                next_poll_ts = time.time() + seconds_until_next_poll(poll_interval_s)
                self.state.update(next_poll_ts=next_poll_ts)

                # Jalankan engine
                try:
                    poll_fn()
                except Exception as e:
                    self.state.update(last_error=str(e))

                # Refresh sampai poll berikutnya
                deadline = next_poll_ts
                while True:
                    live.update(_build_layout(self.state.snapshot(), self.capture))
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    time.sleep(min(kill_switch_interval_s, remaining, REFRESH_INTERVAL))
                    try:
                        kill_switch_fn()
                    except Exception:
                        pass
