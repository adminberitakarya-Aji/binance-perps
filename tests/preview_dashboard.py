"""
Preview dashboard terminal visual dengan data dummy (tanpa koneksi Binance).
Jalankan: python tests/preview_dashboard.py
"""
import sys
import time
import logging

sys.path.insert(0, ".")

from rich.console import Console
from rich.live import Live

from src.ui.dashboard import (
    DashboardState,
    _build_layout,
    install_log_capture,
    REFRESH_INTERVAL,
)

# ── Pasang log capture ────────────────────────────────────────────────── #
log_capture = install_log_capture()
log = logging.getLogger("preview")
logging.basicConfig(level=logging.INFO)

# ── Isi data dummy yang realistis ─────────────────────────────────────── #
s = DashboardState()
s.symbol         = "BTCUSDT"
s.interval       = "1H"
s.mode           = "TESTNET"
s.bot_version    = "v2.0-binance"
s.mid_price      = 95_312.50
s.ema50          = 94_870.20
s.adx14          = 28.7
s.plus_di        = 23.4
s.minus_di       = 14.9
s.rsi14          = 54.1
s.atr14          = 438.50
s.vol_ratio_20   = 1.42
s.ml_enabled     = True
s.ml_threshold   = 0.70
s.ml_last_prob   = 0.743
s.ml_last_result = "PASS"
s.balance        = 5_006.62
s.equity         = 5_031.18
s.daily_pnl_pct  = 0.00492
s.kill_triggered = False
s.trailing_active = True
s.next_poll_ts   = time.time() + 2 * 3600 + 847  # ~2 jam 14 menit lagi

# Simulasikan posisi terbuka
s.pos_symbol    = "BTCUSDT"
s.pos_side      = "BUY"
s.pos_size      = 0.0560
s.pos_entry     = 94_750.00
s.pos_sl        = 93_875.00
s.pos_tp        = 96_500.00
s.pos_float_pnl = 31.64

# ── Isi beberapa baris log dummy ──────────────────────────────────────── #
log.info("[engine] equity=5031.18 baseline=5006.62 daily_pnl=+0.49%%")
log.info("[engine] [BTCUSDT] sinyal=BUY conf=0.65 alasan=FOLLOW BUY: close>EMA, ADX=28.7, RSI=54.1")
log.info("[ml_inference] ML p(win)=0.743 threshold=0.70 -> PASS")
log.info("[executor] ORDER FILLED: BTCUSDT BUY 0.0560 @ 94750.00 (notional=5306.00)")
log.info("[engine] posisi BTCUSDT dicatat: side=B SL=93875.00 TP=96500.00")
log.info("[engine] TRAILING: SL 93450.00 -> 93875.00 (mid=95312.50, modify)")
log.info("[engine] equity=5031.18 baseline=5006.62 daily_pnl=+0.49%%")
log.info("[main] Menunggu poll berikutnya...")

console = Console()

# ── Render preview statis dulu (10 frame auto-refresh) ───────────────── #
print("\nMemuat preview dashboard... (10 detik, Ctrl+C untuk skip)\n")
try:
    with Live(
        _build_layout(s, log_capture),
        console=console,
        refresh_per_second=1,
        screen=True,
    ) as live:
        for i in range(10):
            # Simulasi update kecil tiap detik
            s.next_poll_ts = time.time() + 2 * 3600 + (847 - i * 60)
            s.equity       = 5_031.18 + i * 1.5
            s.pos_float_pnl = 31.64 + i * 1.5
            if i == 3:
                s.ml_last_prob   = 0.682
                s.ml_last_result = "SKIP"
            if i == 6:
                s.ml_last_prob   = 0.715
                s.ml_last_result = "PASS"
            live.update(_build_layout(s, log_capture))
            time.sleep(1)
except KeyboardInterrupt:
    pass

print("\nPreview selesai. Dashboard berfungsi normal!")
print("Untuk menjalankan bot dengan dashboard: python main.py --dashboard")
