"""
Fetch riwayat funding rate dari Binance USDⓈ-M Futures (/fapi/v1/fundingRate,
1000 rekam/request, endpoint publik) untuk fitur ML & estimasi biaya.

    python -m src.backtest.fetch_funding --symbol BTCUSDT --days 730

Output: data/BTCUSDT_funding.csv (time, funding_rate) -- rate per 8 jam.
"""

import argparse
import csv
import os
import time

import requests

URL = "https://fapi.binance.com/fapi/v1/fundingRate"
TIMEOUT = 20
SLEEP = 0.15


def fetch_funding(symbol: str = "BTCUSDT", days: int = 730) -> list:
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86_400_000
    out = {}
    cursor = start_ms

    print(f"Fetching funding rate {symbol} dari Binance ({days} hari terakhir)...")

    while cursor < end_ms:
        try:
            r = requests.get(URL, params={
                "symbol": symbol,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            }, timeout=TIMEOUT)
            r.raise_for_status()
            rows = r.json()
        except Exception as e:
            print(f"Error fetching funding cursor {cursor}: {e}")
            break

        if not rows or not isinstance(rows, list):
            break

        for row in rows:
            t = int(row["fundingTime"])
            out[t] = float(row["fundingRate"])

        last_t = int(rows[-1]["fundingTime"])
        if last_t <= cursor:
            break
        cursor = last_t + 1
        if len(rows) < 1000:
            break
        time.sleep(SLEEP)

    return [(t, out[t]) for t in sorted(out)]


def main():
    ap = argparse.ArgumentParser(description="Fetch funding rate Binance Futures")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--coin", default=None, help="Alias untuk --symbol")
    ap.add_argument("--days", type=int, default=730)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    symbol = args.symbol or (f"{args.coin}USDT" if args.coin and not args.coin.endswith("USDT") else args.coin) or "BTCUSDT"
    rows = fetch_funding(symbol, args.days)
    if not rows:
        raise SystemExit(f"Funding rate {symbol} kosong atau gagal di-fetch.")

    os.makedirs("data", exist_ok=True)
    out_path = args.out or f"data/{symbol}_funding.csv"
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "funding_rate"])
        w.writerows(rows)

    rates = [r for _, r in rows]
    first = time.strftime("%Y-%m-%d", time.gmtime(rows[0][0] / 1000))
    last = time.strftime("%Y-%m-%d", time.gmtime(rows[-1][0] / 1000))
    print(f"{len(rows)} rekam disimpan -> {out_path}")
    print(f"rentang : {first} s/d {last} UTC")
    print(f"mean    : {sum(rates) / len(rates):+.6f} | mean|rate|: "
          f"{sum(abs(r) for r in rates) / len(rates):.6f}")


if __name__ == "__main__":
    main()
