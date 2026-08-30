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
        """Eksekusi order awal (Lapis 1) beserta bracket SL/TP."""
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

    def execute_dca_layer(
        self,
        symbol: str,
        signal: Signal,
        layer_size_usd: float,
        price: float,
        new_total_size: float,
        new_sl: float | None,
        new_tp: float | None,
        layer_index: int,
    ):
        """
        Eksekusi penambahan lapis DCA (Lapis 2, 3, dst):
        1. Kirim market order untuk menambah size
        2. Batalkan trigger order SL/TP lama
        3. Pasang bracket SL/TP baru untuk total size gabungan
        """
        if layer_size_usd < self.MIN_NOTIONAL_USD:
            log.warning("[%s] skip DCA: notional $%.2f < minimum $%.0f", symbol, layer_size_usd, self.MIN_NOTIONAL_USD)
            return None

        layer_size_asset = self.client.round_size(symbol, layer_size_usd / price)
        if layer_size_asset <= 0:
            log.warning("[%s] skip DCA: size asset terlalu kecil", symbol)
            return None

        is_buy = signal == Signal.BUY
        log.info("[%s] EKSEKUSI DCA LAPIS %d: %s %s size=%s (~$%.2f) @ %s",
                 symbol, layer_index + 1, signal.value, symbol, layer_size_asset, layer_size_usd, price)

        try:
            # 1. Market order penambahan size
            fill = self.client.place_market_order_raw(symbol, is_buy, layer_size_asset)
            log.info("[%s] DCA lapis %d terisi: %s", symbol, layer_index + 1, fill)

            # 2. Cancel trigger order lama
            self.client.cancel_all_trigger_orders(symbol)

            # 3. Pasang trigger order baru untuk total size gabungan
            close_is_buy = not is_buy
            tot_size_rounded = self.client.round_size(symbol, new_total_size)
            self.client.place_tpsl_pair(symbol, close_is_buy, tot_size_rounded, new_sl, new_tp)
            log.info("[%s] Bracket SL/TP baru dipasang untuk total size=%s: SL=%s TP=%s",
                     symbol, tot_size_rounded, new_sl, new_tp)

            return fill
        except Exception as e:
            log.error("[%s] Gagal eksekusi lapis DCA %d: %s", symbol, layer_index + 1, e)
            return None
