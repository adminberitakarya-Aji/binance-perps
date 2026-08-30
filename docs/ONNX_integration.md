# Integrasi ONNX — Konfigurasi Produksi (Perlu Retrain dengan Data Binance)

> ⚠️ **Status:** Model yang ada (`btc_ml_rf_1h.onnx`) dilatih dengan data
> Hyperliquid. Setelah migrasi ke Binance USDⓈ-M Futures, model **harus
> di-retrain** dengan data Binance baru (fee berbeda, distribusi funding berbeda).
> Model baru akan disimpan sebagai `models/btcusdt_ml_rf_1h.onnx`.

Hasil walk-forward 3 tahun di data Binance (target setelah retrain): **p≥0.60 →
E[r_net] positif**. Model produksi dilatih di SELURUH data yang tersedia dari
Binance USDⓈ-M Futures.

## Artefak (Target Setelah Retrain)

| File | Isi |
|---|---|
| `models/btcusdt_ml_rf_1h.onnx` | RandomForest (150 tree, depth 6), opset 12, input `float_input` float32 `[None,16]` |
| `models/btcusdt_ml_rf_1h.meta.json` | Urutan fitur, threshold, konfigurasi risiko |
| Regenerasi | `python -m src.ml.export_onnx --dataset data/BTCUSDT_1h_market_ml_dataset.csv` |

## Spesifikasi I/O ONNX

- Input: `float_input`, matriks float32 `[N,16]` — **urutan kolom = `feature_order`
  di meta.json**, jangan diubah:
  `dist_to_ema_atr, adx_main, adx_pdi, adx_mdi, adx_di_diff, rsi, atr_normalized,
  body_atr, upper_shadow_atr, lower_shadow_atr, hour, day_of_week, signal_type,
  vol_ratio_20, vol_ratio_100, funding_rate`
- Output (zipmap OFF): `[0]` = label int64, `[1]` = probabilitas float `[N,2]`,
  `class_order = [0,1]` → **kolom 1 = p(win)**.
- Keputusan: `p1 >= 0.60` → eksekusi sinyal; di bawah threshold → skip.

## Rumus fitur (WAJIB identik dengan exporter — `src/ml/export_dataset.py`)

Semua fitur candle dihitung di **bar sinyal i** (bar yang memicu kandidat),
dengan ATR14 bar i sebagai penyebut; indikator: EMA50/ADX14/RSI14/ATR14.

```
dist_to_ema_atr   = (close - EMA50) / ATR14
adx_main          = ADX main (period 14)
adx_pdi / adx_mdi = +DI / -DI (period 14)
adx_di_diff       = adx_pdi - adx_mdi
rsi               = RSI(14)
atr_normalized    = ATR14 / close * 1000.0
body_atr          = abs(close - open) / ATR14
upper_shadow_atr  = (high - max(open, close)) / ATR14
lower_shadow_atr  = (min(open, close) - low) / ATR14
hour              = jam UTC bar open (0-23)
day_of_week       = 0=Senin..6=Minggu
signal_type       = 1 (BUY) / 2 (SELL)
vol_ratio_20      = volume / SMA20(volume)
vol_ratio_100     = volume / SMA100(volume)
funding_rate      = funding rate Binance terbaru saat sinyal (per 8 jam, raw)
```

Deteksi kandidat (threshold sumber, dari `TrendReversalStrategy`):
- BUY: `close > EMA50` && `ADX >= 15` && `+DI > -DI` && `RSI < 65` (dengan
  konfirmasi bar prev sesuai strategi), atau reversal: `RSI <= 35` + pin bar bawah.
- SELL: mirror penuh.

`funding_rate`: ambil dari Binance `GET /fapi/v1/fundingRate` (1 rekam terakhir).
Unit = rate per 8 jam mentah (mis. `0.0001`), SAMA dengan skala training
(`data/BTCUSDT_funding.csv`).

## Parameter risiko (konsisten dengan label training)

| Parameter | Nilai |
|---|---|
| Entry | taker (market) di close bar sinyal |
| Fee taker | 0.05% per sisi (Binance USDⓈ-M standar) |
| SL | 2.0 × ATR14 |
| TP | 1.5 × jarak SL (RR 1.5) |
| Horizon label | 30 bar |
| Risk per trade | 1% equity (RiskLimits) |
| Kill switch | max drawdown harian sesuai `src/risk/manager.py` |

## Pemeliharaan model

1. **Retrain + re-derive threshold tiap ±3 bulan**: jalankan ulang
   `export_dataset` → `train_model` → `export_onnx` → validasi backtest.
2. Bandingkan distribusi probabilitas live vs training; drift besar = retraining.
3. Validasi akhir sebelum go-live: jalankan backtest lengkap di data 1H Binance
   (retensi penuh tersedia via Binance Vision S3).
