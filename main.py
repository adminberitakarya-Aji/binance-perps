import argparse
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


def build_engine(config: Config) -> tuple[TradingEngine, TelegramNotifier, object]:
    """Bangun semua komponen engine dan kembalikan (engine, notifier, ml_filter)."""
    client   = BinanceFuturesClient(config)
    notifier = TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id)

    # Inisialisasi cache filter exchange (tickSize, stepSize, minNotional)
    try:
        client.load_exchange_info(config.symbol)
    except Exception as e:
        log.warning("Gagal load exchangeInfo awal: %s (akan retry saat eksekusi)", e)

    # Konfigurasi strategi produksi
    strategy     = TrendReversalStrategy(require_trend_alignment=False)
    limits       = RiskLimits(
        max_leverage=config.max_leverage,
        max_daily_loss_pct=config.max_daily_loss_pct,
        atr_sl_mult=config.atr_sl_mult,
        tp_rr_ratio=config.tp_rr_ratio,
        risk_per_trade_pct=config.risk_per_trade_pct,
        use_trailing=config.trailing_enabled,
        trailing_start_atr_mult=config.trailing_start_atr_mult,
        trailing_distance_atr_mult=config.trailing_distance_atr_mult,
        trailing_step_atr_mult=config.trailing_step_atr_mult,
        dca_enabled=config.dca_enabled,
        dca_max_orders=config.dca_max_orders,
        dca_step_atr_mult=config.dca_step_atr_mult,
        dca_lot_multiplier=config.dca_lot_multiplier,
        dca_tp_rr_ratio=config.dca_tp_rr_ratio,
        dca_hard_sl_equity_pct=config.dca_hard_sl_equity_pct,
    )
    risk_manager = RiskManager(limits)
    executor     = OrderExecutor(client, notifier)

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
        symbols=[config.symbol],
        notifier=notifier,
        ml_filter=ml_filter,
    )
    return engine, notifier, ml_filter


def run_plain(engine: TradingEngine, notifier: TelegramNotifier):
    """Loop utama tanpa dashboard (mode log biasa)."""
    log.info("Agent Binance Futures mulai jalan (%s)",
             "TESTNET" if engine.client.config.use_testnet else "MAINNET")

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


def run_dashboard(engine: TradingEngine, notifier: TelegramNotifier, ml_filter):
    """Loop utama dengan dashboard terminal visual (mode Rich)."""
    from src.ui.dashboard import (
        DashboardRunner,
        install_log_capture,
        patch_ml_filter,
    )

    log_capture = install_log_capture()
    patch_ml_filter(ml_filter, None)  # state akan di-attach oleh runner

    runner = DashboardRunner(engine, log_capture)

    # Patch ML filter agar prob-nya masuk ke dashboard state
    if ml_filter is not None:
        patch_ml_filter(ml_filter, runner.state)

    runner.start()
    log.info("Dashboard Terminal Visual aktif — tekan Ctrl+C untuk keluar")

    runner.run_live(
        poll_fn=engine.run_once,
        kill_switch_fn=engine.monitor_kill_switch,
        poll_interval_s=POLL_INTERVAL_SECONDS,
        kill_switch_interval_s=KILL_SWITCH_CHECK_SECONDS,
    )


def main():
    parser = argparse.ArgumentParser(description="Binance Perps Trading Bot")
    parser.add_argument(
        "--dashboard", "--ui",
        action="store_true",
        default=False,
        help="Tampilkan dashboard terminal visual real-time (default: mode log biasa)",
    )
    args = parser.parse_args()

    config = Config.from_env()
    engine, notifier, ml_filter = build_engine(config)

    log.info("Agent Binance Futures mulai jalan (%s - %s)",
             "TESTNET" if config.use_testnet else "MAINNET", config.symbol)

    if args.dashboard:
        run_dashboard(engine, notifier, ml_filter)
    else:
        run_plain(engine, notifier)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Bot dihentikan oleh user (Ctrl+C). Keluar dengan aman.")

