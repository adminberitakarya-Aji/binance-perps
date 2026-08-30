"""
Konfigurasi agent Binance USDⓈ-M Futures. Baca dari environment variables (lihat .env.example).
JANGAN commit API Key & Secret ke git.
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

BINANCE_MAINNET_URL = "https://fapi.binance.com"
BINANCE_TESTNET_URL = "https://testnet.binancefuture.com"


@dataclass
class Config:
    api_key: str
    api_secret: str
    use_testnet: bool = True
    symbol: str = "BTCUSDT"
    # Alert Telegram (opsional -- kosongkan keduanya = silent mode)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    # Filter ML Fase 2. DEFAULT FALSE
    ml_filter_enabled: bool = False
    ml_threshold: float = 0.60
    ml_model_path: str = ""  # kosong = default models/btcusdt_ml_rf_1h.onnx

    @property
    def api_url(self) -> str:
        return BINANCE_TESTNET_URL if self.use_testnet else BINANCE_MAINNET_URL

    @classmethod
    def from_env(cls) -> "Config":
        # Muat .env dari project root (dicari ke atas dari lokasi file ini).
        # Variabel yang sudah di-set di shell tetap menang (tidak di-override).
        load_dotenv()

        api_key = os.environ.get("BINANCE_API_KEY", "").strip()
        api_secret = os.environ.get("BINANCE_API_SECRET", "").strip()
        use_testnet = os.environ.get("BINANCE_USE_TESTNET", "true").lower() == "true"
        symbol = os.environ.get("BINANCE_SYMBOL", "BTCUSDT").strip().upper()
        ml_enabled = os.environ.get("ML_FILTER_ENABLED", "false").lower() == "true"
        ml_threshold = float(os.environ.get("ML_THRESHOLD", "0.60"))
        ml_model_path = (os.environ.get("ML_MODEL_PATH") or "").strip()

        if not api_key or not api_secret:
            raise ValueError(
                "BINANCE_API_KEY dan BINANCE_API_SECRET wajib di-set. "
                "Copy .env.example ke .env dan isi nilainya."
            )

        return cls(
            api_key=api_key,
            api_secret=api_secret,
            use_testnet=use_testnet,
            symbol=symbol,
            telegram_bot_token=(os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip(),
            telegram_chat_id=(os.environ.get("TELEGRAM_CHAT_ID") or "").strip(),
            ml_filter_enabled=ml_enabled,
            ml_threshold=ml_threshold,
            ml_model_path=ml_model_path,
        )
