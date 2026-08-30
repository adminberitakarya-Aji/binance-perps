import json
import os
from datetime import datetime, timezone

from src.client import BinanceFuturesClient
from src.data.market_data import fetch_snapshot
from src.strategy.base import MarketSnapshot, Signal, Strategy
from src.risk.manager import RiskManager
from src.execution.executor import OrderExecutor
from src.utils.logger import get_logger
from src.utils.notifier import TelegramNotifier

log = get_logger("engine")


class TradingEngine:
    def __init__(
        self,
        client: BinanceFuturesClient,
        strategy: Strategy,
        risk_manager: RiskManager,
        executor: OrderExecutor,
        symbols: list,
        interval: str = "1h",
        notifier: TelegramNotifier | None = None,
        ml_filter=None,  # MLSignalFilter | None
    ):
        self.client = client
        self.strategy = strategy
        self.risk_manager = risk_manager
        self.executor = executor
        self.symbols = symbols
        self.interval = interval
        self.ml_filter = ml_filter
        self.notifier = notifier or TelegramNotifier()
        self.state_path = os.path.join("data", "live_positions.json")
        self.live_positions: dict = {}
        self.daily_state_path = os.path.join("data", "daily_state.json")
        self.daily_state: dict = {}
        self._load_state()
        self._load_daily_state()

    # ------------------------------------------------------------------
    # Persistensi state posisi live (trailing & DCA tetap aman setelah restart)
    # ------------------------------------------------------------------
    def _load_state(self):
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path) as f:
                    self.live_positions = json.load(f)
                if self.live_positions:
                    log.info("state posisi live dimuat: %s", list(self.live_positions.keys()))
        except Exception as e:
            log.error("gagal memuat state: %s", e)
            self.live_positions = {}

    def _save_state(self):
        try:
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self.state_path, "w") as f:
                json.dump(self.live_positions, f, indent=1)
        except Exception as e:
            log.error("gagal menyimpan state: %s", e)

    # ------------------------------------------------------------------
    # Tracker PnL harian (kill switch risk manager) -- persist + reset UTC
    # ------------------------------------------------------------------
    def _load_daily_state(self):
        try:
            if os.path.exists(self.daily_state_path):
                with open(self.daily_state_path) as f:
                    self.daily_state = json.load(f)
        except Exception as e:
            log.error("gagal memuat daily state: %s", e)
            self.daily_state = {}

    def _save_daily_state(self):
        try:
            os.makedirs(os.path.dirname(self.daily_state_path), exist_ok=True)
            with open(self.daily_state_path, "w") as f:
                json.dump(self.daily_state, f, indent=1)
        except Exception as e:
            log.error("gagal menyimpan daily state: %s", e)

    def _get_equity_or_none(self) -> float | None:
        """Equity asli dari totalMarginBalance Binance; None kalau kosong/gagal."""
        try:
            state = self.client.get_account_state()
            account_value = float(
                state.get("totalMarginBalance", 0)
                or state.get("totalWalletBalance", 0)
                or 0
            )
            if account_value <= 0:
                return None
            return account_value
        except Exception as e:
            log.warning("gagal ambil account state: %s", e)
            return None

    def _update_daily_pnl(self):
        """Hitung PnL harian (basis hari UTC) -> suntikkan ke risk_manager."""
        equity = self._get_equity_or_none()
        if equity is None:
            log.info("equity tidak tersedia -> tracker PnL harian tidak di-update")
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if self.daily_state.get("date_utc") != today:
            yesterday_pnl_pct = None
            old_baseline = float(self.daily_state.get("day_start_equity") or 0)
            if old_baseline > 0:
                yesterday_pnl_pct = (equity - old_baseline) / old_baseline

            self.daily_state = {
                "date_utc": today,
                "day_start_equity": equity,
                "kill_triggered": False,
            }
            self._save_daily_state()
            log.info("tracker harian reset: date=%s baseline_equity=%.2f", today, equity)

            try:
                positions = []
                for sym, st in self.live_positions.items():
                    pos = self.client.get_position(sym)
                    size = abs(pos["szi"]) if pos else None
                    positions.append((sym, st.get("side"), size, st.get("avg_price", st.get("entry_price")), st.get("sl"), st.get("tp")))
                self.notifier.notify_heartbeat(
                    today,
                    equity,
                    yesterday_pnl_pct,
                    positions,
                    bool(self.daily_state.get("kill_triggered")),
                    self.client.config.use_testnet,
                )
            except Exception as e:
                log.warning("gagal kirim heartbeat: %s", e)

        day_start = float(self.daily_state.get("day_start_equity") or 0)
        if day_start <= 0:
            self.daily_state["day_start_equity"] = equity
            self._save_daily_state()
            day_start = equity

        daily_pnl_pct = (equity - day_start) / day_start
        self.risk_manager.daily_pnl_pct = daily_pnl_pct
        log.info("equity=%.2f baseline=%.2f daily_pnl=%.2f%%", equity, day_start, daily_pnl_pct * 100)

        if (
            daily_pnl_pct <= -self.risk_manager.limits.max_daily_loss_pct
            and not self.daily_state.get("kill_triggered")
        ):
            self.daily_state["kill_triggered"] = True
            self._save_daily_state()
            log.warning(
                "KILL SWITCH TERPICU: daily_pnl=%.2f%% <= -%.1f%% (entry baru diblokir sampai ganti hari UTC)",
                daily_pnl_pct * 100,
                self.risk_manager.limits.max_daily_loss_pct * 100,
            )
            self.notifier.notify_kill_switch(
                daily_pnl_pct,
                self.risk_manager.limits.max_daily_loss_pct,
                equity,
                day_start,
            )

    def run_once(self):
        self._update_daily_pnl()

        for symbol in self.symbols:
            # --- A. Kelola posisi terbuka (Hard SL, DCA averaging, trailing stop) ---
            self._manage_open_positions(symbol)

            pos = self.client.get_position(symbol)
            if pos is not None:
                log.info("[%s] skip entry baru: masih ada posisi terbuka (%s, szi=%s)", symbol, pos["side"], pos["szi"])
                continue

            need = self.strategy.required_bars()
            lookback = max(need + 10, 560)
            snapshot = fetch_snapshot(self.client, symbol, interval=self.interval, lookback_candles=lookback)

            result = self.strategy.generate_signal(snapshot)
            log.info("[%s] sinyal=%s conf=%s alasan=%s", symbol, result.signal.value, result.confidence, result.reason)

            if result.signal == Signal.HOLD:
                continue

            # --- Filter ML (fail-closed): p(win) >= threshold, else skip ---
            if self.ml_filter is not None:
                funding_rate = self.client.get_funding_rate(symbol)
                window = snapshot.candles if hasattr(snapshot, "candles") else []
                if not self.ml_filter.allow(window, result.signal, self.strategy, funding_rate):
                    log.info("[%s] sinyal %s DITOLAK filter ML (fail-closed)", symbol, result.signal.value)
                    continue

            atr = self._get_last_atr(snapshot)
            sl_distance_pct = None
            if atr is not None and atr > 0 and snapshot.mid_price > 0:
                sl_distance_pct = (atr * self.risk_manager.limits.atr_sl_mult) / snapshot.mid_price

            equity_usd = self._get_equity_or_none()
            if equity_usd is None:
                log.error("[%s] equity tidak tersedia -> skip entry (fail-closed)", symbol)
                continue

            size_usd = self.risk_manager.check_and_size(
                equity_usd, result.signal, result.confidence, sl_distance_pct=sl_distance_pct
            )

            if size_usd > 0:
                if atr is None or atr <= 0:
                    log.warning("[%s] ATR tidak tersedia -> skip entry (butuh SL/TP valid)", symbol)
                    continue
                sl, tp = self.risk_manager.compute_sl_tp(result.signal, snapshot.mid_price, atr)
                exec_result = self.executor.execute(
                    symbol, result.signal, size_usd, snapshot.mid_price, sl=sl, tp=tp
                )
                if exec_result is not None:
                    size_asset = self.client.round_size(symbol, size_usd / snapshot.mid_price)
                    self.live_positions[symbol] = {
                        "side": "B" if result.signal == Signal.BUY else "S",
                        "entry_price": snapshot.mid_price,
                        "avg_price": snapshot.mid_price,
                        "total_size": size_asset,
                        "entry_atr": atr,
                        "sl": sl,
                        "tp": tp,
                        "layers": [
                            {"price": snapshot.mid_price, "size": size_asset, "atr": atr}
                        ],
                    }
                    self._save_state()
                    log.info(
                        "posisi %s dicatat: side=%s SL=%s TP=%s (Lapis 1/ %d)",
                        symbol, self.live_positions[symbol]["side"], sl, tp,
                        self.risk_manager.limits.dca_max_orders,
                    )
                    self.notifier.notify_entry(
                        symbol=symbol,
                        signal=result.signal.value,
                        size=size_asset,
                        size_usd=size_usd,
                        price=snapshot.mid_price,
                        sl=sl,
                        tp=tp,
                        confidence=result.confidence,
                        equity=equity_usd,
                        reason=result.reason,
                    )

    # ------------------------------------------------------------------
    # Manajemen posisi terbuka: Hard SL, Smart DCA, trailing SL
    # ------------------------------------------------------------------
    def _manage_open_positions(self, symbol: str):
        state = self.live_positions.get(symbol)
        pos = self.client.get_position(symbol)

        # 1. Posisi sudah tertutup -> bersihkan
        if pos is None:
            if state is not None:
                log.info("[%s] posisi sudah tertutup -> hapus state & cancel trigger sisa", symbol)
                self.notifier.notify_closed(
                    symbol,
                    state.get("side", "?"),
                    self._get_equity_or_none(),
                    self.risk_manager.daily_pnl_pct,
                    bool(self.daily_state.get("kill_triggered")),
                )
                self.live_positions.pop(symbol, None)
                self._save_state()
            try:
                self.client.cancel_all_trigger_orders(symbol)
            except Exception as e:
                log.warning("[%s] cleanup trigger gagal: %s", symbol, e)
            return

        # 2. Posisi ada tapi state hilang: rekonstruksi state minimal
        if state is None:
            log.warning("[%s] posisi terbuka tanpa state -> rekonstruksi state minimal", symbol)
            self.live_positions[symbol] = {
                "side": pos["side"],
                "entry_price": pos["entryPx"],
                "avg_price": pos["entryPx"],
                "total_size": abs(pos["szi"]),
                "entry_atr": None,
                "sl": None,
                "tp": None,
                "layers": [{"price": pos["entryPx"], "size": abs(pos["szi"])}],
            }
            self._save_state()
            return

        equity = self._get_equity_or_none()
        mid_px = self.client.get_mid_price(symbol)

        # 3. --- HARD SL CUT-LOSS DARURAT ---
        # Jika total kerugian keranjang >= batas darurat (misal 3% modal) -> TUTUP PAKSA
        unrealized_pnl = float(pos.get("unrealizedPnl") or 0)
        if equity and unrealized_pnl < 0:
            floating_loss_usd = abs(unrealized_pnl)
            if self.risk_manager.is_hard_sl_triggered(floating_loss_usd, equity):
                log.critical(
                    "[%s] HARD SL DARURAT TERPICU: loss -$%.2f >= %.1f%% modal -> TUTUP PAKSA SEMUA LAPIS",
                    symbol, floating_loss_usd, self.risk_manager.limits.dca_hard_sl_equity_pct * 100
                )
                try:
                    self.client.cancel_all_trigger_orders(symbol)
                    self.client.market_close_position(symbol)
                except Exception as e:
                    log.critical("[%s] gagal market close hard SL: %s", symbol, e)
                self.notifier.notify_force_close(
                    symbol,
                    f"Hard SL Cut-Loss -${floating_loss_usd:.2f}",
                    detail="Floating loss melampaui batas darurat modal",
                )
                self.live_positions.pop(symbol, None)
                self._save_state()
                return

        # 4. --- SMART DCA / AVERAGING DOWN ---
        if self.risk_manager.limits.dca_enabled and state.get("entry_atr"):
            layers = state.get("layers", [])
            if not layers:
                layers = [{"price": state["entry_price"], "size": abs(pos["szi"]), "atr": state["entry_atr"]}]
                state["layers"] = layers
                state["avg_price"] = state["entry_price"]
                state["total_size"] = abs(pos["szi"])
                self._save_state()

            if len(layers) < self.risk_manager.limits.dca_max_orders:
                last_layer_price = layers[-1]["price"]
                signal = Signal.BUY if state["side"] == "B" else Signal.SELL
                entry_atr = state["entry_atr"]

                if self.risk_manager.should_trigger_dca(signal, last_layer_price, mid_px, entry_atr, len(layers)):
                    base_size_usd = layers[0]["size"] * layers[0]["price"]
                    layer_idx = len(layers)
                    layer_size_usd = self.risk_manager.compute_dca_layer_size(equity or 5000.0, base_size_usd, layer_idx)
                    layer_size_asset = self.client.round_size(symbol, layer_size_usd / mid_px)

                    if layer_size_asset > 0:
                        sim_layers = layers + [{"price": mid_px, "size": layer_size_asset, "atr": entry_atr}]
                        new_avg_px, new_tot_sz, new_tp = self.risk_manager.compute_dca_avg_and_tp(signal, sim_layers, entry_atr)
                        new_sl = state.get("sl")

                        fill = self.executor.execute_dca_layer(
                            symbol, signal, layer_size_usd, mid_px, new_tot_sz, new_sl, new_tp, layer_idx
                        )
                        if fill is not None:
                            state["layers"] = sim_layers
                            state["avg_price"] = new_avg_px
                            state["total_size"] = new_tot_sz
                            state["tp"] = new_tp
                            self._save_state()
                            log.info(
                                "[%s] DCA Lapis %d BERHASIL: Size +%s (Total=%s), Avg Px=%s, New TP=%s",
                                symbol, len(sim_layers), layer_size_asset, new_tot_sz, new_avg_px, new_tp
                            )
                            self.notifier.notify_entry(
                                symbol=symbol,
                                signal=f"DCA Lapis {len(sim_layers)}/{self.risk_manager.limits.dca_max_orders}",
                                size=layer_size_asset,
                                size_usd=layer_size_usd,
                                price=mid_px,
                                sl=new_sl,
                                tp=new_tp,
                                confidence=0.9,
                                equity=equity or 0,
                                reason=f"Averaging down: Avg Px -> ${new_avg_px:,.2f}",
                            )
                            return

        # 5. --- SL guard (self-healing): posisi TIDAK boleh telanjang ---
        trigger_active = self.client.get_trigger_orders(symbol)
        sl_active = next((o for o in trigger_active if str(o.get("triggerCondition", "")).startswith("sl")), None)
        if state.get("sl") is not None and sl_active is None:
            log.error("[%s] SL trigger hilang di exchange -> pasang ulang dari state (SL=%s)", symbol, state["sl"])
            try:
                close_is_buy = state["side"] == "S"
                self.client.place_tpsl_pair(symbol, close_is_buy, abs(pos["szi"]), state["sl"], state.get("tp"))
                log.info("[%s] SL dipasang ulang: SL=%s TP=%s", symbol, state["sl"], state.get("tp"))
                return
            except Exception as e:
                log.critical("[%s] gagal pasang ulang SL (%s) -> TUTUP PAKSA posisi", symbol, e)
                try:
                    self.client.cancel_all_trigger_orders(symbol)
                    self.client.market_close_position(symbol)
                except Exception as e2:
                    log.critical("[%s] tutup paksa gagal (%s) -- PERIKSA MANUAL!", symbol, e2)
                return

        # 6. --- TRAILING STOP BERBASIS AVERAGE ENTRY PRICE ---
        if self.risk_manager.limits.use_trailing and state.get("entry_atr") and state.get("sl") is not None:
            signal = Signal.BUY if state["side"] == "B" else Signal.SELL
            avg_price = state.get("avg_price", state["entry_price"])
            entry_atr = state["entry_atr"]

            new_sl = self.risk_manager.compute_trailing_sl(
                signal, avg_price, mid_px, state["sl"], entry_atr
            )
            if new_sl is None or abs(new_sl - state["sl"]) < 1e-9:
                return

            old_sl = state["sl"]
            close_is_buy = state["side"] == "S"
            try:
                if sl_active is not None:
                    self.client.modify_sl_trigger(
                        symbol, sl_active["oid"], close_is_buy, abs(pos["szi"]), new_sl
                    )
                else:
                    self.client.place_tpsl_pair(symbol, close_is_buy, abs(pos["szi"]), new_sl, state.get("tp"))
                log.info("[%s] TRAILING: SL %s -> %s (mid=%s, avg_entry=%s)", symbol, old_sl, new_sl, mid_px, avg_price)
                state["sl"] = new_sl
                self._save_state()
                self.notifier.notify_trailing(symbol, old_sl, new_sl, mid_px)
            except Exception as e:
                log.error("[%s] gagal modify SL: %s", symbol, e)

    def monitor_kill_switch(self):
        """Cek PnL harian/kill switch di luar siklus poll utama."""
        self._update_daily_pnl()

    def _get_last_atr(self, snapshot: MarketSnapshot) -> float | None:
        """ATR terakhir dari candle closed."""
        try:
            strategy = self.strategy
            if hasattr(strategy, "_to_df") and hasattr(strategy, "_compute_indicators"):
                df = strategy._to_df(snapshot.candles)
                df = strategy._compute_indicators(df)
                last_atr = df["atr"].iloc[-1]
                if last_atr == last_atr:
                    return float(last_atr)
        except Exception as e:
            log.warning("gagal hitung ATR: %s", e)
        return None
