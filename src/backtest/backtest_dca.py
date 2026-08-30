"""
Simulasi Backtest Komparatif Smart DCA Multi-Timeframe (15M, 30M, 1H).

Menguji performa Smart DCA (Averaging Down) berbasis ATR dengan Average-Price Trailing Stop
pada data historis 2 tahun Binance USDⓈ-M Futures (net of taker fee 0.05%).
"""

import argparse
import os
import sys

import numpy as np
import pandas as pd
import ta

from src.strategy.trend_reversal import TrendReversalStrategy
from src.strategy.base import Signal


def run_dca_backtest(
    csv_path: str,
    interval: str,
    dca_max_orders: int = 3,
    dca_step_atr_mult: float = 1.5,
    dca_lot_multiplier: float = 1.0,
    dca_tp_rr_ratio: float = 1.0,
    dca_hard_sl_equity_pct: float = 0.03,
    use_trailing: bool = True,
    trailing_start_atr_mult: float = 1.2,
    trailing_distance_atr_mult: float = 1.0,
    initial_equity: float = 5000.0,
    risk_per_trade_pct: float = 0.01,
    taker_fee_pct: float = 0.0005,  # 0.05% taker fee Binance Futures
) -> dict:
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"File {csv_path} tidak ditemukan!")

    df = pd.read_csv(csv_path)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
        elif col[0] in df.columns:
            df[col] = df[col[0]].astype(float)

    # Indikator
    strategy = TrendReversalStrategy(require_trend_alignment=False)
    candles_dict = [
        {"o": row["open"], "h": row["high"], "l": row["low"], "c": row["close"], "v": row["volume"], "t": row.get("t", i)}
        for i, row in df.iterrows()
    ]
    df_calc = strategy._to_df(candles_dict)
    df_calc = strategy._compute_indicators(df_calc)

    equity = initial_equity
    peak_equity = initial_equity
    max_drawdown = 0.0

    baskets = []
    active_basket = None

    # Iterasi candle demi candle
    for i in range(60, len(df_calc)):
        row = df_calc.iloc[i]
        prev_row = df_calc.iloc[i - 1]
        cur_atr = float(row["atr"]) if row["atr"] == row["atr"] else 0.0

        if cur_atr <= 0:
            continue

        # --- A. KELOLA BASKET AKTIF ---
        if active_basket is not None:
            side = active_basket["side"]
            layers = active_basket["layers"]
            avg_px = active_basket["avg_price"]
            tot_sz = active_basket["total_size"]
            base_atr = active_basket["entry_atr"]
            tp_px = active_basket["tp"]
            sl_px = active_basket["sl"]

            # 1. Cek Take Profit
            hit_tp = (row["h"] >= tp_px) if side == "BUY" else (row["l"] <= tp_px)
            if hit_tp:
                exit_price = tp_px
                gross_pnl = (exit_price - avg_px) * tot_sz if side == "BUY" else (avg_px - exit_price) * tot_sz
                total_notional = sum(l["price"] * l["size"] for l in layers) + (exit_price * tot_sz)
                fees = total_notional * taker_fee_pct
                net_pnl = gross_pnl - fees
                equity += net_pnl

                baskets.append({
                    "outcome": "TP",
                    "layers": len(layers),
                    "net_pnl": net_pnl,
                    "return_pct": (net_pnl / equity) * 100,
                    "bars": i - active_basket["start_bar"],
                })
                active_basket = None
                peak_equity = max(peak_equity, equity)
                max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
                continue

            # 2. Cek Trailing Stop (hanya jika trailing sudah aktif)
            if active_basket.get("trailed") and sl_px is not None:
                hit_trail = (row["l"] <= sl_px) if side == "BUY" else (row["h"] >= sl_px)
                if hit_trail:
                    exit_price = sl_px
                    gross_pnl = (exit_price - avg_px) * tot_sz if side == "BUY" else (avg_px - exit_price) * tot_sz
                    total_notional = sum(l["price"] * l["size"] for l in layers) + (exit_price * tot_sz)
                    fees = total_notional * taker_fee_pct
                    net_pnl = gross_pnl - fees
                    equity += net_pnl

                    baskets.append({
                        "outcome": "TRAIL_SL",
                        "layers": len(layers),
                        "net_pnl": net_pnl,
                        "return_pct": (net_pnl / equity) * 100,
                        "bars": i - active_basket["start_bar"],
                    })
                    active_basket = None
                    peak_equity = max(peak_equity, equity)
                    max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
                    continue

            # 3. Cek Hard SL Cut-loss Darurat (-3% equity atau Basket Final SL)
            worst_px = row["l"] if side == "BUY" else row["h"]
            floating_pnl = (worst_px - avg_px) * tot_sz if side == "BUY" else (avg_px - worst_px) * tot_sz
            hit_basket_sl = (sl_px is not None and not active_basket.get("trailed") and ((row["l"] <= sl_px) if side == "BUY" else (row["h"] >= sl_px)))
            hit_hard_sl = (floating_pnl < 0 and abs(floating_pnl) >= (equity * dca_hard_sl_equity_pct))

            if hit_hard_sl or hit_basket_sl:
                exit_price = sl_px if hit_basket_sl else worst_px
                gross_pnl = (exit_price - avg_px) * tot_sz if side == "BUY" else (avg_px - exit_price) * tot_sz
                total_notional = sum(l["price"] * l["size"] for l in layers) + (exit_price * tot_sz)
                fees = total_notional * taker_fee_pct
                net_pnl = gross_pnl - fees
                equity += net_pnl

                baskets.append({
                    "outcome": "HARD_SL" if hit_hard_sl else "FINAL_SL",
                    "layers": len(layers),
                    "net_pnl": net_pnl,
                    "return_pct": (net_pnl / equity) * 100,
                    "bars": i - active_basket["start_bar"],
                })
                active_basket = None
                peak_equity = max(peak_equity, equity)
                max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
                continue

            # 4. Cek Trailing Stop Activation & Update (dari Average Price)
            if use_trailing:
                trail_start_dist = base_atr * trailing_start_atr_mult
                trail_dist = base_atr * trailing_distance_atr_mult
                best_px = row["h"] if side == "BUY" else row["l"]
                profit_dist = (best_px - avg_px) if side == "BUY" else (avg_px - best_px)

                if profit_dist >= trail_start_dist:
                    new_sl = (best_px - trail_dist) if side == "BUY" else (best_px + trail_dist)
                    if side == "BUY" and (sl_px is None or new_sl > sl_px):
                        active_basket["sl"] = new_sl
                        active_basket["trailed"] = True
                    elif side == "SELL" and (sl_px is None or new_sl < sl_px):
                        active_basket["sl"] = new_sl
                        active_basket["trailed"] = True

            # 5. Cek Buka Lapis DCA Berikutnya (jika floating minus)
            if len(layers) < dca_max_orders and not active_basket.get("trailed"):
                last_layer_px = layers[-1]["price"]
                required_step = base_atr * dca_step_atr_mult
                trigger_dca = (row["l"] <= last_layer_px - required_step) if side == "BUY" else (row["h"] >= last_layer_px + required_step)

                if trigger_dca:
                    dca_fill_px = (last_layer_px - required_step) if side == "BUY" else (last_layer_px + required_step)
                    base_sz_usd = layers[0]["size"] * layers[0]["price"]
                    layer_sz_usd = base_sz_usd * (dca_lot_multiplier ** len(layers))
                    layer_sz_asset = layer_sz_usd / dca_fill_px

                    layers.append({"price": dca_fill_px, "size": layer_sz_asset})
                    tot_sz = sum(l["size"] for l in layers)
                    avg_px = sum(l["price"] * l["size"] for l in layers) / tot_sz
                    new_tp = (avg_px + base_atr * dca_tp_rr_ratio) if side == "BUY" else (avg_px - base_atr * dca_tp_rr_ratio)

                    # Update Basket SL (ditempatkan di bawah lapis terakhir)
                    final_sl = (dca_fill_px - base_atr * 2.0) if side == "BUY" else (dca_fill_px + base_atr * 2.0)

                    active_basket["layers"] = layers
                    active_basket["total_size"] = tot_sz
                    active_basket["avg_price"] = avg_px
                    active_basket["tp"] = new_tp
                    active_basket["sl"] = final_sl

            peak_equity = max(peak_equity, equity)
            max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity)
            continue

        # --- B. EVALUASI ENTRY BARU (LAPIS 1) ---
        res = strategy._decide_from_rows(row, prev_row)
        if res.signal in (Signal.BUY, Signal.SELL):
            sl_dist = cur_atr * (dca_step_atr_mult * (dca_max_orders - 1) + 2.0)
            sl_distance_pct = (cur_atr * 2.0) / row["c"]
            risk_money = equity * risk_per_trade_pct
            pos_size_usd = risk_money / sl_distance_pct
            max_size = equity * 3.0
            pos_size_usd = min(pos_size_usd, max_size)

            size_asset = pos_size_usd / row["c"]
            side_str = "BUY" if res.signal == Signal.BUY else "SELL"
            initial_tp = (row["c"] + cur_atr * dca_tp_rr_ratio) if res.signal == Signal.BUY else (row["c"] - cur_atr * dca_tp_rr_ratio)
            # Basket initial final SL (setelah seluruh lapis)
            initial_sl = (row["c"] - sl_dist) if res.signal == Signal.BUY else (row["c"] + sl_dist)

            active_basket = {
                "side": side_str,
                "entry_price": row["c"],
                "avg_price": row["c"],
                "entry_atr": cur_atr,
                "total_size": size_asset,
                "tp": initial_tp,
                "sl": initial_sl,
                "layers": [{"price": row["c"], "size": size_asset}],
                "start_bar": i,
                "trailed": False,
            }

    # Ringkasan Hasil
    df_baskets = pd.DataFrame(baskets)
    total_baskets = len(df_baskets)
    if total_baskets == 0:
        return {"error": "Tidak ada trade yang dieksekusi"}

    win_baskets = df_baskets[df_baskets["net_pnl"] > 0]
    loss_baskets = df_baskets[df_baskets["net_pnl"] <= 0]
    win_rate = (len(win_baskets) / total_baskets) * 100.0

    total_profit = win_baskets["net_pnl"].sum()
    total_loss = abs(loss_baskets["net_pnl"].sum())
    profit_factor = (total_profit / total_loss) if total_loss > 0 else 999.0
    net_return_pct = ((equity - initial_equity) / initial_equity) * 100.0

    l1_count = len(df_baskets[df_baskets["layers"] == 1])
    l2_count = len(df_baskets[df_baskets["layers"] == 2])
    l3_count = len(df_baskets[df_baskets["layers"] >= 3])
    hard_sl_count = len(df_baskets[df_baskets["outcome"] == "HARD_SL"])

    return {
        "interval": interval,
        "initial_equity": initial_equity,
        "final_equity": equity,
        "net_return_pct": net_return_pct,
        "total_baskets": total_baskets,
        "baskets_per_month": total_baskets / 24.0,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "max_drawdown_pct": max_drawdown * 100.0,
        "layer_1_pct": (l1_count / total_baskets) * 100.0,
        "layer_2_pct": (l2_count / total_baskets) * 100.0,
        "layer_3_pct": (l3_count / total_baskets) * 100.0,
        "hard_sl_count": hard_sl_count,
        "avg_hold_bars": df_baskets["bars"].mean(),
    }


def main():
    parser = argparse.ArgumentParser(description="Multi-Timeframe Smart DCA Backtest")
    parser.add_argument("--dca_max_orders", type=int, default=3)
    parser.add_argument("--dca_step_atr_mult", type=float, default=1.5)
    parser.add_argument("--dca_lot_multiplier", type=float, default=1.0)
    parser.add_argument("--dca_tp_rr_ratio", type=float, default=1.0)
    args = parser.parse_args()

    files = [
        ("15m", "data/BTCUSDT_15m.csv"),
        ("30m", "data/BTCUSDT_30m.csv"),
        ("1h", "data/BTCUSDT_1h.csv"),
    ]

    results = []
    print("\n" + "=" * 80)
    print("   SIMULASI BACKTEST SMART DCA BINANCE BTCUSDT (DATA 2 TAHUN - NET OF FEE)")
    print("   Pengaturan: Max Lapis = %d | Step = %.1fx ATR | TP = %.1fx ATR Avg Px" %
          (args.dca_max_orders, args.dca_step_atr_mult, args.dca_tp_rr_ratio))
    print("=" * 80)

    for tf, path in files:
        if not os.path.exists(path):
            print(f"[{tf}] File {path} belum ada, lewati...")
            continue
        print(f"Menjalankan simulasi untuk timeframe {tf.upper()} ({path})...")
        res = run_dca_backtest(
            csv_path=path,
            interval=tf,
            dca_max_orders=args.dca_max_orders,
            dca_step_atr_mult=args.dca_step_atr_mult,
            dca_lot_multiplier=args.dca_lot_multiplier,
            dca_tp_rr_ratio=args.dca_tp_rr_ratio,
        )
        results.append(res)

    print("\n" + "=" * 80)
    print("                          TABEL PERBANDINGAN HASIL")
    print("=" * 80)
    headers = ["Metrik Performa", "15 Menit (15M)", "30 Menit (30M)", "1 Jam (1H)"]
    print(f"{headers[0]:<28} | {headers[1]:<15} | {headers[2]:<15} | {headers[3]:<15}")
    print("-" * 80)

    res_map = {r["interval"].lower(): r for r in results}

    def _val(tf, key, fmt=""):
        if tf not in res_map or "error" in res_map[tf]:
            return "N/A"
        v = res_map[tf].get(key)
        if fmt == "$":
            return f"${v:,.2f}"
        return (fmt % v) if fmt else str(v)

    print(f"{'Total Net Return (%)':<28} | {_val('15m', 'net_return_pct', '%+.2f%%'):<15} | {_val('30m', 'net_return_pct', '%+.2f%%'):<15} | {_val('1h', 'net_return_pct', '%+.2f%%'):<15}")
    print(f"{'Saldo Akhir ($5,000 modal)':<28} | {_val('15m', 'final_equity', '$'):<15} | {_val('30m', 'final_equity', '$'):<15} | {_val('1h', 'final_equity', '$'):<15}")
    print(f"{'Total Siklus Basket':<28} | {_val('15m', 'total_baskets', '%d'):<15} | {_val('30m', 'total_baskets', '%d'):<15} | {_val('1h', 'total_baskets', '%d'):<15}")
    print(f"{'Frekuensi per Bulan':<28} | {_val('15m', 'baskets_per_month', '%.1f /bln'):<15} | {_val('30m', 'baskets_per_month', '%.1f /bln'):<15} | {_val('1h', 'baskets_per_month', '%.1f /bln'):<15}")
    print(f"{'Basket Win Rate':<28} | {_val('15m', 'win_rate', '%.1f%%'):<15} | {_val('30m', 'win_rate', '%.1f%%'):<15} | {_val('1h', 'win_rate', '%.1f%%'):<15}")
    print(f"{'Profit Factor':<28} | {_val('15m', 'profit_factor', '%.2f'):<15} | {_val('30m', 'profit_factor', '%.2f'):<15} | {_val('1h', 'profit_factor', '%.2f'):<15}")
    print(f"{'Max Drawdown':<28} | {_val('15m', 'max_drawdown_pct', '%.2f%%'):<15} | {_val('30m', 'max_drawdown_pct', '%.2f%%'):<15} | {_val('1h', 'max_drawdown_pct', '%.2f%%'):<15}")
    print("-" * 80)
    print(f"{'Selesai di Lapis 1 Saja':<28} | {_val('15m', 'layer_1_pct', '%.1f%%'):<15} | {_val('30m', 'layer_1_pct', '%.1f%%'):<15} | {_val('1h', 'layer_1_pct', '%.1f%%'):<15}")
    print(f"{'Butuh Lapis 2 DCA':<28} | {_val('15m', 'layer_2_pct', '%.1f%%'):<15} | {_val('30m', 'layer_2_pct', '%.1f%%'):<15} | {_val('1h', 'layer_2_pct', '%.1f%%'):<15}")
    print(f"{'Mencapai Lapis 3 (Max)':<28} | {_val('15m', 'layer_3_pct', '%.1f%%'):<15} | {_val('30m', 'layer_3_pct', '%.1f%%'):<15} | {_val('1h', 'layer_3_pct', '%.1f%%'):<15}")
    print(f"{'Hard SL Hit (Cut-Loss)':<28} | {_val('15m', 'hard_sl_count', '%d kali'):<15} | {_val('30m', 'hard_sl_count', '%d kali'):<15} | {_val('1h', 'hard_sl_count', '%d kali'):<15}")
    print("=" * 80)


if __name__ == "__main__":
    main()
