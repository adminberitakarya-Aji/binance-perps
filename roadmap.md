# Roadmap: Monitoring, Keselamatan & Kesiapan VPS

> Rencana pengerjaan bot trading Binance USDⓈ-M Futures. Fase 1–4 selesai
> di platform Hyperliquid. Fase 5 adalah migrasi platform ke Binance beserta
> seluruh pembaruan pipeline data ML.

## Status Komponen (Per Fase)

| # | Item | Status aktual |
|---|---|---|
| 1 | Equity asli dari `get_account_state()` | ✅ SELESAI — baca `totalMarginBalance` (Binance) |
| 2 | Tracking daily PnL untuk kill switch | ✅ SELESAI — persist `data/daily_state.json`, reset harian UTC |
| 3 | Logging persisten | ✅ SELESAI — `src/utils/logger.py` (rotasi 5MB×5 + stdout) |
| 4 | Monitoring / alert (Telegram) | ✅ SELESAI — `src/utils/notifier.py` (8 event, silent/loud) |
| 5 | Migrasi platform: Hyperliquid → Binance USDⓈ-M Futures | 🔄 DALAM PENGERJAAN |

---

## Urutan Pengerjaan

```
Fase 1: Logging persisten          ✅ (fondasi — fase 2 & 4 butuh ini)
Fase 2: Kill switch daily PnL       ✅ (keselamatan — paling krusial)
Fase 3: Telegram alert              ✅ (pemantauan — di atas logger)
Fase 4: Rapikan README & .env.example ✅
Fase 5: Migrasi ke Binance USDⓈ-M Futures 🔄
```

---

## Fase 1 — Logging Persisten ✅ SELESAI (2026-08-29)

**Masalah:** `print` ke stdout hilang saat SSH session ditutup / process
crash. Di VPS kita jadi buta saat insiden.

**Desain:**
- File baru: `src/utils/logger.py`
  - stdlib `logging` saja (tanpa dependency baru)
  - `get_logger(name)` → dua handler:
    - `RotatingFileHandler("logs/bot.log", maxBytes=5MB, backupCount=5)`
    - `StreamHandler` (stdout, supaya tetap terlihat saat manual run)
  - Format: `%(asctime)s %(levelname)-7s [%(name)s] %(message)s`
- Ganti `print` → logger di jalur **live saja**: `src/engine.py`,
  `src/execution/executor.py`, `src/client.py`, `main.py`.
  Jalur backtest & tests dipertahankan `print` (tidak perlu file log).
- `logs/` ditambahkan ke `.gitignore`.

**Hasil validasi:** `logs/bot.log` tercipta dan berisi entri ber-timestamp;
tidak ada `print` tersisa di jalur live; semua test suite hijau.

---

## Fase 2 — Kill Switch Daily PnL (Rem Darurat) ✅ SELESAI (2026-08-29)

**Masalah:** `RiskManager.daily_pnl_pct` tidak pernah di-update. Kill switch
-5%/hari ada di kode tapi tidak akan pernah aktif.

**Desain:**
- State harian dipersist: `data/daily_state.json`:
  ```json
  {"date_utc": "2026-08-30", "day_start_equity": 1000.0, "kill_triggered": false}
  ```
- Di `TradingEngine` (sekali per `run_once()`, bukan per symbol):
  1. Ambil equity via `_get_equity_or_none()`.
  2. Jika `date_utc` != hari ini UTC → reset `day_start_equity`, simpan.
  3. `daily_pnl_pct = (equity - day_start_equity) / day_start_equity`
  4. Suntikkan ke `risk_manager.daily_pnl_pct`.
  5. Equity tidak tersedia → JANGAN update tracker (hindari PnL palsu).
- Kill switch menolak ENTRY baru saja; posisi terbuka tetap dikelola
  (SL/TP/trailing tetap jalan).

**Batasan yang disadari:**
- Deposit/withdrawal di tengah hari terhitung sebagai "PnL" → bisa
  memicu kill switch salah. Di testnet tidak relevan.
- Zona waktu pakai **UTC** (konvensi crypto), bukan waktu server VPS.

**Hasil validasi:** suite `tests/test_daily_kill_switch.py` 5 test PASS;
regresi backtest & strategy suite hijau.

---

## Fase 3 — Telegram Alert ✅ SELESAI (2026-08-29)

**Masalah:** Bot headless di VPS tanpa cara tahu: entry apa yang terjadi,
apakah SL/TP terpasang, apakah kill switch terpicu, apakah ada error.

**Desain:**
- File baru: `src/utils/notifier.py`
  - Class `TelegramNotifier`, HTTP POST stdlib `urllib.request` ke
    `https://api.telegram.org/bot<TOKEN>/sendMessage` — tanpa dependency baru.
  - Timeout 10 detik; kegagalan kirim TIDAK crash bot (swallow + log warning).
  - Mode silent otomatis kalau `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` kosong.
- 8 event yang mengirim alert: entry, trailing, closed, kill switch, force-close
  (proteksi), force-close (trailing), error, heartbeat harian.

**Hasil validasi:** `tests/test_notifier.py` 4 test PASS; token palsu ke API
Telegram nyata tertelan jadi warning tanpa crash.

---

## Fase 4 — Rapikan README & .env.example ✅ SELESAI (2026-08-29)

README di-rewrite penuh; `.env.example` sinkron dengan `src/config.py`.

---

## Fase 5 — Migrasi Platform ke Binance USDⓈ-M Futures 🔄 DALAM PENGERJAAN

**Latar belakang:** Bot sebelumnya berjalan di platform Hyperliquid. Seluruh
infrastruktur sekarang dimigrasikan ke Binance USDⓈ-M Futures (fapi) agar
dapat memanfaatkan likuiditas yang lebih besar, fee yang lebih kompetitif,
dan data historis yang lebih panjang.

### Perbedaan platform utama

| Aspek | Hyperliquid (lama) | Binance USDⓈ-M (baru) |
|---|---|---|
| Autentikasi | Ethereum private key (EIP-712) | HMAC-SHA256 (API Key + Secret) |
| Format simbol | `BTC` | `BTCUSDT` |
| Presisi harga/size | `szDecimals` (5 sig-fig) | `tickSize` / `stepSize` (exchangeInfo) |
| SL/TP protection | `bulk_orders` grouping `normalTpsl` | `STOP_MARKET` + `TAKE_PROFIT_MARKET` reduceOnly |
| Modifikasi SL trailing | `modify_order` in-place | Cancel + place baru (place dulu, lalu cancel lama) |
| Fee taker | 0.035% per sisi | **0.05% per sisi** |
| Periode funding | Per jam | **Per 8 jam** |
| Min notional | $10 | **$5** |

### Checklist pengerjaan Fase 5

- [x] Hapus data lama Hyperliquid (`data/` dikosongkan)
- [x] Update seluruh dokumentasi (README, roadmap, docs/)
- [ ] Update `requirements.txt` (hapus `hyperliquid-python-sdk`, `eth-account`)
- [ ] Update `src/config.py` dan `.env.example` → variabel Binance
- [ ] Implementasi `BinanceFuturesClient` di `src/client.py`
- [ ] Update `src/data/market_data.py` (parser klines Binance)
- [ ] Update `src/execution/executor.py` (min notional $5)
- [ ] Update `src/engine.py` (equity dari `totalMarginBalance`)
- [ ] Update `main.py` (symbol BTCUSDT, init BinanceFuturesClient)
- [ ] Update `src/backtest/fetch_historical.py` → Binance fapi klines
- [ ] Update `src/backtest/fetch_funding.py` → Binance funding rate 8h
- [ ] Update `src/ml/export_dataset.py` (FEE_RATE=0.0005, FUNDING_HOURLY Binance)
- [ ] Update test suite (mock client Binance, presisi tickSize/stepSize)
- [ ] Fetch data historis Binance baru
- [ ] Retrain model ML dengan data Binance
- [ ] Smoke test live di testnet Binance

### Pipeline data ML (Binance)

```bash
# 1. Fetch klines (publik, tanpa API key)
python -m src.backtest.fetch_historical --symbol BTCUSDT --interval 1h --days 365

# 2. Fetch funding rate historis (8 jam/periode)
python -m src.backtest.fetch_funding --symbol BTCUSDT --days 730

# 3. Ekspor dataset ML
python -m src.ml.export_dataset \
  --file data/BTCUSDT_1h.csv --interval 1h \
  --funding-file data/BTCUSDT_funding.csv --simulate-trailing

# 4. Training
python -m src.ml.train_model --file data/BTCUSDT_1h_market_ml_dataset.csv

# 5. Export ONNX
python -m src.ml.export_onnx
```

---

## Luar Scope (dipegang untuk nanti)

1. **Process supervision VPS** (systemd unit / NSSM / Task Scheduler +
   auto-restart saat boot) — disiapkan terpisah.
2. **Maker/limit entry** & selektivitas sinyal — riset edge, bukan infra.
3. **Deposit/withdrawal tracking** sebagai pengganti equity-snapshot untuk
   kill switch yang lebih akurat.
