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
    atr_sl_mult: float = 2.0           # SL = ATR * mult (adaptif volatilitas)
    tp_rr_ratio: float = 1.5           # TP = jarak SL * rasio (RR fixed)

    # --- Position sizing berbasis risiko (risk percent per trade) ---
    risk_per_trade_pct: float = 0.01   # 1% equity risiko per trade

    # --- Trailing stop (berbasis Average Entry Price) ---
    use_trailing: bool = True
    trailing_start_atr_mult: float = 1.2    # Mulai trailing setelah profit >= ATR * mult dari avg entry
    trailing_distance_atr_mult: float = 1.0  # Jarak SL baru di belakang harga berjalan
    trailing_step_atr_mult: float = 0.3     # SL cuma digeser kalau pergerakan >= step ini (anti-churn)

    # --- Smart DCA / Grid Settings ---
    dca_enabled: bool = False               # true = izinkan penambahan lapis saat floating minus
    dca_max_orders: int = 3                 # Maksimal jumlah lapis (termasuk entry awal)
    dca_step_atr_mult: float = 1.5          # Jarak buka lapis berikutnya (tiap minus 1.5x ATR)
    dca_lot_multiplier: float = 1.0         # Pengali lot lapis berikutnya (1.0 = equal sizing)
    dca_tp_rr_ratio: float = 1.0            # TP gabungan = avg_price +/- (ATR * rasio)
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
        """SL/TP awal berbasis ATR & harga langsung."""
        sl_distance = atr * self.limits.atr_sl_mult
        tp_distance = sl_distance * self.limits.tp_rr_ratio

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
        """True jika harga saat ini sudah mencapai jarak step ATR untuk lapis berikutnya."""
        if not self.limits.dca_enabled:
            return False

        if current_layer_count >= self.limits.dca_max_orders:
            return False

        if entry_atr <= 0 or last_layer_price <= 0 or current_price <= 0:
            return False

        required_drop = entry_atr * self.limits.dca_step_atr_mult

        if signal == Signal.BUY:
            # BUY: harga harus turun sebesar required_drop dari entry lapis terakhir
            return current_price <= (last_layer_price - required_drop)
        else:
            # SELL: harga harus naik sebesar required_drop dari entry lapis terakhir
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
        Return SL baru (float) jika perlu digeser, atau None jika belum waktunya.
        """
        if not self.limits.use_trailing or entry_atr <= 0:
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