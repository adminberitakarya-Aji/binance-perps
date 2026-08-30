# Binance USDⓈ-M Futures Trading Agent

Bot trading perpetuals kripto di Binance USDⓈ-M Futures — strategi trend-reversal
(EMA/ADX/RSI + pin bar/engulfing) dengan filter ML meta-labeling,
strategi pluggable, risk manager, proteksi SL/TP exchange-native, dan
infrastruktur live yang siap VPS: logging persisten, kill switch harian, dan
alert Telegram.

> 💡 **Hasil Validasi Edge (Data Binance 2 Tahun / 17.503 bar 1H):**
> - Strategi mentah tanpa filter: expectancy negatif ($-0.101\text{ R}$, WR 41.8% vs break-even 46.0%).
> - **Dengan Filter ML Random Forest ($p \ge 0.70$):** **Ekspektansi POSITIF $+0.122\text{ R}$ per trade**, **Win Rate Net 55.2%** (di atas break-even 46.0%), dan **3 dari 4 fold walk-forward positif** setelah fee taker Binance 0.05% dan funding rate.
> - Model ONNX produksi: [`models/btcusdt_ml_rf_1h.onnx`](file:///d:/binance/models/btcusdt_ml_rf_1h.onnx).

## Status

| Komponen | Status |
|---|---|
| Strategi trend-reversal (EMA/ADX/RSI + filter trend alignment) | ✅ jalan |
| Sizing risk-based (1% equity / jarak SL, cap 3× equity) | ✅ konsisten backtest & live |
| SL/TP + trailing (STOP_MARKET / TAKE_PROFIT_MARKET Binance) | ✅ + force-close otomatis saat proteksi gagal |
| Kill switch harian −5% (basis UTC, persist, reset otomatis) | ✅ |
| Logging persisten (`logs/bot.log`, rotasi 5MB×5) | ✅ |
| Alert Telegram (8 event, info silent / error loud) | ✅ aktif kalau token diisi |
| Fetch data historis dari Binance fapi (klines + funding rate) | ✅ endpoint publik, tanpa API key |
| Pipeline ML dari data Binance (retrain model) | ✅ selesai (model RF 18 fitur, threshold $p \ge 0.70$) |
| Smoke test live testnet Binance (entry + SL/TP pair nyata) | ⏳ siap dijalankan (tinggal isi API key di `.env`) |

Rencana pengerjaan & detail desain: lihat [roadmap.md](roadmap.md).

## Struktur

```
├── main.py                    # entry point: loop utama, wiring semua komponen
├── src/
│   ├── config.py              # baca kredensial dari .env (BINANCE_API_KEY, dll.)
│   ├── client.py              # wrapper Binance USDⓈ-M Futures REST API
│   ├── engine.py              # menyatukan strategy + risk + execution + tracker harian
│   ├── data/market_data.py    # fetch candle + mid price (drop partial bar, anti-repaint)
│   ├── strategy/
│   │   ├── base.py            # interface Strategy + MarketSnapshot/SignalResult
│   │   ├── sma_crossover.py   # contoh strategi sederhana
│   │   └── trend_reversal.py  # strategi perps kripto (EMA/ADX/RSI + pin bar/engulfing)
│   ├── risk/manager.py        # sizing risk-based, kill switch, SL/TP & trailing ATR
│   ├── execution/executor.py  # kirim order final (min notional $5, alert proteksi gagal)
│   ├── backtest/              # fetch historis Binance + engine backtest (fee + funding)
│   │   ├── fetch_historical.py   # fetch klines dari Binance fapi (publik)
│   │   ├── fetch_funding.py      # fetch funding rate 8-jam dari Binance fapi
│   │   ├── fetch_external.py     # fallback multi-sumber (Binance Vision S3, OKX, Gate)
│   │   ├── engine.py             # engine backtest (fee + funding)
│   │   └── run_backtest.py       # runner backtest
│   ├── ml/
│   │   ├── export_dataset.py  # ekspor dataset ML dari candle + fitur + label
│   │   ├── train_model.py     # training RandomForest → simpan model
│   │   ├── export_onnx.py     # konversi model ke ONNX
│   │   └── inference.py       # filter ML live (fail-closed, threshold p≥0.60)
│   └── utils/
│       ├── logger.py          # logging rotasi file + stdout
│       └── notifier.py        # alert Telegram (fire-and-forget)
├── models/                    # model ONNX + metadata (btcusdt_ml_rf_1h.onnx)
├── data/                      # (gitignored) CSV historis Binance + state posisi/harian
├── logs/                      # (gitignored) bot.log
└── tests/                     # suite script + assert (python tests/test_*.py)
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# isi BINANCE_API_KEY dan BINANCE_API_SECRET di .env
```

**Cara membuat API Key Binance:**
1. Login ke [Binance](https://www.binance.com) → **Profile → API Management**
2. Buat API key baru → aktifkan permission **Futures**
3. Untuk testnet: buka [testnet.binancefuture.com](https://testnet.binancefuture.com) → **API Key** (key testnet berbeda dari mainnet)
4. Isi `BINANCE_API_KEY` dan `BINANCE_API_SECRET` di `.env`

> ⚠️ Jangan pernah aktifkan permission **Withdraw** pada API key bot.

## Test koneksi

```bash
python -m src.client
```

Connect ke Binance Futures (testnet atau mainnet sesuai `.env`) dan print mid price
BTCUSDT — cara cepat cek kredensial & koneksi sebelum menjalankan agent penuh.

## Jalankan agent

Tersedia 3 mode eksekusi bot:

### 1. Mode Desktop GUI Settings (MetaTrader 5 Style)
Buka jendela antarmuka visual MT5 untuk mengubah seluruh parameter strategi, ML, DCA, TP/SL, dan Risk:
```powershell
.venv\Scripts\python.exe main.py --settings
```
*(atau alias: `.venv\Scripts\python.exe main.py --gui`)*

### 2. Mode Terminal Visual Dashboard (Rich HUD)
Jalankan bot live dengan tampilan Dashboard Terminal Visual real-time (Header HUD, Sinyal & Indikator, ML Onnx probability bar, Position & DCA Lapis Status, Feed log):
```powershell
.venv\Scripts\python.exe main.py --dashboard
```
*(atau alias: `.venv\Scripts\python.exe main.py --ui`)*

### 3. Mode Log Standar (Headless / Background / VPS)
```powershell
.venv\Scripts\python.exe main.py
```

Default berjalan di **testnet** dan polling otomatis selaras dengan close candle sesuai `TRADING_INTERVAL` di `.env` (+buffer). Ganti `BINANCE_USE_TESTNET=false` di `.env` hanya setelah Anda yakin dengan hasil uji testnet.

## Ganti strategi

Tambahkan class baru di `src/strategy/` yang extend `Strategy` (lihat
`base.py`), lalu ganti satu baris di `main.py`:

```python
strategy = TrendReversalStrategy(require_trend_alignment=True)  # ganti ke strategi kamu
```

## Backtest

**Langkah 1 — fetch data historis dari Binance** (endpoint publik, tanpa API key):

```bash
python -m src.backtest.fetch_historical --symbol BTCUSDT --interval 1h --days 365
```

Hasilnya di `data/BTCUSDT_1h.csv`. Jika koneksi ke `fapi.binance.com` bermasalah,
gunakan fallback dari arsip Binance Vision (S3):

```bash
python -m src.backtest.fetch_external --symbol BTCUSDT --interval 1h --days 365
```

**Langkah 2 — fetch funding rate historis Binance:**

```bash
python -m src.backtest.fetch_funding --symbol BTCUSDT --days 730
```

Hasilnya di `data/BTCUSDT_funding.csv`.

**Langkah 3 — jalankan backtest**, otomatis membandingkan `require_trend_alignment=True` vs `False`:

```bash
python -m src.backtest.run_backtest --file data/BTCUSDT_1h.csv
```

Model biaya di engine sudah realistis:
- **Fee** taker Binance USDⓈ-M: default 0.05% per sisi (round-trip 0.10%)
- **Funding** default dari data nyata Binance (periode 8 jam), dibebankan prorata durasi hold
- **Sizing** risk-based 1% equity per trade — konsisten dengan jalur live

**Batasan backtest ini yang perlu kamu sadari:**
- Entry price = harga close candle saat sinyal muncul, bukan harga tick presisi — hasil real bisa lebih buruk karena slippage
- Tidak ada model liquidation eksplisit
- Hasil backtest yang bagus BUKAN jaminan performa live

## Pipeline ML

**Langkah 1–2** sama dengan fetch data di atas (klines + funding rate).

**Langkah 3 — ekspor dataset ML:**

```bash
python -m src.ml.export_dataset \
  --file data/BTCUSDT_1h.csv \
  --interval 1h \
  --funding-file data/BTCUSDT_funding.csv \
  --simulate-trailing
```

Output: `data/BTCUSDT_1h_market_ml_dataset.csv`

**Langkah 4 — training model:**

```bash
python -m src.ml.train_model --file data/BTCUSDT_1h_market_ml_dataset.csv
```

**Langkah 5 — export ke ONNX:**

```bash
python -m src.ml.export_onnx
```

Output: `models/btcusdt_ml_rf_1h.onnx` + `models/btcusdt_ml_rf_1h.meta.json`

**Aktifkan filter ML di `.env`** setelah model tervalidasi:

```
ML_FILTER_ENABLED=true
ML_MODEL_PATH=models/btcusdt_ml_rf_1h.onnx
```

## Testing

Semua suite memakai konvensi script + assert (tanpa framework):

```bash
python tests/test_backtest_engine.py    # sanity engine backtest (4 skenario sintetis)
python tests/test_trend_reversal.py     # perilaku strategi (7 test, aligned/unaligned)
python tests/test_daily_kill_switch.py  # kill switch: trigger/reset/persist/fallback
python tests/test_notifier.py           # notifier: silent/loud, fail-safe, wiring engine
python tests/test_p1_fixes.py           # perbaikan P1: SL self-healing, fail-closed, dll.
python tests/test_p2_fixes.py           # perbaikan P2: regression lanjutan
```

## Monitoring & Alert Telegram

Isi dua variabel di `.env` untuk mengaktifkan alert (kosong = bot jalan
silent penuh):

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

Langkah sekali-setup:
1. Buat bot via **@BotFather** di Telegram → dapatkan token
2. Kirim pesan apa pun ke bot kamu → buka
   `https://api.telegram.org/bot<TOKEN>/getUpdates` → salin `"chat":{"id":...}`
3. Isi kedua variabel, lalu uji kirim semua template alert:
   `python -m src.utils.notifier` → cek HP

Yang akan masuk ke HP:
| Event | Tipe |
|---|---|
| 🟢 Entry (sinyal + order + SL/TP terpasang) | info, silent |
| 🔁 Trailing (SL digeser) | info, silent |
| 🏁 Posisi tertutup (SL/TP terisi / manual) | info, silent |
| 💓 Heartbeat harian (equity + PnL kemarin + posisi) | info, silent |
| 🛑 Kill switch terpicu (rugi harian ≤ −5%) | **loud** |
| 🔴 Force-close (proteksi / trailing gagal → tutup paksa) | **loud** |
| ❌ Error tak terduga di loop utama | **loud** |

Kegagalan kirim **tidak pernah** mengganggu trading (fire-and-forget,
hanya log warning). File log persisten ada di `logs/bot.log`
(rotasi 5MB × 5) — pantau dengan `tail -f logs/bot.log`.

## Menjalankan di VPS

Bot ini dirancang headless-friendly, tapi **process supervision** ada di
luar scope kode. Instruksi minimal:

1. Clone repo + setup (sama seperti di atas) di VPS
2. Isi `.env` (pastikan file permission restriktif — berisi API key)
3. Uji dulu di testnet: `python -m src.client`, lalu biarkan `BINANCE_USE_TESTNET=true`
4. Pilih salah satu:
   - **Linux (systemd):** buat unit `binancebot.service` dengan
     `ExecStart=/path/ke/.venv/bin/python main.py`, `Restart=always`,
     `RestartSec=30`, `WantedBy=multi-user.target`
   - **Windows:** Task Scheduler (action: run `main.py` at startup) atau NSSM
5. Alert Telegram adalah alarm utama; heartbeat harian (±07:00 WIB) adalah
   bukti bot masih hidup — kalau tidak masuk, cek VPS

## Status pengerjaan & rencana

Daftar TODO lama telah digantikan [roadmap.md](roadmap.md). Fase saat ini:
migrasi platform dari Hyperliquid ke Binance USDⓈ-M Futures. Setelah migrasi
selesai, langkah berikutnya adalah fetch data Binance, retrain model ML, dan
smoke test di testnet Binance.
