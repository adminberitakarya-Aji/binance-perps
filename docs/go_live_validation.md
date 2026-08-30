# Go-Live Validation — BTCUSDT 1H di data Binance USDⓈ-M Futures

> ⚠️ **Status:** Dokumen ini akan diperbarui setelah data Binance baru berhasil
> di-fetch dan model ML di-retrain. Hasil validasi lama (data Hyperliquid)
> sudah tidak relevan setelah migrasi platform.

## Hasil Validasi Sebelumnya (Data Hyperliquid — Tidak Berlaku Lagi)

Validasi lama di data HL BTC 1H (Feb–Agu 2026) menunjukkan:
- Filter ML justru memilih trade yang lebih buruk dari baseline.
- Trailing stop adalah degradasi utama (PF turun dari 1.01 ke 0.85).
- Temuan ini kemungkinan bersifat **regime-dependent** dan tidak berlaku
  untuk data Binance dengan distribusi fee & funding yang berbeda.

## Rencana Validasi Binance (Setelah Retrain)

### Langkah-langkah

1. **Fetch data Binance** (klines 1H + funding rate):
   ```bash
   python -m src.backtest.fetch_historical --symbol BTCUSDT --interval 1h --days 365
   python -m src.backtest.fetch_funding --symbol BTCUSDT --days 730
   ```

2. **Ekspor dataset ML & retrain model:**
   ```bash
   python -m src.ml.export_dataset \
     --file data/BTCUSDT_1h.csv --interval 1h \
     --funding-file data/BTCUSDT_funding.csv --simulate-trailing
   python -m src.ml.train_model --file data/BTCUSDT_1h_market_ml_dataset.csv
   python -m src.ml.export_onnx
   ```

3. **Backtest engine lengkap** (risk 1%, fee Binance 0.05%, funding Binance):
   ```bash
   python -m src.backtest.run_backtest --file data/BTCUSDT_1h.csv
   ```

4. **Walk-forward validation** (anchored-expanding, 5 fold, purge 30 bar):
   ```bash
   python -m src.ml.train_model --file data/BTCUSDT_1h_market_ml_dataset.csv --wf
   ```

### Kriteria Lolos Go-Live

| Kriteria | Target |
|---|---|
| WR net (setelah fee + funding Binance) | ≥ 45% |
| Profit Factor | ≥ 1.0 (semua 5 fold WF) |
| E[r_net] pada p≥threshold | > 0 R |
| Max Drawdown | ≤ 25% |
| Fold terlemah WF | ≥ break-even |

### Implikasi

- `ML_FILTER_ENABLED` default **false** sampai model Binance lolos validasi.
- Jangan aktifkan filter ML sebelum seluruh langkah di atas selesai dan
  kriteria go-live terpenuhi.
- Pertimbangkan untuk menonaktifkan trailing stop (set `use_trailing=False`)
  jika PF degradasi terulang — temuan HL: trailing ON memperburuk PF dari 1.01 → 0.85.

## Catatan untuk Retrain Berikutnya

1. **Regime-aware split**: pastikan periode terbaru (2026) masuk beberapa kali
   di train set, bukan hanya di fold test terakhir.
2. **Selaraskan simulasi label dengan engine**: gunakan `--simulate-trailing`
   di export_dataset jika trailing aktif di live.
3. **Perluas fitur regime**: realized vol 7d, jarak dari ATH/ATL 90d — hipotesis:
   edge ada di regime volatilitas tertentu saja.
4. **Paper trading** dulu di testnet Binance: kumpulkan slippage & funding aktual
   sebelum go-live dengan uang riil.
