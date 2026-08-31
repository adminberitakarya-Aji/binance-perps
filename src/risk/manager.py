"""
Risk manager punya kata akhir atas setiap sinyal dan manajemen posisi multi-lapis (DCA).
Semua limit dan parameter dapat dikonfigurasi melalui .env / Config.
"""

from dataclasses import dataclass

from src.strategy.base import Signal
from src.utils.logger import get_logger

log = get_logger("risk")


@dataclass
class RiskLimits:
    max_position_pct: float = 0.1      # fallback sizing lama
    max_leverage: float = 3.0          # batas maksimum notional cap (3x equity)
    max_daily_loss_pct: float = 0.05   # kill switch harian otomatis (-5%)
    min_confidence: float = 0.5        # abaikan sinyal di bawah ini

    # --- Mode TP/SL: "atr" (adaptif volatilitas), "pct" (% harga tetap), atau "point" (jarak fixed $) ---
    tpsl_mode: str = "atr"
    atr_sl_mult: float = 2.0           # SL = ATR * mult          [mode: atr]
    tp_rr_ratio: float = 1.5           # TP = jarak SL * rasio    [mode: atr]
    sl_pct: float = 0.5                # SL = sl_pct% dari entry  [mode: pct]
    tp_pct: float = 1.0                # TP = tp_pct% dari entry  [mode: pct]
    sl_points: float = 300.0           # SL = sl_points ($) dari entry [mode: point]
    tp_points: float = 450.0           # TP = tp_points ($) dari entry [mode: point]

    # --- Position sizing berbasis risiko (risk percent per trade) ---
    risk_per_trade_pct: float = 0.01   # 1% equity risiko per trade

    # --- Trailing stop (berbasis Average Entry Price) ---
    use_trailing: bool = True
    trailing_start_atr_mult: float = 1.2    # Mulai trailing setelah profit >= ATR * mult dari avg entry [mode: atr]
    trailing_distance_atr_mult: float = 1.0  # Jarak SL baru di belakang harga berjalan [mode: atr]
    trailing_step_atr_mult: float = 0.3     # SL cuma digeser kalau pergerakan >= step ini (anti-churn) [mode: atr]
    trailing_start_points: float = 200.0    # Mulai trailing setelah profit >= poin ($) dari avg entry [mode: point]
    trailing_lock_points: float = 100.0     # SL awal yang dikunci (+poin $ dari avg entry) [mode: point]
    trailing_step_points: float = 100.0     # Jarak milestone kenaikan berikutnya (+poin $) [mode: point]
    trailing_move_points: float = 50.0      # Nilai pergeseran SL setiap milestone (+poin $) [mode: point]

    # --- Smart DCA / Grid Settings ---
    dca_enabled: bool = False               # true = izinkan penambahan lapis saat floating minus
    dca_max_orders: int = 3                 # Maksimal jumlah lapis (termasuk entry awal)
    dca_step_atr_mult: float = 1.5          # Jarak buka lapis berikutnya (ATR mult)  [mode: atr]
    dca_step_pct: float = 0.5              # Jarak buka lapis berikutnya (% harga)    [mode: pct]
    dca_step_points: float = 200.0          # Jarak buka lapis berikutnya ($ poin)    [mode: point]
    dca_lot_multiplier: float = 1.0         # Pengali lot lapis berikutnya (1.0 = equal sizing)
    dca_tp_rr_ratio: float = 1.0            # TP gabungan = avg_price +/- (ATR * rasio) [mode: atr]
    dca_tp_points: float = 200.0           # TP gabungan = avg_price +/- poin dollar [mode: point]
    dca_hard_sl_equity_pct: float = 0.03    # Cut-loss total jika floating loss >= 3% modal akun


class RiskManager:
    def __init__(self, limits: RiskLimits):
        self.limits = limits
        self.daily_pnl_pct = 0.0  # di-update TradingEngine._update_daily_pnl()

    # ------------------------------------------------------------------
    # Initial Position Sizing
    # ------------------------------------------------------------------
    def check_and_size(
        self,
        equity_usd: float,
        signal: Signal,
        confidence: float,
        sl_distance_pct: float | None = None,
    ) -> float:
        """Return ukuran posisi awal (notional USD). 0 berarti sinyal ditolak."""
        if self.daily_pnl_pct <= -self.limits.max_daily_loss_pct:
            log.warning("Kill switch aktif: batas rugi harian tercapai")
            return 0.0

        if confidence < self.limits.min_confidence:
            log.info("Sinyal ditolak: confidence %s < %s", confidence, self.limits.min_confidence)
            return 0.0

        if signal == Signal.HOLD:
            return 0.0

        if sl_distance_pct is not None and sl_distance_pct > 0:
            risk_money = equity_usd * self.limits.risk_per_trade_pct
            position_size = risk_money / sl_distance_pct
            max_size = equity_usd * self.limits.max_leverage
            if position_size > max_size:
                log.info("Notional %.2f di-cap ke %.2f (maks %.0fx equity)", position_size, max_size, self.limits.max_leverage)
                position_size = max_size
            return position_size

        # fallback sizing lama
        position_size = equity_usd * self.limits.max_position_pct * confidence
        return position_size

    def compute_sl_tp(self, signal: Signal, entry_price: float, atr: float) -> tuple[float, float]:
        """SL/TP awal: gunakan mode 'atr' (adaptif), 'pct' (% harga), atau 'point' (jarak fixed $).

        Jika DCA aktif (dca_enabled=True), jarak SL diletakkan di bawah seluruh lapis DCA
        agar Lapis 2 dan Lapis 3 memiliki ruang untuk averaging down tanpa tertabrak SL Lapis 1.
        """
        if self.limits.tpsl_mode == "pct":
            tp_distance = entry_price * (self.limits.tp_pct / 100.0)
            if self.limits.dca_enabled and self.limits.dca_max_orders > 1:
                total_drop_pct = (self.limits.dca_max_orders * self.limits.dca_step_pct) + self.limits.sl_pct
                sl_distance = entry_price * (total_drop_pct / 100.0)
                log.debug("DCA aktif (mode pct): SL diletakkan %.2f%% di bawah entry ($%.2f)", total_drop_pct, sl_distance)
            else:
                sl_distance = entry_price * (self.limits.sl_pct / 100.0)
                log.debug("Single entry (mode pct): SL=%.2f%% ($%.2f) TP=%.2f%% ($%.2f)", self.limits.sl_pct, sl_distance, self.limits.tp_pct, tp_distance)
        elif self.limits.tpsl_mode == "point":
            tp_distance = self.limits.tp_points
            if self.limits.dca_enabled and self.limits.dca_max_orders > 1:
                total_drop_pts = (self.limits.dca_max_orders * self.limits.dca_step_points) + self.limits.sl_points
                sl_distance = total_drop_pts
                log.debug("DCA aktif (mode point): SL diletakkan $%.2f di bawah entry", sl_distance)
            else:
                sl_distance = self.limits.sl_points
                log.debug("Single entry (mode point): SL=$%.2f TP=$%.2f", sl_distance, tp_distance)
        else:  # mode atr (default)
            tp_distance = (atr * self.limits.atr_sl_mult) * self.limits.tp_rr_ratio
            if self.limits.dca_enabled and self.limits.dca_max_orders > 1:
                total_drop_atr = (self.limits.dca_max_orders * self.limits.dca_step_atr_mult) + self.limits.atr_sl_mult
                sl_distance = atr * total_drop_atr
                log.debug("DCA aktif (mode atr): SL diletakkan %.2fx ATR di bawah entry ($%.2f)", total_drop_atr, sl_distance)
            else:
                sl_distance = atr * self.limits.atr_sl_mult
                log.debug("Single entry (mode atr): SL=%.2fx ATR ($%.2f) TP=%.2fx SL ($%.2f)", self.limits.atr_sl_mult, sl_distance, self.limits.tp_rr_ratio, tp_distance)

        if signal == Signal.BUY:
            sl = entry_price - sl_distance
            tp = entry_price + tp_distance
        else:  # SELL
            sl = entry_price + sl_distance
            tp = entry_price - tp_distance

        return round(sl, 2), round(tp, 2)

    # ------------------------------------------------------------------
    # Smart DCA / Averaging Calculations
    # ------------------------------------------------------------------
    def should_trigger_dca(
        self,
        signal: Signal,
        last_layer_price: float,
        current_price: float,
        entry_atr: float,
        current_layer_count: int,
    ) -> bool:
        """True jika harga saat ini sudah mencapai jarak step untuk lapis berikutnya."""
        if not self.limits.dca_enabled:
            return False

        if current_layer_count >= self.limits.dca_max_orders:
            return False

        if last_layer_price <= 0 or current_price <= 0:
            return False

        if self.limits.tpsl_mode == "pct":
            required_drop = last_layer_price * (self.limits.dca_step_pct / 100.0)
        elif self.limits.tpsl_mode == "point":
            required_drop = self.limits.dca_step_points
        else:
            # Mode atr: jarak lapis = ATR * multiplier
            if entry_atr <= 0:
                return False
            required_drop = entry_atr * self.limits.dca_step_atr_mult

        if signal == Signal.BUY:
            return current_price <= (last_layer_price - required_drop)
        else:
            return current_price >= (last_layer_price + required_drop)

    def compute_dca_layer_size(
        self,
        equity_usd: float,
        base_size_usd: float,
        layer_index: int,  # 0-indexed: lapis ke-2 -> layer_index=1
    ) -> float:
        """Hitung ukuran USD untuk lapis DCA ke-N."""
        mult = self.limits.dca_lot_multiplier ** layer_index
        layer_size_usd = base_size_usd * mult
        max_size = equity_usd * self.limits.max_leverage
        return min(layer_size_usd, max_size)

    def compute_dca_grid_plan(
        self,
        signal: Signal,
        entry_price: float,
        base_size_usd: float,
        entry_atr: float,
        equity_usd: float,
    ) -> list[dict]:
        """
        Hitung rencana pre-placed limit orders untuk seluruh lapis DCA (Lapis 2, 3, ...).

        Return list of dicts, satu per lapis:
            {
                "layer": int,         # nomor lapis (2, 3, ...)
                "price": float,       # harga limit order
                "size_usd": float,    # notional USD
                "size_asset": float,  # quantity aset (BELUM dibulatkan ke stepSize)
            }
        """
        if not self.limits.dca_enabled or self.limits.dca_max_orders <= 1:
            return []

        grid = []
        last_price = entry_price

        for layer_idx in range(1, self.limits.dca_max_orders):  # layer_idx 1 = Lapis 2
            # ── Hitung harga lapis berikutnya ──────────────────────────────
            if self.limits.tpsl_mode == "pct":
                step = last_price * (self.limits.dca_step_pct / 100.0)
            elif self.limits.tpsl_mode == "point":
                step = self.limits.dca_step_points
            else:
                if entry_atr <= 0:
                    break
                step = entry_atr * self.limits.dca_step_atr_mult

            if signal == Signal.BUY:
                layer_price = last_price - step
            else:  # SELL
                layer_price = last_price + step

            # ── Hitung ukuran lapis ────────────────────────────────────────
            size_usd = self.compute_dca_layer_size(equity_usd, base_size_usd, layer_idx)
            size_asset = size_usd / layer_price if layer_price > 0 else 0

            grid.append({
                "layer": layer_idx + 1,          # nomor lapis (2, 3, ...)
                "price": round(layer_price, 2),
                "size_usd": size_usd,
                "size_asset": size_asset,
            })

            last_price = layer_price

        return grid

    def compute_dca_avg_and_tp(
        self,
        signal: Signal,
        layers: list[dict],  # [{"price": float, "size": float, ...}]
        entry_atr: float,
    ) -> tuple[float, float, float]:
        """
        Hitung Weighted Average Price, Total Size, dan Target Take Profit baru gabungan.
        Return (avg_price, total_size, new_tp).
        """
        total_size = sum(layer["size"] for layer in layers)
        if total_size <= 0:
            return 0.0, 0.0, 0.0

        total_cost = sum(layer["price"] * layer["size"] for layer in layers)
        avg_price = total_cost / total_size

        if self.limits.tpsl_mode == "pct":
            tp_distance = avg_price * (self.limits.tp_pct / 100.0)
        elif self.limits.tpsl_mode == "point":
            tp_distance = self.limits.dca_tp_points if self.limits.dca_tp_points > 0 else self.limits.tp_points
        else:
            tp_distance = entry_atr * self.limits.dca_tp_rr_ratio

        if signal == Signal.BUY:
            new_tp = avg_price + tp_distance
        else:
            new_tp = avg_price - tp_distance

        return round(avg_price, 2), total_size, round(new_tp, 2)

    def is_hard_sl_triggered(
        self,
        floating_loss_usd: float,  # nilai positif dari kerugian (misal floating -150 USD -> 150)
        equity_usd: float,
    ) -> bool:
        """True jika total floating loss keranjang sudah melampaui batas hard SL (misal >= 3% equity)."""
        if equity_usd <= 0:
            return False
        loss_pct = floating_loss_usd / equity_usd
        return loss_pct >= self.limits.dca_hard_sl_equity_pct

    # ------------------------------------------------------------------
    # Trailing Stop (berbasis Average Entry Price)
    # ------------------------------------------------------------------
    def compute_trailing_sl(
        self,
        signal: Signal,
        avg_entry_price: float,
        current_price: float,
        current_sl: float,
        entry_atr: float,
    ) -> float | None:
        """
        Trailing stop untuk posisi (single atau DCA multi-layer).
        Dihitung dari avg_entry_price.
        Mendukung mode 'atr' (dinamis jarak ATR) dan 'point' (Discrete Step-Lock Trailing).
        Return SL baru (float) jika perlu digeser, atau None jika belum waktunya.
        """
        if not self.limits.use_trailing:
            return None

        # ── Mode POINT: Discrete Step-Lock Trailing ────────────────────────
        if self.limits.tpsl_mode == "point":
            if self.limits.trailing_start_points <= 0:
                return None

            if signal == Signal.BUY:
                profit_dist = current_price - avg_entry_price
                if profit_dist < self.limits.trailing_start_points:
                    return None
                extra_profit = profit_dist - self.limits.trailing_start_points
                steps = int(extra_profit // self.limits.trailing_step_points) if self.limits.trailing_step_points > 0 else 0
                locked_profit = self.limits.trailing_lock_points + (steps * self.limits.trailing_move_points)
                new_sl = avg_entry_price + locked_profit
                if current_sl is None or current_sl <= 0 or new_sl > (current_sl + 1e-6):
                    return round(new_sl, 2)
                return None
            else:  # SELL
                profit_dist = avg_entry_price - current_price
                if profit_dist < self.limits.trailing_start_points:
                    return None
                extra_profit = profit_dist - self.limits.trailing_start_points
                steps = int(extra_profit // self.limits.trailing_step_points) if self.limits.trailing_step_points > 0 else 0
                locked_profit = self.limits.trailing_lock_points + (steps * self.limits.trailing_move_points)
                new_sl = avg_entry_price - locked_profit
                if current_sl is None or current_sl <= 0 or new_sl < (current_sl - 1e-6):
                    return round(new_sl, 2)
                return None

        # ── Mode ATR (default) ─────────────────────────────────────────────
        if entry_atr <= 0:
            return None

        trail_start_dist = entry_atr * self.limits.trailing_start_atr_mult
        trail_dist = entry_atr * self.limits.trailing_distance_atr_mult
        trail_step = entry_atr * self.limits.trailing_step_atr_mult

        if signal == Signal.BUY:
            profit_dist = current_price - avg_entry_price
            if profit_dist < trail_start_dist:
                return None
            new_sl = current_price - trail_dist
            if current_sl is None or current_sl <= 0 or new_sl > (current_sl + trail_step):
                return round(new_sl, 2)
            return None
        else:  # SELL
            profit_dist = avg_entry_price - current_price
            if profit_dist < trail_start_dist:
                return None
            new_sl = current_price + trail_dist
            if current_sl is None or current_sl <= 0 or new_sl < (current_sl - trail_step):
                return round(new_sl, 2)
            return None