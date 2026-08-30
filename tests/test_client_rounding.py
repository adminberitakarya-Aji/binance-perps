"""
Test pembulatan harga (tickSize) dan ukuran (stepSize) sesuai aturan Binance Futures.
Fungsi murni tanpa jaringan.

Jalankan: python tests/test_client_rounding.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.client import round_px_binance, round_sz_binance


def check(name: str, cond: bool, detail: str = ""):
    if not cond:
        raise AssertionError(f"GAGAL: {name} {detail}")
    print(f"OK: {name}")


# --- 1. BTCUSDT (tickSize = 0.10): pembulatan ke 0.1 terdekat ---
out = round_px_binance(61234.56, tick_size=0.1)
check("BTCUSDT 61234.56 (tick=0.1) -> 61234.6", out == 61234.6, f"dapat {out}")

out = round_px_binance(60123.44, tick_size=0.1)
check("BTCUSDT 60123.44 (tick=0.1) -> 60123.4", out == 60123.4, f"dapat {out}")

out = round_px_binance(60123.0, tick_size=0.1)
check("BTCUSDT 60123.0 (tick=0.1) -> 60123.0", out == 60123.0, f"dapat {out}")

# --- 2. ETHUSDT (tickSize = 0.01): 2 desimal ---
out = round_px_binance(3123.45678, tick_size=0.01)
check("ETHUSDT 3123.45678 (tick=0.01) -> 3123.46", out == 3123.46, f"dapat {out}")

# --- 3. Coin murah (mis. DOGEUSDT tickSize = 0.00001): 5 desimal ---
out = round_px_binance(0.12345678, tick_size=0.00001)
check("DOGE 0.12345678 (tick=0.00001) -> 0.12346", out == 0.12346, f"dapat {out}")

# --- 4. Idempoten ---
check("idempoten px", round_px_binance(round_px_binance(61234.56, 0.1), 0.1) == 61234.6)

print("\nSemua test round_px_binance lulus.")

# =====================================================================
# round_sz_binance: pembulatan UKURAN order (LOT_SIZE stepSize)
# =====================================================================

# --- 1. BTCUSDT (stepSize = 0.001): floor ke 3 desimal ---
out = round_sz_binance(0.123456789, step_size=0.001)
check("BTCUSDT 0.123456789 (step=0.001) -> 0.123", out == 0.123, f"dapat {out}")

# --- 2. Step size besar (mis. SOL stepSize = 1.0 atau 0.1) ---
out = round_sz_binance(123.456789, step_size=0.1)
check("stepSize=0.1: 123.456789 -> 123.4", out == 123.4, f"dapat {out}")

out = round_sz_binance(123.456789, step_size=1.0)
check("stepSize=1.0: 123.456789 -> 123.0", out == 123.0, f"dapat {out}")

# --- 3. Idempoten ---
check("idempoten sz", round_sz_binance(round_sz_binance(0.123456, 0.001), 0.001) == 0.123)

print("Semua test round_sz_binance lulus.\n")
