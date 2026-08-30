from src.client import BinanceFuturesClient, ProtectionError
from src.strategy.base import Signal
from src.utils.logger import get_logger
from src.utils.notifier import TelegramNotifier

log = get_logger("exec")


class OrderExecutor:
    """Kirim order final ke Binance USDⓈ-M Futures dari jalur live."""

    # Binance USDⓈ-M Futures minimum notional $5.0
    MIN_NOTIONAL_USD = 5.0

    def __init__(self, client: BinanceFuturesClient, notifier: TelegramNotifier | None = None):
        self.client = client
        # notifier default = no-op (mode silent)
        self.notifier = notifier or TelegramNotifier()

    def execute(
        self,
        symbol: str,
        signal: Signal,
        size_usd: float,
        price: float,
        sl: float | None = None,
        tp: float | None = None,
    ):
        if size_usd < self.MIN_NOTIONAL_USD:
            log.warning("[%s] skip: notional $%.2f < minimum $%.0f", symbol, size_usd, self.MIN_NOTIONAL_USD)
            return None

        size_in_asset = self.client.round_size(symbol, size_usd / price)
        if size_in_asset <= 0:
            log.warning("[%s] skip: size %s (asset) terlalu kecil", symbol, size_in_asset)
            return None

        is_buy = signal == Signal.BUY
        proteksi = f" SL={sl} TP={tp}" if (sl is not None or tp is not None) else ""
        log.info("%s %s size=%s (~$%.2f)%s", signal.value, symbol, size_in_asset, size_usd, proteksi)

        try:
            result = self.client.place_market_order(symbol, is_buy, size_in_asset, sl=sl, tp=tp)
            log.info("[%s] Order result: %s", symbol, result)
            return result
        except ProtectionError as e:
            # proteksi gagal & posisi SUDAH ditutup paksa oleh client -> alert
            log.error("[%s] PROTEKSI GAGAL: %s (posisi sudah ditutup paksa)", symbol, e)
            self.notifier.notify_force_close(
                symbol,
                f"{signal.value} {size_in_asset} {symbol} (~${size_usd:.2f})",
                detail=str(e),
            )
            return None
        except Exception as e:
            log.error("[%s] Gagal eksekusi order: %s", symbol, e)
            return None
