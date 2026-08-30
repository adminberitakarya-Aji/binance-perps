# docs/ — Blueprint Pipeline ML (Referensi)

Folder ini menyimpan **blueprint pipeline ML meta-labeling** yang direplikasi
ke data perps kripto (Binance USDⓈ-M Futures BTCUSDT) pada Fase 2. Bukan
bagian dari runtime bot — aman dihapus jika sudah tidak diperlukan, tapi
berguna sebagai spesifikasi acuan.

| File | Fungsi |
|---|---|
| `Export_ML_Dataset.mq5` | Spesifikasi ekspor fitur + labeling historis: 13 fitur ternormalisasi ATR, hanya bar kandidat sinyal, label = simulasi SL (2×ATR) / TP (RR 1.5) ke depan (horizon 30 bar) |
| `train_model.py` | Spesifikasi training: RandomForest (150 tree, depth 6, class_weight balanced), time-split 80/20, ekspor ONNX |
| `ONNX_integration.md` | Dokumentasi integrasi ONNX: spesifikasi I/O, urutan fitur, threshold, pemeliharaan model |
| `go_live_validation.md` | Hasil validasi go-live di data Binance (diperbarui setelah retrain dengan data Binance baru) |

## Catatan penting pipeline ML Binance (Fase 5)

1. **Fee Binance berbeda dari Hyperliquid**: taker 0.05% per sisi (vs 0.035%
   Hyperliquid). `export_dataset.py` sudah diperbarui dengan `FEE_RATE = 0.0005`.
2. **Periode funding Binance 8 jam** (bukan 1 jam HL). `FUNDING_HOURLY` dihitung
   dari data `BTCUSDT_funding.csv` nyata Binance setelah fetch.
3. **Model ML lama (dari data HL) sudah tidak valid** — perlu retrain setelah
   data Binance baru tersedia.
4. WR dasar kandidat ~33–36% pada RR 1.5 → rule-based saja expectancy negatif;
   profitabilitas bergantung penuh pada filter ML yang tervalidasi.
5. **Threshold harus dikalibrasi ulang per dataset Binance** (0.60 dari data HL
   belum tentu optimal untuk Binance).
