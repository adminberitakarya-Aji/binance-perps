"""
Konfigurasi agent Binance USDⓈ-M Futures. Baca dari environment variables (lihat .env.example).
JANGAN commit API Key & Secret ke git.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

BINANCE_MAINNET_URL = "https://fapi.binance.com"
BINANCE_TESTNET_URL = "https://testnet.binancefuture.com"

# Timeframe yang valid di Binance Futures
VALID_INTERVALS = {"1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1d"}


@dataclass
class Config:
    api_key: str
    api_secret: str
    use_testnet: bool = True
    symbol: str = "BTCUSDT"

    # Timeframe candle untuk strategi
    trading_interval: str = "1h"  # '15m', '30m', '1h', '4h', dst.

    # Alert Telegram (opsional -- kosongkan keduanya = silent mode)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # Filter ML Fase 2 (RandomForest ONNX)
    ml_filter_enabled: bool = False
    ml_threshold: float = 0.60
    ml_model_path: str = ""  # kosong = default models/btcusdt_ml_rf_1h.onnx

    # Mode TP/SL: "atr" (adaptif volatilitas) atau "pct" (% harga fixed)
    tpsl_mode: str = "atr"

    # Risk Management Settings
    risk_per_trade_pct: float = 0.01      # 1% equity per trade
    max_leverage: float = 3.0             # Max notional cap (3x equity)
    max_daily_loss_pct: float = 0.05      # Kill switch harian (-5%)
    atr_sl_mult: float = 2.0              # SL awal = ATR * mult   [dipakai jika tpsl_mode=atr]
    tp_rr_ratio: float = 1.5              # TP awal = jarak SL * rasio [dipakai jika tpsl_mode=atr]
    sl_pct: float = 0.5                   # SL = sl_pct% dari harga entry  [dipakai jika tpsl_mode=pct]
    tp_pct: float = 1.0                   # TP = tp_pct% dari harga entry  [dipakai jika tpsl_mode=pct]

    # Trailing Stop Settings
    trailing_enabled: bool = True
    trailing_start_atr_mult: float = 1.2  # Mulai trailing setelah profit >= ATR * mult dari avg entry
    trailing_distance_atr_mult: float = 1.0 # Jarak SL baru di belakang harga berjalan
    trailing_step_atr_mult: float = 0.3   # Minimal pergeseran harga untuk update SL

    # Smart DCA / Grid Settings
    dca_enabled: bool = False             # true = aktifkan averaging down, false = single entry
    dca_max_orders: int = 3               # Maksimal jumlah lapis (termasuk entry awal)
    dca_step_atr_mult: float = 1.5        # Jarak buka lapis berikutnya (tiap minus 1.5x ATR) [mode atr]
    dca_step_pct: float = 0.5            # Jarak buka lapis berikutnya (% harga lapis sebelumnya) [mode pct]
    dca_lot_multiplier: float = 1.0       # Pengali lot lapis berikutnya (1.0 = equal size)
    dca_tp_rr_ratio: float = 1.0          # TP gabungan = average_entry +/- (ATR * rasio) [mode atr]
    dca_hard_sl_equity_pct: float = 0.03  # Cut-loss total jika floating loss >= 3% modal

    @property
    def api_url(self) -> str:
        return BINANCE_TESTNET_URL if self.use_testnet else BINANCE_MAINNET_URL

    @classmethod
    def from_env(cls) -> "Config":
        # Muat .env dari project root
        load_dotenv()

        api_key = os.environ.get("BINANCE_API_KEY", "").strip()
        api_secret = os.environ.get("BINANCE_API_SECRET", "").strip()
        use_testnet = os.environ.get("BINANCE_USE_TESTNET", "true").lower() == "true"
        symbol = os.environ.get("BINANCE_SYMBOL", "BTCUSDT").strip().upper()

        if not api_key or not api_secret:
            raise ValueError(
                "BINANCE_API_KEY dan BINANCE_API_SECRET wajib di-set. "
                "Copy .env.example ke .env dan isi nilainya."
            )

        # Timeframe
        trading_interval = os.environ.get("TRADING_INTERVAL", "1h").strip().lower()
        if trading_interval not in VALID_INTERVALS:
            raise ValueError(
                f"TRADING_INTERVAL='{trading_interval}' tidak valid. "
                f"Pilihan: {sorted(VALID_INTERVALS)}"
            )

        # ML
        ml_enabled = os.environ.get("ML_FILTER_ENABLED", "false").lower() == "true"
        ml_threshold = float(os.environ.get("ML_THRESHOLD", "0.60"))
        ml_model_path = (os.environ.get("ML_MODEL_PATH") or "").strip()

        # Mode TP/SL
        tpsl_mode = os.environ.get("TPSL_MODE", "atr").strip().lower()
        if tpsl_mode not in ("atr", "pct"):
            raise ValueError(f"TPSL_MODE harus 'atr' atau 'pct', bukan '{tpsl_mode}'")

        # Risk
        risk_per_trade_pct = float(os.environ.get("RISK_PER_TRADE_PCT", "0.01"))
        max_leverage = float(os.environ.get("MAX_LEVERAGE", "3.0"))
        max_daily_loss_pct = float(os.environ.get("MAX_DAILY_LOSS_PCT", "0.05"))
        atr_sl_mult = float(os.environ.get("ATR_SL_MULT", "2.0"))
        tp_rr_ratio = float(os.environ.get("TP_RR_RATIO", "1.5"))
        sl_pct = float(os.environ.get("SL_PCT", "0.5"))
        tp_pct = float(os.environ.get("TP_PCT", "1.0"))

        # Trailing
        trailing_enabled = os.environ.get("TRAILING_ENABLED", "true").lower() == "true"
        trailing_start_atr_mult = float(os.environ.get("TRAILING_START_ATR_MULT", "1.2"))
        trailing_distance_atr_mult = float(os.environ.get("TRAILING_DISTANCE_ATR_MULT", "1.0"))
        trailing_step_atr_mult = float(os.environ.get("TRAILING_STEP_ATR_MULT", "0.3"))

        # DCA
        dca_enabled = os.environ.get("DCA_ENABLED", "false").lower() == "true"
        dca_max_orders = int(os.environ.get("DCA_MAX_ORDERS", "3"))
        dca_step_atr_mult = float(os.environ.get("DCA_STEP_ATR_MULT", "1.5"))
        dca_step_pct = float(os.environ.get("DCA_STEP_PCT", "0.5"))
        dca_lot_multiplier = float(os.environ.get("DCA_LOT_MULTIPLIER", "1.0"))
        dca_tp_rr_ratio = float(os.environ.get("DCA_TP_RR_RATIO", "1.0"))
        dca_hard_sl_equity_pct = float(os.environ.get("DCA_HARD_SL_EQUITY_PCT", "0.03"))

        return cls(
            api_key=api_key,
            api_secret=api_secret,
            use_testnet=use_testnet,
            symbol=symbol,
            trading_interval=trading_interval,
            telegram_bot_token=(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip(),
            telegram_chat_id=(os.environ.get("TELEGRAM_CHAT_ID") or "").strip(),
            ml_filter_enabled=ml_enabled,
            ml_threshold=ml_threshold,
            ml_model_path=ml_model_path,
            tpsl_mode=tpsl_mode,
            risk_per_trade_pct=risk_per_trade_pct,
            max_leverage=max_leverage,
            max_daily_loss_pct=max_daily_loss_pct,
            atr_sl_mult=atr_sl_mult,
            tp_rr_ratio=tp_rr_ratio,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
            trailing_enabled=trailing_enabled,
            trailing_start_atr_mult=trailing_start_atr_mult,
            trailing_distance_atr_mult=trailing_distance_atr_mult,
            trailing_step_atr_mult=trailing_step_atr_mult,
            dca_enabled=dca_enabled,
            dca_max_orders=dca_max_orders,
            dca_step_atr_mult=dca_step_atr_mult,
            dca_step_pct=dca_step_pct,
            dca_lot_multiplier=dca_lot_multiplier,
            dca_tp_rr_ratio=dca_tp_rr_ratio,
            dca_hard_sl_equity_pct=dca_hard_sl_equity_pct,
        )
