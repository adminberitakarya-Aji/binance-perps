import time

from src.config import Config
from src.client import BinanceFuturesClient
from src.strategy.trend_reversal import TrendReversalStrategy
from src.risk.manager import RiskManager, RiskLimits
from src.execution.executor import OrderExecutor
from src.engine import TradingEngine
from src.utils.logger import get_logger
from src.utils.notifier import TelegramNotifier

POLL_INTERVAL_SECONDS = 60 * 60   # timeframe strategi produksi (BTC 1H)
CANDLE_CLOSE_BUFFER_SECONDS = 300  # jeda setelah close candle (data siap di API)
KILL_SWITCH_CHECK_SECONDS = 60    # monitoring kill switch antar-poll

log = get_logger("main")


def seconds_until_next_poll(
    interval_seconds: int, buffer_s: int = CANDLE_CLOSE_BUFFER_SECONDS, now: float | None = None
) -> float:
    """Detik sampai poll berikutnya yang SELARAS boundary candle."""
    if now is None:
        now = time.time()
    cur_target = int(now // interval_seconds) * interval_seconds + buffer_s
    target = cur_target if now < cur_target else cur_target + interval_seconds
    return max(target - now, 1.0)


def main():
    config = Config.from_env()
    client = BinanceFuturesClient(config)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    # Inisialisasi cache filter exchange (tickSize, stepSize, minNotional)
    try:
        client.load_exchange_info(config.symbol)
    except Exception as e:
        log.warning("Gagal load exchangeInfo awal: %s (akan retry saat eksekusi)", e)

    # Konfigurasi strategi produksi
    strategy = TrendReversalStrategy(
        require_trend_alignment=False,
    )
    risk_manager = RiskManager(RiskLimits())
    executor = OrderExecutor(client, notifier)

    # Filter ML (opsional, default nonaktif sampai model Binance tervalidasi)
    ml_filter = None
    if config.ml_filter_enabled:
        try:
            from src.ml.inference import MLSignalFilter

            model_path = config.ml_model_path or None
            if model_path:
                ml_filter = MLSignalFilter(model_path, threshold=config.ml_threshold)
            else:
                ml_filter = MLSignalFilter(threshold=config.ml_threshold)
            log.info("Filter ML aktif (threshold %.2f)", config.ml_threshold)
        except Exception as e:
            log.error("Gagal muat filter ML: %s -- bot TIDAK dijalankan (fail-closed)", e)
            raise SystemExit(1)

    engine = TradingEngine(
        client=client,
        strategy=strategy,
        risk_manager=risk_manager,
        executor=executor,
        symbols=[config.symbol],  # default BTCUSDT
        notifier=notifier,
        ml_filter=ml_filter,
    )

    log.info("Agent Binance Futures mulai jalan (%s - %s)",
             "TESTNET" if config.use_testnet else "MAINNET", config.symbol)

    while True:
        try:
            engine.run_once()
        except Exception as e:
            log.error("Error saat run_once: %s", e)
            notifier.notify_error("di run_once", e)

        next_poll = time.time() + seconds_until_next_poll(POLL_INTERVAL_SECONDS)
        while True:
            remaining = next_poll - time.time()
            if remaining <= 0:
                break
            time.sleep(min(KILL_SWITCH_CHECK_SECONDS, remaining))
            try:
                engine.monitor_kill_switch()
            except Exception as e:
                log.error("Error saat monitor kill switch: %s", e)


if __name__ == "__main__":
    main()
