"""
Filter sinyal ML untuk live engine & backtest (Fase 2).

Sinkronisasi TF <-> ONNX:
  - TRADING_INTERVAL=15m  -> models/btcusdt_ml_rf_15m.onnx  (19 fitur)
  - TRADING_INTERVAL=30m  -> models/btcusdt_ml_rf_30m.onnx  (19 fitur)
  - TRADING_INTERVAL=1h   -> models/btcusdt_ml_rf_1h.onnx   (18 fitur)
  - Jika model TF spesifik tidak ada -> fallback ke 1h dengan WARNING.

Prinsip FAIL-CLOSED: error apapun saat inferensi -> sinyal DITOLAK.
Feature vector dibangun PERSIS dari feature_order di .meta.json model
yang dimuat, sehingga model 18-fitur (1H) dan 19-fitur (15m/30m)
keduanya berjalan otomatis tanpa modifikasi kode.
"""

import json
import os

import numpy as np
import onnxruntime as ort
import pandas as pd

from src.strategy.base import Signal
from src.utils.logger import get_logger

log = get_logger("ml_inference")

DEFAULT_MODEL_PATH = os.path.join("models", "btcusdt_ml_rf_1h.onnx")


def get_default_model_path_for_interval(interval: str = "1h") -> str:
    """
    Otomatis pilih model ONNX yang sesuai timeframe trading.

    Konvensi nama file: models/btcusdt_ml_rf_{interval}.onnx
      - 15m  -> models/btcusdt_ml_rf_15m.onnx
      - 30m  -> models/btcusdt_ml_rf_30m.onnx
      - 1h   -> models/btcusdt_ml_rf_1h.onnx

    Jika model untuk TF tidak ditemukan, fallback ke 1H dengan WARNING.
    """
    interval_clean = interval.strip().lower()
    candidate = os.path.join("models", f"btcusdt_ml_rf_{interval_clean}.onnx")
    candidate_meta = candidate.replace(".onnx", ".meta.json")

    if os.path.exists(candidate) and os.path.exists(candidate_meta):
        log.info("ML model dipilih sesuai TF [%s]: %s", interval_clean, candidate)
        return candidate

    log.warning(
        "Model untuk TF [%s] tidak ditemukan (%s) "
        "-> FALLBACK ke model 1H (%s). "
        "Akurasi filter mungkin tidak optimal untuk TF ini. "
        "Latih model baru dengan: python -m src.ml.train_model",
        interval_clean, candidate, DEFAULT_MODEL_PATH,
    )
    return DEFAULT_MODEL_PATH


class MLSignalFilter:
    def __init__(self, model_path: str = DEFAULT_MODEL_PATH,
                 threshold: float | None = None):
        meta_path = model_path.replace(".onnx", ".meta.json")
        if not os.path.exists(model_path) or not os.path.exists(meta_path):
            raise FileNotFoundError(
                f"Model/metadata tidak ditemukan: {model_path}, {meta_path}\n"
                f"Latih model baru: python -m src.ml.train_model"
            )
        with open(meta_path) as f:
            self.meta = json.load(f)

        self.feature_order: list = self.meta["feature_order"]
        self.threshold = threshold if threshold is not None \
            else float(self.meta["decision_rule"]["threshold"])
        self.input_name = self.meta["input"]["name"]

        # Interval model (untuk display dashboard & validasi)
        self.model_interval: str = (
            self.meta.get("interval")
            or self.meta.get("config", {}).get("interval", "?")
        )
        model_name = os.path.basename(model_path)
        self.meta.setdefault("model_name", model_name)

        self.session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"])
        log.info(
            "ML filter siap: %s | TF=%s | %d fitur | threshold %.2f",
            model_path, self.model_interval, len(self.feature_order), self.threshold,
        )

    # ------------------------------------------------------------------
    # Feature engineering -- semua fitur kandidat; vector final
    # dibangun dari feature_order metadata masing-masing model.
    # ------------------------------------------------------------------
    def _compute_all_features(
        self,
        candles: list,
        signal: Signal,
        strategy,
        funding_rate: float | None = None,
    ) -> dict | None:
        """
        Hitung SEMUA fitur kandidat dari bar sinyal.
        _to_vector() kemudian memilih subset sesuai feature_order model.
        """
        if not candles:
            return None
        if len(candles) < 520:
            log.warning(
                "window candle %d < 520 -- fitur regime butuh >= 500 bar history (fail-closed)",
                len(candles),
            )
            return None

        df = strategy._to_df(candles)
        df = strategy._compute_indicators(df)
        df["vol_sma20"]  = df["v"].rolling(20).mean()
        df["vol_sma100"] = df["v"].rolling(100).mean()

        i      = len(candles) - 1
        last   = df.iloc[i]
        candle = candles[i]
        o, h   = float(candle["o"]), float(candle["h"])
        l, c   = float(candle["l"]), float(candle["c"])
        v      = float(candle["v"])
        atr    = float(last["atr"])

        if not atr == atr or atr <= 0 or c <= 0:
            return None

        dt   = pd.Timestamp(int(candle["t"]), unit="ms", tz="UTC")
        v20  = float(df["vol_sma20"].iloc[i])
        v100 = float(df["vol_sma100"].iloc[i])

        # Union semua fitur yang pernah dipakai model manapun
        feats = {
            "dist_to_ema_atr":   (c - float(last["ema"])) / atr,
            "adx_main":          float(last["adx"]),
            "adx_pdi":           float(last["plus_di"]),
            "adx_mdi":           float(last["minus_di"]),
            "adx_di_diff":       float(last["plus_di"]) - float(last["minus_di"]),
            "rsi":               float(last["rsi"]),
            "atr_normalized":    atr / c * 1000.0,
            "body_atr":          abs(c - o) / atr,
            "upper_shadow_atr":  (h - max(o, c)) / atr,
            "lower_shadow_atr":  (min(o, c) - l) / atr,
            "hour":              dt.hour,
            "day_of_week":       dt.dayofweek,
            "signal_type":       1 if signal == Signal.BUY else 2,
            "vol_ratio_20":      v / v20  if v20  > 0 else 1.0,
            "vol_ratio_100":     v / v100 if v100 > 0 else 1.0,
            "funding_rate":      float(funding_rate) if funding_rate is not None else 0.0,
        }

        # Fitur regime (butuh >= 500 bar history)
        rv  = float(df["c"].pct_change().rolling(50).std().iloc[i])
        dhi = float(((df["h"].rolling(500).max() - df["c"]) / df["atr"]).iloc[i])
        dlo = float(((df["c"] - df["l"].rolling(500).min()) / df["atr"]).iloc[i])
        if rv != rv or dhi != dhi or dlo != dlo:
            log.warning("fitur regime NaN (history kurang?) -> fail-closed")
            return None
        feats["rv_50"]           = rv
        feats["dist_hi_500_atr"] = dhi
        feats["dist_lo_500_atr"] = dlo

        return feats

    # Alias publik agar kode lama tetap bekerja
    def compute_features(self, candles: list, signal: Signal,
                         strategy, funding_rate: float | None = None) -> dict | None:
        return self._compute_all_features(candles, signal, strategy, funding_rate)

    def _to_vector(self, feats: dict) -> np.ndarray:
        """
        Bangun feature vector PERSIS sesuai feature_order model yang dimuat.
        Model 1H (18 fitur, tanpa funding_rate) dan 15m/30m (19 fitur,
        dengan funding_rate) keduanya ditangani otomatis dari meta.json.
        """
        missing = [f for f in self.feature_order if f not in feats]
        if missing:
            raise KeyError(
                f"Fitur hilang untuk model TF={self.model_interval}: {missing}. "
                f"Pastikan model dilatih ulang dengan fitur terkini."
            )
        return np.array([[feats[f] for f in self.feature_order]], dtype=np.float32)

    def predict_proba(self, candles: list, signal: Signal, strategy,
                      funding_rate: float | None = None) -> float | None:
        """p(win) dari bar sinyal; None = inferensi gagal (fail-closed)."""
        try:
            feats = self._compute_all_features(candles, signal, strategy, funding_rate)
            if feats is None:
                log.warning("fitur tidak valid (ATR NaN / harga <= 0)")
                return None
            vec = self._to_vector(feats)
            out = self.session.run(None, {self.input_name: vec})
            return float(out[1][0, 1])  # class_order [0,1] -> kolom 1 = p(win)
        except Exception as e:
            log.error("inferensi ML gagal (fail-closed): %s", e)
            return None

    def allow(self, candles: list, signal: Signal, strategy,
              funding_rate: float | None = None) -> bool:
        """True jika sinyal boleh dieksekusi (p1 >= threshold). Fail-closed."""
        if signal not in (Signal.BUY, Signal.SELL):
            return False
        p1 = self.predict_proba(candles, signal, strategy, funding_rate)
        if p1 is None:
            return False
        log.info(
            "ML p(win)=%.3f threshold=%.2f -> %s [model TF=%s]",
            p1, self.threshold, "PASS" if p1 >= self.threshold else "SKIP",
            self.model_interval,
        )
        return p1 >= self.threshold