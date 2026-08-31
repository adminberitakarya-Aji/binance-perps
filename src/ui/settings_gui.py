"""
Desktop GUI Settings (MetaTrader 5 / MT5 Style Expert Inputs Window).
Memungkinkan konfigurasi visual lengkap untuk seluruh parameter strategi, ML, DCA, TPSL, dan Risk
dengan antarmuka dark-theme MT5, validasi tipe data, serta tombol Load / Save / OK / Cancel / Reset.
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# Skema Definisi Parameter MT5 Style
# format: (var_name, display_label, type, default_val, options/choices, section_header, hint)
PARAMETERS_SCHEMA = [
    # ===== SYMBOL & BROKER SETTINGS =====
    ("BINANCE_SYMBOL", "Custom Symbol (BTCUSDT, ETHUSDT, dsb.)", "str", "BTCUSDT", None, "===== SYMBOL & BROKER SETTINGS =====", "Pasangan aset futures"),
    ("BINANCE_USE_TESTNET", "Gunakan Testnet Binance (true = testnet, false = live)", "bool", "true", ["true", "false"], None, "Lingkungan API Binance Futures"),
    ("TRADING_INTERVAL", "Timeframe Candle Trading", "choice", "1h", ["1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "1d"], None, "Timeframe analisis & eksekusi bot"),
    ("BINANCE_API_KEY", "Binance API Key", "password", "", None, None, "API Key Binance Futures"),
    ("BINANCE_API_SECRET", "Binance API Secret", "password", "", None, None, "API Secret Binance Futures"),

    # ===== TELEGRAM ALERT =====
    ("TELEGRAM_BOT_TOKEN", "Telegram Bot Token (kosongkan = silent)", "str", "", None, "===== TELEGRAM ALERT (OPSIONAL) =====", "Token bot telegram untuk notifikasi"),
    ("TELEGRAM_CHAT_ID", "Telegram Chat ID (kosongkan = silent)", "str", "", None, None, "ID chat/channel telegram tujuan"),

    # ===== MACHINE LEARNING / ONNX (FASE 2) =====
    ("ML_FILTER_ENABLED", "Aktifkan Filter Machine Learning (ONNX)", "bool", "true", ["true", "false"], "===== MACHINE LEARNING / ONNX (FASE 2) =====", "Gunakan ML filter sebelum buka posisi"),
    ("ML_THRESHOLD", "Min Win Probability Threshold (0.35 - 0.70)", "float", "0.50", None, None, "Ambang probabilitas kemenangan minimum"),
    ("ML_MODEL_PATH", "Model Path (kosongkan = default models/*.onnx)", "str", "", None, None, "Lokasi file model .onnx"),

    # ===== STRATEGI & MODE TP/SL =====
    ("TPSL_MODE", "Mode Perhitungan TP/SL ('atr', 'pct', atau 'point')", "choice", "atr", ["atr", "pct", "point"], "===== STRATEGI & MODE TP/SL =====", "Pilihan dasar kalkulasi SL/TP & DCA"),
    ("ATR_SL_MULT", "Jarak SL Awal (ATR Multiplier - jika mode ATR)", "float", "2.0", None, None, "Kelipatan ATR untuk SL awal"),
    ("TP_RR_RATIO", "Target TP Ratio (RR Multiplier - jika mode ATR)", "float", "1.5", None, None, "Rasio Take Profit terhadap jarak SL"),
    ("SL_PCT", "Stop Loss % dari Entry (jika mode PCT)", "float", "0.5", None, None, "Jarak SL dalam persen nominal harga"),
    ("TP_PCT", "Take Profit % dari Entry (jika mode PCT)", "float", "1.0", None, None, "Jarak TP dalam persen nominal harga"),
    ("SL_POINTS", "Stop Loss Poin/$ dari Entry (jika mode POINT)", "float", "300.0", None, None, "Jarak SL dalam nominal dollar ($) / poin"),
    ("TP_POINTS", "Take Profit Poin/$ dari Entry (jika mode POINT)", "float", "450.0", None, None, "Jarak TP dalam nominal dollar ($) / poin"),

    # ===== MONEY MANAGEMENT & RISK =====
    ("RISK_PER_TRADE_PCT", "Risk % Equity per Trade (0.01 = 1% modal)", "float", "0.01", None, "===== MONEY MANAGEMENT & RISK =====", "Persentase risiko kerugian modal per posisi"),
    ("MAX_LEVERAGE", "Maks Notional Cap / Leverage (3.0 = 3x modal)", "float", "3.0", None, None, "Batas atas ukuran posisi total"),
    ("MAX_DAILY_LOSS_PCT", "Kill Switch Rugi Harian (0.05 = -5% cut)", "float", "0.05", None, None, "Batas batas rugi harian otomatis"),

    # ===== SMART DCA / AVERAGING RECOVERY =====
    ("DCA_ENABLED", "Aktifkan Smart DCA Averaging Recovery", "bool", "true", ["true", "false"], "===== SMART DCA / AVERAGING RECOVERY =====", "Buka lapis averaging saat floating minus"),
    ("DCA_MAX_ORDERS", "Maksimal Level Averaging Tambahan (default: 3)", "int", "3", None, None, "Jumlah total lapis order maksimal"),
    ("DCA_STEP_ATR_MULT", "Jarak Lapis DCA (ATR Mult - jika mode ATR)", "float", "1.5", None, None, "Jarak buka lapis berikutnya berbasis ATR"),
    ("DCA_STEP_PCT", "Jarak Lapis DCA (% Harga - jika mode PCT)", "float", "0.5", None, None, "Jarak buka lapis berikutnya berbasis persen"),
    ("DCA_STEP_POINTS", "Jarak Lapis DCA (Poin/$ - jika mode POINT)", "float", "200.0", None, None, "Jarak buka lapis berikutnya dalam poin dollar ($)"),
    ("DCA_LOT_MULTIPLIER", "Pengali Lot Tiap Level (1.0 = equal, 1.5x)", "float", "1.0", None, None, "Multiplier ukuran lot untuk lapis baru"),
    ("DCA_TP_RR_RATIO", "Target Profit Gabungan dari Avg Price (RR - ATR)", "float", "1.5", None, None, "Target TP keranjang dari average entry price (mode ATR)"),
    ("DCA_TP_POINTS", "Target Profit Gabungan dari Avg Price (Poin/$)", "float", "200.0", None, None, "Target TP keranjang dari average entry price dalam dollar ($)"),
    ("DCA_HARD_SL_EQUITY_PCT", "Cut-Loss Darurat Floating (% Saldo, mis. 0.03)", "float", "0.03", None, None, "Batas darurat kerugian keranjang total"),

    # ===== TRAILING STOP (AVERAGE POSITION) =====
    ("TRAILING_ENABLED", "Aktifkan Average-Price Trailing Stop", "bool", "true", ["true", "false"], "===== TRAILING STOP (AVERAGE POSITION) =====", "Kunci profit berjalan secara otomatis"),
    ("TRAILING_START_ATR_MULT", "Aktivasi Trailing Profit (ATR Mult - mode ATR)", "float", "1.5", None, None, "Floating profit minimal untuk mulai trailing (mode ATR)"),
    ("TRAILING_DISTANCE_ATR_MULT", "Jarak Trailing Mundur di Belakang Harga (ATR)", "float", "1.0", None, None, "Jarak SL baru dari harga tertinggi/terendah (mode ATR)"),
    ("TRAILING_STEP_ATR_MULT", "Minimal Pergeseran Harga Update SL (ATR)", "float", "0.3", None, None, "Langkah minimal pergeseran harga (mode ATR)"),
    ("TRAILING_START_POINTS", "Aktivasi Trailing Profit (Poin/$ - mode POINT)", "float", "200.0", None, None, "Floating profit ($) minimal untuk mulai trailing"),
    ("TRAILING_LOCK_POINTS", "SL Awal Terkunci Saat Aktif (Poin/$ - mode POINT)", "float", "100.0", None, None, "Nominal profit ($) yang dikunci ke SL saat awal aktif"),
    ("TRAILING_STEP_POINTS", "Milestone Kenaikan Harga (Poin/$ - mode POINT)", "float", "100.0", None, None, "Jarak pergerakan harga untuk step trailing berikutnya ($)"),
    ("TRAILING_MOVE_POINTS", "Pergeseran SL per Milestone (Poin/$ - mode POINT)", "float", "50.0", None, None, "Besar pergeseran SL maju mengunci profit setiap milestone ($)"),
]


def load_env_file(filepath: str = ".env") -> dict:
    """Baca file .env ke dalam dictionary key-value."""
    data = {}
    if not os.path.exists(filepath):
        return data
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    # Hapus inline comment jika ada
                    v_val = v.split("#")[0].strip()
                    data[k.strip()] = v_val
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
    return data


def save_env_file(filepath: str, values: dict, comments_template: str = ".env.example"):
    """Tulis ulang file .env dengan mempertahankan komentar dan struktur rapi."""
    template_lines = []
    if os.path.exists(comments_template):
        with open(comments_template, "r", encoding="utf-8") as f:
            template_lines = f.readlines()

    written_keys = set()
    output_lines = []

    if template_lines:
        for line in template_lines:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                output_lines.append(line)
            elif "=" in stripped:
                k = stripped.split("=", 1)[0].strip()
                if k in values:
                    val = values[k]
                    output_lines.append(f"{k}={val}\n")
                    written_keys.add(k)
                else:
                    output_lines.append(line)
            else:
                output_lines.append(line)

    # Tulis sisa keys yang belum tertulis di template
    for k, v in values.items():
        if k not in written_keys:
            output_lines.append(f"{k}={v}\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(output_lines)


class MT5SettingsWindow:
    def __init__(self, root: tk.Tk | tk.Toplevel | None = None, env_path: str = ".env"):
        self.env_path = env_path
        self.values = {}
        self.param_widgets = {}

        if root is None:
            self.root = tk.Tk()
            self.is_standalone = True
        else:
            self.root = tk.Toplevel(root)
            self.is_standalone = False

        self._setup_window()
        self._load_initial_data()
        self._build_ui()

    def _setup_window(self):
        self.root.title("Binance_Perps_Agent v2.11 (BTCUSDT, Multi-TF) - Expert Inputs")
        self.root.geometry("780x720")
        self.root.minsize(680, 580)
        self.root.configure(bg="#1e1e1e")

        # Set window icon/styling
        try:
            self.root.attributes("-topmost", True)
            self.root.after_idle(self.root.attributes, "-topmost", False)
        except Exception:
            pass

    def _load_initial_data(self):
        # Muat default dari schema
        for item in PARAMETERS_SCHEMA:
            var_name, _, _, default_val, _, _, _ = item
            self.values[var_name] = default_val

        # Muat dari .env jika ada
        loaded = load_env_file(self.env_path)
        for k, v in loaded.items():
            if k in self.values:
                self.values[k] = v

    def _build_ui(self):
        # Top Tab Bar (Common / Inputs)
        tab_frame = tk.Frame(self.root, bg="#252526", height=32)
        tab_frame.pack(fill=tk.X, side=tk.TOP)

        common_tab = tk.Label(tab_frame, text="Common", bg="#252526", fg="#888888", font=("Segoe UI", 9), padx=12, pady=6)
        common_tab.pack(side=tk.LEFT)

        inputs_tab = tk.Label(tab_frame, text="Inputs", bg="#1e1e1e", fg="#ffffff", font=("Segoe UI", 9, "bold"), padx=16, pady=6, relief=tk.FLAT)
        inputs_tab.pack(side=tk.LEFT)

        # Main Body Frame (Left: Table Scrollable, Right: Load/Save buttons)
        body_frame = tk.Frame(self.root, bg="#1e1e1e")
        body_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Right Side Action Buttons (Load / Save)
        right_panel = tk.Frame(body_frame, bg="#1e1e1e", width=90)
        right_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(6, 0))

        btn_style = {"bg": "#333337", "fg": "#ffffff", "activebackground": "#007acc", "activeforeground": "#ffffff",
                     "relief": tk.RAISED, "font": ("Segoe UI", 9), "width": 8, "pady": 3}

        btn_load = tk.Button(right_panel, text="Load", command=self._on_load, **btn_style)
        btn_load.pack(side=tk.TOP, pady=(40, 6))

        btn_save = tk.Button(right_panel, text="Save", command=self._on_save, **btn_style)
        btn_save.pack(side=tk.TOP, pady=6)

        # Left Side: Scrollable Table
        table_container = tk.Frame(body_frame, bg="#252526", bd=1, relief=tk.SOLID)
        table_container.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Header Row
        header_frame = tk.Frame(table_container, bg="#2d2d30", height=26)
        header_frame.pack(fill=tk.X, side=tk.TOP)

        var_header = tk.Label(header_frame, text=" Variable", bg="#2d2d30", fg="#cccccc", font=("Segoe UI", 9, "bold"), anchor="w")
        var_header.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0), pady=4)

        sep = tk.Frame(header_frame, bg="#3e3e42", width=1)
        sep.pack(side=tk.LEFT, fill=tk.Y)

        val_header = tk.Label(header_frame, text=" Value", bg="#2d2d30", fg="#cccccc", font=("Segoe UI", 9, "bold"), width=28, anchor="w")
        val_header.pack(side=tk.RIGHT, padx=(6, 24), pady=4)

        # Canvas & Scrollbar for Table rows
        canvas = tk.Canvas(table_container, bg="#1e1e1e", highlightthickness=0)
        scrollbar = ttk.Scrollbar(table_container, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = tk.Frame(canvas, bg="#1e1e1e")

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw", width=620)
        canvas.configure(yscrollcommand=scrollbar.set)

        # Enable mousewheel
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Build Rows
        row_idx = 0
        for item in PARAMETERS_SCHEMA:
            var_name, label_txt, data_type, _, choices, section_header, hint = item

            # Section Header Row
            if section_header:
                sec_frame = tk.Frame(scrollable_frame, bg="#2d2d30", height=24)
                sec_frame.pack(fill=tk.X, pady=(6 if row_idx > 0 else 2, 1))
                sec_lbl = tk.Label(sec_frame, text=f" {section_header}", bg="#2d2d30", fg="#00aff0",
                                   font=("Segoe UI", 8, "bold"), anchor="w")
                sec_lbl.pack(fill=tk.X, padx=4, pady=2)

            # Data Row Frame
            row_bg = "#1e1e1e" if row_idx % 2 == 0 else "#252526"
            row_frame = tk.Frame(scrollable_frame, bg=row_bg, height=26)
            row_frame.pack(fill=tk.X, pady=1)

            # Icon Glyphs (MT5 style: 01=int, 1/2=float, ab=str, ⇡⇣=bool)
            glyph = "ab"
            if data_type == "int": glyph = "01"
            elif data_type == "float": glyph = "½"
            elif data_type == "bool": glyph = "⇡⇣"
            elif data_type == "choice": glyph = "🎛"
            elif data_type == "password": glyph = "🔒"

            glyph_lbl = tk.Label(row_frame, text=glyph, bg=row_bg, fg="#00aaff" if data_type == "bool" else "#e06c75",
                                 font=("Consolas", 8, "bold"), width=3, anchor="center")
            glyph_lbl.pack(side=tk.LEFT, padx=(4, 0))

            # Variable Label
            var_lbl = tk.Label(row_frame, text=label_txt, bg=row_bg, fg="#e0e0e0",
                               font=("Segoe UI", 9), anchor="w")
            var_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

            # Value Entry / Widget
            val_val = self.values.get(var_name, "")
            var_storage = tk.StringVar(value=str(val_val))
            self.param_widgets[var_name] = (var_storage, data_type, choices)

            if data_type == "bool":
                cb = ttk.Combobox(row_frame, textvariable=var_storage, values=["true", "false"],
                                  state="readonly", width=14, font=("Segoe UI", 9))
                cb.pack(side=tk.RIGHT, padx=(0, 8), pady=2)
            elif data_type == "choice" and choices:
                cb = ttk.Combobox(row_frame, textvariable=var_storage, values=choices,
                                  state="readonly", width=14, font=("Segoe UI", 9))
                cb.pack(side=tk.RIGHT, padx=(0, 8), pady=2)
            elif data_type == "password":
                ent = tk.Entry(row_frame, textvariable=var_storage, bg="#2d2d30", fg="#ffffff",
                               insertbackground="#ffffff", font=("Segoe UI", 9), width=18, show="*")
                ent.pack(side=tk.RIGHT, padx=(0, 8), pady=2)
            else:
                ent = tk.Entry(row_frame, textvariable=var_storage, bg="#2d2d30", fg="#ffffff",
                               insertbackground="#ffffff", font=("Segoe UI", 9), width=18)
                ent.pack(side=tk.RIGHT, padx=(0, 8), pady=2)

            row_idx += 1

        # Bottom Action Bar (OK / Cancel / Reset)
        bottom_bar = tk.Frame(self.root, bg="#252526", height=42)
        bottom_bar.pack(fill=tk.X, side=tk.BOTTOM, padx=0, pady=0)

        action_frame = tk.Frame(bottom_bar, bg="#252526")
        action_frame.pack(side=tk.RIGHT, padx=12, pady=6)

        btn_ok = tk.Button(action_frame, text="OK", command=self._on_ok, width=10,
                           bg="#007acc", fg="#ffffff", activebackground="#0098ff", activeforeground="#ffffff",
                           font=("Segoe UI", 9, "bold"), relief=tk.RAISED, pady=3)
        btn_ok.pack(side=tk.LEFT, padx=4)

        btn_cancel = tk.Button(action_frame, text="Cancel", command=self._on_cancel, width=10,
                               bg="#333337", fg="#ffffff", activebackground="#4e4e52", activeforeground="#ffffff",
                               font=("Segoe UI", 9), relief=tk.RAISED, pady=3)
        btn_cancel.pack(side=tk.LEFT, padx=4)

        btn_reset = tk.Button(action_frame, text="Reset", command=self._on_reset, width=10,
                              bg="#333337", fg="#ffffff", activebackground="#4e4e52", activeforeground="#ffffff",
                              font=("Segoe UI", 9), relief=tk.RAISED, pady=3)
        btn_reset.pack(side=tk.LEFT, padx=4)

    def _collect_values(self) -> dict:
        result = {}
        for var_name, (str_var, data_type, _) in self.param_widgets.items():
            raw = str_var.get().strip()
            # Validasi sederhana
            if data_type == "int":
                try:
                    int(raw)
                except ValueError:
                    messagebox.showerror("Validation Error", f"Parameter '{var_name}' harus berupa bilangan bulat (integer).")
                    return None
            elif data_type == "float":
                try:
                    float(raw)
                except ValueError:
                    messagebox.showerror("Validation Error", f"Parameter '{var_name}' harus berupa angka (float).")
                    return None
            result[var_name] = raw
        return result

    def _on_ok(self):
        new_values = self._collect_values()
        if new_values is None:
            return

        save_env_file(self.env_path, new_values)
        messagebox.showinfo("Sukses", f"Pengaturan berhasil disimpan ke '{self.env_path}'!\nBot siap dijalankan dengan konfigurasi baru.")
        self.root.destroy()

    def _on_cancel(self):
        self.root.destroy()

    def _on_reset(self):
        if messagebox.askyesno("Reset Pengaturan", "Kembalikan seluruh parameter ke nilai default bawaan (.env.example)?"):
            defaults = load_env_file(".env.example")
            for var_name, (str_var, _, _) in self.param_widgets.items():
                if var_name in defaults:
                    str_var.set(defaults[var_name])

    def _on_load(self):
        file_selected = filedialog.askopenfilename(
            title="Pilih File Konfigurasi / Preset (.set atau .env)",
            filetypes=[("Config Files", "*.env *.set *.ini"), ("All Files", "*.*")]
        )
        if file_selected:
            loaded = load_env_file(file_selected)
            for var_name, (str_var, _, _) in self.param_widgets.items():
                if var_name in loaded:
                    str_var.set(loaded[var_name])
            messagebox.showinfo("Preset Dimuat", f"Preset dari '{os.path.basename(file_selected)}' berhasil diterapkan ke tabel.")

    def _on_save(self):
        new_values = self._collect_values()
        if new_values is None:
            return
        file_dest = filedialog.asksaveasfilename(
            title="Simpan Preset Konfigurasi (.set)",
            defaultextension=".set",
            filetypes=[("Preset Set Files", "*.set"), ("Env Files", "*.env"), ("All Files", "*.*")]
        )
        if file_dest:
            save_env_file(file_dest, new_values)
            messagebox.showinfo("Preset Disimpan", f"Preset berhasil disimpan ke '{os.path.basename(file_dest)}'.")

    def run(self):
        self.root.mainloop()


def launch_settings_gui(env_path: str = ".env"):
    """Fungsi pembuka GUI Settings MT5 Style."""
    app = MT5SettingsWindow(env_path=env_path)
    app.run()


if __name__ == "__main__":
    launch_settings_gui()
