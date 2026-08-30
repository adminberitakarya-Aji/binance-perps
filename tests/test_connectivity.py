import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import Config
from src.client import BinanceFuturesClient

try:
    config = Config.from_env()
    client = BinanceFuturesClient(config)
except Exception as e:
    print(f"[ERROR] Gagal memuat konfigurasi dari .env: {e}")
    sys.exit(1)

mode = "TESTNET" if config.use_testnet else "MAINNET"
print(f"\n=======================================================")
print(f"   TEST KONEKSI BINANCE USD(S)-M FUTURES ({mode})")
print(f"=======================================================")
print(f"Endpoint API : {config.api_url}")
print(f"Simbol       : {config.symbol}")
print(f"API Key      : {config.api_key[:6]}...{config.api_key[-4:] if len(config.api_key) > 10 else ''}")
print("-" * 55)

# 1. Market Data Publik
try:
    mid = client.get_mid_price(config.symbol)
    print(f"[1] Market Data Publik   : OK (Mid Price = ${mid:,.2f})")
except Exception as e:
    print(f"[1] Market Data Publik   : GAGAL ({e})")

# 2. Exchange Info & Filters
try:
    filters = client.get_symbol_filters(config.symbol)
    tick = filters.get("tickSize")
    step = filters.get("stepSize")
    notional = filters.get("minNotional")
    print(f"[2] Exchange Filters     : OK (tickSize={tick}, stepSize={step}, minNotional=${notional})")
except Exception as e:
    print(f"[2] Exchange Filters     : GAGAL ({e})")

# 3. Signed API & Saldo Akun
try:
    state = client.get_account_state()
    if isinstance(state, dict) and int(state.get("code", 0)) < 0:
        print(f"[3] Autentikasi API Key  : DITOLAK (code={state.get('code')}: {state.get('msg')})")
    else:
        margin_bal = float(state.get("totalMarginBalance", 0) or 0)
        wallet_bal = float(state.get("totalWalletBalance", 0) or 0)
        avail_bal = float(state.get("availableBalance", 0) or 0)
        can_trade = state.get("canTrade", True)
        print(f"[3] Autentikasi API Key  : SUKSES (canTrade={can_trade})")
        print(f"    - Total Margin Balance  : ${margin_bal:,.2f} USDT")
        print(f"    - Total Wallet Balance  : ${wallet_bal:,.2f} USDT")
        print(f"    - Available Balance     : ${avail_bal:,.2f} USDT")
except Exception as e:
    print(f"[3] Autentikasi API Key  : GAGAL ({e})")

# 4. Open Positions & Triggers
try:
    pos = client.get_position(config.symbol)
    if pos:
        print(f"[4] Status Posisi {config.symbol} : TERBUKA ({pos['side']} {pos['szi']} @ ${pos['entryPx']:,.2f})")
    else:
        print(f"[4] Status Posisi {config.symbol} : BERSIH (0 posisi aktif)")
except Exception as e:
    print(f"[4] Status Posisi        : GAGAL ({e})")

# 5. Open Trigger Orders
try:
    triggers = client.get_trigger_orders(config.symbol)
    print(f"[5] Conditional Orders   : {len(triggers)} trigger order aktif terdeteksi")
except Exception as e:
    print(f"[5] Conditional Orders   : GAGAL ({e})")

print("=" * 55)
print("Koneksi siap untuk dijalankan!\n")
