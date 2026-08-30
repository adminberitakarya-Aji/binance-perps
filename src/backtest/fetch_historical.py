"""
Fetch candle historis dari Binance USDⓈ-M Futures (fapi / Binance Vision S3 archive)
dan simpan ke CSV untuk backtest.
Endpoint publik, tidak memerlukan API key / signing:

    python -m src.backtest.fetch_historical --symbol BTCUSDT --interval 1h --days 365

Hasilnya disimpan di data/<symbol>_<interval>.csv
"""

import argparse
import calendar
import csv
import io
import os
import time
import zipfile

import requests

FAPI_URL = "https://fapi.binance.com/fapi/v1/klines"
SPOT_URL = "https://api.binance.com/api/v3/klines"
TIMEOUT = 5
SLEEP = 0.1

_UNIT_MIN = {"m": 1, "h": 60, "d": 1440}


def _interval_minutes(interval: str) -> int:
    return int(interval[:-1]) * _UNIT_MIN[interval[-1]]


def fetch_from_vision_s3(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Fetch arsip resmi Binance Vision (data.binance.vision).
    Dapat diakses bebas bahkan saat API domain terblokir ISP.
    """
    interval_ms = _interval_minutes(interval) * 60_000
    out = {}

    def _parse_zip(content):
        zf = zipfile.ZipFile(io.BytesIO(content))
        rows = zf.read(zf.namelist()[0]).decode().strip().split("\n")
        for line in rows:
            parts = line.split(",")
            if not parts[0].strip().isdigit():
                continue
            ts = int(parts[0])
            t = ts // 1000 if ts > 10**14 else ts
            if t < start_ms or t > end_ms:
                continue
            out[t] = {
                "t": t,
                "T": t + interval_ms - 1,
                "o": parts[1],
                "h": parts[2],
                "l": parts[3],
                "c": parts[4],
                "v": parts[5],
                "n": parts[8] if len(parts) > 8 else "",
            }

    # 1) zip bulanan
    m_start = time.gmtime(start_ms / 1000)
    y, m = m_start.tm_year, m_start.tm_mon
    now = time.gmtime()
    while (y, m) <= (now.tm_year, now.tm_mon):
        # Coba futures um dulu, lalu spot
        urls = [
            f"https://data.binance.vision/data/futures/um/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{y:04d}-{m:02d}.zip",
            f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{y:04d}-{m:02d}.zip",
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=15)
                if r.status_code == 200:
                    _parse_zip(r.content)
                    break
            except Exception:
                pass
        m += 1
        if m > 12:
            y, m = y + 1, 1
        time.sleep(SLEEP)

    # 2) sisa hari di bulan berjalan
    day_ms = 86_400_000
    month_start_ms = calendar.timegm(
        time.strptime(time.strftime("%Y-%m-01", time.gmtime(end_ms / 1000)), "%Y-%m-%d")
    ) * 1000
    day = month_start_ms
    while day <= end_ms:
        gt = time.gmtime(day / 1000)
        urls = [
            f"https://data.binance.vision/data/futures/um/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{gt.tm_year:04d}-{gt.tm_mon:02d}-{gt.tm_mday:02d}.zip",
            f"https://data.binance.vision/data/spot/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{gt.tm_year:04d}-{gt.tm_mon:02d}-{gt.tm_mday:02d}.zip",
        ]
        for url in urls:
            try:
                r = requests.get(url, timeout=10)
                if r.status_code == 200:
                    _parse_zip(r.content)
                    break
            except Exception:
                pass
        day += day_ms
        time.sleep(SLEEP)

    return [out[t] for t in sorted(out)]


def fetch_from_api(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Fetch langsung via REST klines endpoint."""
    interval_ms = _interval_minutes(interval) * 60_000
    out = {}
    cursor = start_ms

    while cursor < end_ms:
        r = None
        for base_url in [FAPI_URL, SPOT_URL]:
            try:
                r = requests.get(base_url, params={
                    "symbol": symbol,
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1500,
                }, timeout=TIMEOUT)
                if r.status_code == 200:
                    break
            except Exception:
                continue

        if r is None or r.status_code != 200:
            break

        rows = r.json()
        if not rows or not isinstance(rows, list):
            break

        for row in rows:
            t = int(row[0])
            out[t] = {
                "t": t,
                "T": int(row[6]),
                "o": row[1],
                "h": row[2],
                "l": row[3],
                "c": row[4],
                "v": row[5],
                "n": row[8] if len(row) > 8 else 0,
            }

        last_t = int(rows[-1][0])
        next_cursor = last_t + interval_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        time.sleep(SLEEP)

    return [out[t] for t in sorted(out)]


def fetch_and_save(symbol: str = "BTCUSDT", interval: str = "1h", days: int = 365, out: str | None = None):
    now_ms = int(time.time() * 1000)
    interval_ms = _interval_minutes(interval) * 60_000
    start_ms = now_ms - interval_ms * ((days * 86_400_000) // interval_ms)

    print(f"Mengunduh {symbol} {interval} klines Binance ({days} hari terakhir)...")

    # 1. Coba Binance Vision S3 (arsip penuh, sangat stabil & anti-blokir)
    print("Mencoba Binance Vision S3...")
    candles = fetch_from_vision_s3(symbol, interval, start_ms, now_ms)
    source = "Binance Vision S3"

    # 2. Fallback ke Direct REST API jika S3 kosong
    if not candles:
        print("Mencoba REST API Binance...")
        candles = fetch_from_api(symbol, interval, start_ms, now_ms)
        source = "Binance REST API"

    if not candles:
        print("Peringatan: Gagal mendapatkan candle dari semua sumber.")
        return

    os.makedirs("data", exist_ok=True)
    out_path = out or f"data/{symbol}_{interval}.csv"
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["t", "T", "o", "h", "l", "c", "v", "n"])
        writer.writeheader()
        writer.writerows(candles)

    first = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[0]["t"] / 1000))
    last = time.strftime("%Y-%m-%d %H:%M", time.gmtime(candles[-1]["t"] / 1000))
    print(f"Selesai (sumber: {source}): {len(candles)} candle ({first} s/d {last} UTC) disimpan ke {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch candle historis Binance Futures")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--interval", default="1h")
    parser.add_argument("--days", type=int, default=365)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    fetch_and_save(args.symbol, args.interval, args.days, args.out)
