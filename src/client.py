"""
Wrapper REST API Binance USDⓈ-M Futures (fapi).
Menyatukan query data publik (klines, ticker, exchangeInfo) dan eksekusi order
(signing HMAC-SHA256, SL/TP conditional orders, account/positions) dalam satu
titik akses mandiri tanpa dependensi SDK pihak ketiga yang berat.
"""

import hashlib
import hmac
import math
import time
from urllib.parse import urlencode

import requests

from src.config import Config
from src.utils.logger import get_logger

log = get_logger("client")


def _get_precision(val: float) -> int:
    """Hitung jumlah desimal dari step/tick size (mis. 0.001 -> 3, 0.1 -> 1, 1.0 -> 0)."""
    s = f"{val:.10f}".rstrip("0")
    if "." in s:
        return len(s.split(".")[1])
    return 0


def round_px_binance(px: float, tick_size: float) -> float:
    """Bulatkan harga ke kelipatan tickSize terdekat."""
    if tick_size <= 0:
        return px
    decimals = _get_precision(tick_size)
    steps = round(px / tick_size)
    rounded = steps * tick_size
    return round(rounded, decimals)


def round_sz_binance(sz: float, step_size: float) -> float:
    """Bulatkan ukuran (quantity) ke kelipatan stepSize terdekat."""
    if step_size <= 0:
        return sz
    decimals = _get_precision(step_size)
    steps = math.floor(sz / step_size + 1e-9)
    rounded = steps * step_size
    return round(rounded, decimals)


class OrderRejectedError(RuntimeError):
    """Exchange MENOLAK order (error code dari Binance)."""


class ProtectionError(RuntimeError):
    """Entry terisi tapi SL/TP gagal dipasang -> posisi SUDAH ditutup paksa."""


def validate_order_result(result, context: str = "order"):
    """Validasi respons order Binance; raise OrderRejectedError kalau ditolak."""
    if not isinstance(result, dict):
        raise OrderRejectedError(f"{context}: respons tidak dikenal: {result!r}")
    if "code" in result and int(result["code"]) < 0:
        msg = result.get("msg", "Unknown error")
        raise OrderRejectedError(f"{context} ditolak (code={result['code']}): {msg}")
    if result.get("status") in ("REJECTED", "EXPIRED"):
        raise OrderRejectedError(f"{context} ditolak dengan status: {result.get('status')}")
    return result


class BinanceFuturesClient:
    def __init__(self, config: Config, session: requests.Session | None = None):
        self.config = config
        self.base_url = config.api_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": config.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "BinanceFuturesAgent/1.0",
        })
        self._exchange_info_cache: dict = {}
        self._symbol_filters: dict = {}

    # ------------------------------------------------------------------
    # HTTP & Signature Helpers
    # ------------------------------------------------------------------
    def _sign(self, params: dict) -> str:
        query_string = urlencode(params)
        signature = hmac.new(
            self.config.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return signature

    def _request(self, method: str, path: str, params: dict | None = None, signed: bool = False) -> dict | list:
        url = f"{self.base_url}{path}"
        payload = dict(params or {})

        if signed:
            payload["timestamp"] = int(time.time() * 1000)
            payload["recvWindow"] = 5000
            payload["signature"] = self._sign(payload)

        try:
            if method.upper() == "GET":
                resp = self.session.get(url, params=payload, timeout=15)
            elif method.upper() == "POST":
                resp = self.session.post(url, data=payload, timeout=15)
            elif method.upper() == "DELETE":
                resp = self.session.delete(url, params=payload, timeout=15)
            elif method.upper() == "PUT":
                resp = self.session.put(url, data=payload, timeout=15)
            else:
                raise ValueError(f"Metode HTTP tidak didukung: {method}")

            data = resp.json()
            if isinstance(data, dict) and "code" in data and int(data["code"]) < 0:
                log.warning("Binance API error [%s %s]: %s", method, path, data)
            return data
        except Exception as e:
            log.error("HTTP request gagal [%s %s]: %s", method, path, e)
            raise

    # ------------------------------------------------------------------
    # Exchange Info & Precision Filtering
    # ------------------------------------------------------------------
    def load_exchange_info(self, symbol: str | None = None) -> dict:
        """Fetch exchangeInfo dan simpan cache filter (tickSize, stepSize, minNotional)."""
        data = self._request("GET", "/fapi/v1/exchangeInfo")
        if isinstance(data, dict) and "symbols" in data:
            self._exchange_info_cache = data
            for s in data["symbols"]:
                sym = s.get("symbol")
                filters = {}
                for f in s.get("filters", []):
                    f_type = f.get("filterType")
                    if f_type == "PRICE_FILTER":
                        filters["tickSize"] = float(f.get("tickSize", 0.1))
                    elif f_type == "LOT_SIZE":
                        filters["stepSize"] = float(f.get("stepSize", 0.001))
                        filters["minQty"] = float(f.get("minQty", 0.001))
                    elif f_type in ("MIN_NOTIONAL", "NOTIONAL"):
                        filters["minNotional"] = float(f.get("notional", f.get("minNotional", 5.0)))
                self._symbol_filters[sym] = filters
        return self._symbol_filters.get(symbol or self.config.symbol, {})

    def get_symbol_filters(self, symbol: str) -> dict:
        if symbol not in self._symbol_filters:
            self.load_exchange_info(symbol)
        return self._symbol_filters.get(symbol, {"tickSize": 0.1, "stepSize": 0.001, "minNotional": 5.0})

    def round_price(self, symbol: str, price: float) -> float:
        filters = self.get_symbol_filters(symbol)
        tick_size = filters.get("tickSize", 0.1)
        return round_px_binance(price, tick_size)

    def round_size(self, symbol: str, size: float) -> float:
        filters = self.get_symbol_filters(symbol)
        step_size = filters.get("stepSize", 0.001)
        return round_sz_binance(size, step_size)

    # ------------------------------------------------------------------
    # Market Data
    # ------------------------------------------------------------------
    def get_mid_price(self, symbol: str) -> float:
        data = self._request("GET", "/fapi/v1/ticker/bookTicker", {"symbol": symbol})
        if isinstance(data, dict) and "bidPrice" in data and "askPrice" in data:
            bid = float(data["bidPrice"])
            ask = float(data["askPrice"])
            return (bid + ask) / 2.0
        # fallback to price ticker
        pdata = self._request("GET", "/fapi/v1/ticker/price", {"symbol": symbol})
        return float(pdata["price"])

    def get_candles(self, symbol: str, interval: str, start_ms: int, end_ms: int, limit: int = 1500) -> list:
        """interval: '1m', '5m', '15m', '1h', '4h', '1d'.
        Konversi ke format dict {t, T, o, h, l, c, v, n} yang konsisten.
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": limit,
        }
        rows = self._request("GET", "/fapi/v1/klines", params)
        if not isinstance(rows, list):
            return []

        out = []
        for r in rows:
            out.append({
                "t": int(r[0]),
                "T": int(r[6]),
                "o": float(r[1]),
                "h": float(r[2]),
                "l": float(r[3]),
                "c": float(r[4]),
                "v": float(r[5]),
                "n": int(r[8]) if len(r) > 8 else 0,
            })
        return out

    def get_funding_rate(self, symbol: str) -> float | None:
        """Funding rate terakhir (rate 8 jam) dari Binance."""
        try:
            rows = self._request("GET", "/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1})
            if isinstance(rows, list) and rows:
                return float(rows[-1]["fundingRate"])
            return None
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Account & Positions
    # ------------------------------------------------------------------
    def get_account_state(self) -> dict:
        """State akun Binance Futures (v2/account)."""
        data = self._request("GET", "/fapi/v2/account", signed=True)
        return data if isinstance(data, dict) else {}

    def get_open_positions(self) -> list:
        """Daftar seluruh posisi akun dari positionRisk."""
        data = self._request("GET", "/fapi/v2/positionRisk", signed=True)
        return data if isinstance(data, list) else []

    def get_position(self, symbol: str) -> dict | None:
        """Posisi terbuka satu simbol.
        Return {"szi": float (+long/-short), "entryPx": float, "side": "B"/"S"} atau None.
        """
        positions = self.get_open_positions()
        for p in positions:
            if p.get("symbol") == symbol:
                szi = float(p.get("positionAmt") or 0)
                if abs(szi) < 1e-9:
                    return None
                return {
                    "szi": szi,
                    "entryPx": float(p.get("entryPrice") or 0),
                    "side": "B" if szi > 0 else "S",
                }
        return None

    def get_position_retry(self, symbol: str, retries: int = 3, delay_s: float = 1.0) -> dict | None:
        """Posisi kadang belum terlihat sesaat setelah fill; retry ringan."""
        for _ in range(retries):
            pos = self.get_position(symbol)
            if pos is not None:
                return pos
            time.sleep(delay_s)
        return self.get_position(symbol)

    # ------------------------------------------------------------------
    # Orders & Execution
    def place_market_order_raw(self, symbol: str, is_buy: bool, size: float) -> dict:
        """Kirim market order murni tanpa proteksi SL/TP otomatis (dipakai DCA layer)."""
        side = "BUY" if is_buy else "SELL"
        qty = self.round_size(symbol, size)
        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
        }
        return validate_order_result(
            self._request("POST", "/fapi/v1/order", params, signed=True),
            f"market order raw {symbol}",
        )

    def place_market_order(
        self,
        symbol: str,
        is_buy: bool,
        size: float,
        sl: float | None = None,
        tp: float | None = None,
    ) -> dict:
        """Market order untuk entry baru + pasang proteksi SL/TP reduce-only."""
        if abs(size) < 1e-9:
            return self.market_close_position(symbol)

        side = "BUY" if is_buy else "SELL"
        qty = self.round_size(symbol, size)

        params = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
        }
        res = validate_order_result(
            self._request("POST", "/fapi/v1/order", params, signed=True),
            f"entry {symbol}",
        )

        if sl is None and tp is None:
            return res

        pos = self.get_position_retry(symbol)
        if pos is None:
            raise ProtectionError(
                f"posisi {symbol} tidak terdeteksi setelah entry -- SL/TP gagal dipasang"
            )

        close_is_buy = pos["side"] == "S"
        try:
            self.place_tpsl_pair(symbol, close_is_buy, abs(pos["szi"]), sl, tp)
        except Exception as e:
            log.error("GAGAL pasang SL/TP (%s) -> tutup paksa posisi %s", e, symbol)
            try:
                self.cancel_all_trigger_orders(symbol)
                self.market_close_position(symbol)
            except Exception as e2:
                log.critical("gagal tutup paksa %s: %s -- PERIKSA MANUAL!", symbol, e2)
            raise ProtectionError(f"SL/TP gagal dipasang ({e}) -> posisi {symbol} ditutup paksa") from e

        return res

    def place_tpsl_pair(
        self,
        symbol: str,
        close_is_buy: bool,
        size: float,
        sl: float,
        tp: float | None = None,
    ) -> list:
        """Pasang STOP_MARKET (SL) dan opsional TAKE_PROFIT_MARKET (TP) reduce-only.

        Menggunakan endpoint resmi Binance Futures Algo Order (/fapi/v1/algoOrder)
        karena order tipe conditional (STOP_MARKET / TAKE_PROFIT_MARKET) telah
        dimigrasikan sepenuhnya ke Algo Service Binance.
        """
        close_side = "BUY" if close_is_buy else "SELL"
        qty = self.round_size(symbol, size)
        results = []

        # 1. Stop Loss (STOP_MARKET) via Algo Order API
        sl_px = self.round_price(symbol, sl)
        sl_params = {
            "symbol": symbol,
            "side": close_side,
            "type": "STOP_MARKET",
            "algoType": "CONDITIONAL",
            "triggerPrice": sl_px,
            "quantity": qty,
            "reduceOnly": "true",
            "workingType": "MARK_PRICE",
        }
        sl_res = validate_order_result(
            self._request("POST", "/fapi/v1/algoOrder", sl_params, signed=True),
            f"SL {symbol}",
        )
        results.append(sl_res)
        log.info("SL dipasang %s @ %.2f (algoId=%s)", symbol, sl_px, sl_res.get("algoId"))

        # 2. Take Profit (TAKE_PROFIT_MARKET) via Algo Order API
        if tp is not None and tp > 0:
            tp_px = self.round_price(symbol, tp)
            tp_params = {
                "symbol": symbol,
                "side": close_side,
                "type": "TAKE_PROFIT_MARKET",
                "algoType": "CONDITIONAL",
                "triggerPrice": tp_px,
                "quantity": qty,
                "reduceOnly": "true",
                "workingType": "MARK_PRICE",
            }
            tp_res = validate_order_result(
                self._request("POST", "/fapi/v1/algoOrder", tp_params, signed=True),
                f"TP {symbol}",
            )
            results.append(tp_res)
            log.info("TP dipasang %s @ %.2f (algoId=%s)", symbol, tp_px, tp_res.get("algoId"))

        return results

    def get_trigger_orders(self, symbol: str) -> list:
        """Conditional open orders (STOP_MARKET, TAKE_PROFIT_MARKET) satu simbol.
        Mendukung endpoint /fapi/v1/openAlgoOrders (Algo API baru) dan fallback /fapi/v1/openOrders.
        Menghasilkan list dict dengan key oid, triggerCondition, stopPrice, is_algo agar kompatibel.
        """
        triggers = []

        # 1. Query dari Algo Orders API (utama)
        try:
            algo_orders = self._request("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol}, signed=True)
            if isinstance(algo_orders, list):
                for o in algo_orders:
                    o_type = o.get("orderType", "") or o.get("type", "")
                    is_sl = "STOP" in o_type
                    triggers.append({
                        "oid": o.get("algoId"),
                        "orderId": o.get("algoId"),
                        "algoId": o.get("algoId"),
                        "coin": symbol,
                        "symbol": symbol,
                        "type": o_type,
                        "side": o.get("side"),
                        "stopPrice": float(o.get("triggerPrice") or o.get("stopPrice") or 0),
                        "triggerCondition": "sl" if is_sl else "tp",
                        "origQty": float(o.get("quantity") or o.get("origQty") or 0),
                        "is_algo": True,
                    })
        except Exception as e:
            log.debug("Gagal query openAlgoOrders %s: %s", symbol, e)

        # 2. Fallback query dari openOrders biasa jika ada
        try:
            orders = self._request("GET", "/fapi/v1/openOrders", {"symbol": symbol}, signed=True)
            if isinstance(orders, list):
                for o in orders:
                    o_type = o.get("type", "")
                    if o_type in ("STOP_MARKET", "STOP", "TAKE_PROFIT_MARKET", "TAKE_PROFIT"):
                        is_sl = "STOP" in o_type
                        triggers.append({
                            "oid": o.get("orderId"),
                            "orderId": o.get("orderId"),
                            "coin": symbol,
                            "symbol": symbol,
                            "type": o_type,
                            "side": o.get("side"),
                            "stopPrice": float(o.get("stopPrice") or 0),
                            "triggerCondition": "sl" if is_sl else "tp",
                            "origQty": float(o.get("origQty") or 0),
                            "is_algo": False,
                        })
        except Exception as e:
            log.debug("Gagal query openOrders %s: %s", symbol, e)

        return triggers

    def cancel_order(self, symbol: str, order_id: int | str) -> dict:
        """Cancel order biasa atau algo order."""
        # Coba cancel via Algo API terlebih dahulu
        try:
            res = self._request("DELETE", "/fapi/v1/algoOrder", {"symbol": symbol, "algoId": order_id}, signed=True)
            if isinstance(res, dict) and res.get("code") in (200, "200", None) and res.get("msg") != "Unknown error":
                return res
        except Exception:
            pass

        # Fallback cancel order biasa
        params = {"symbol": symbol, "orderId": order_id}
        return self._request("DELETE", "/fapi/v1/order", params, signed=True)

    def cancel_all_trigger_orders(self, symbol: str) -> int:
        """Cancel semua trigger order aktif untuk satu simbol. Return jumlah yang dibatalkan."""
        triggers = self.get_trigger_orders(symbol)
        n = 0
        for o in triggers:
            try:
                self.cancel_order(symbol, o["oid"])
                n += 1
            except Exception as e:
                log.warning("gagal cancel trigger oid=%s: %s", o.get("oid"), e)
        return n

    def modify_sl_trigger(
        self,
        symbol: str,
        oid: int | str,
        close_is_buy: bool,
        size: float,
        new_sl: float,
    ) -> dict:
        """Geser trigger SL: pasang SL baru via Algo API, lalu batalkan SL lama."""
        new_sl_px = self.round_price(symbol, new_sl)
        close_side = "BUY" if close_is_buy else "SELL"
        qty = self.round_size(symbol, size)

        # Pasang SL baru via Algo Order API
        sl_params = {
            "symbol": symbol,
            "side": close_side,
            "type": "STOP_MARKET",
            "algoType": "CONDITIONAL",
            "triggerPrice": new_sl_px,
            "quantity": qty,
            "reduceOnly": "true",
            "workingType": "MARK_PRICE",
        }
        new_res = validate_order_result(
            self._request("POST", "/fapi/v1/algoOrder", sl_params, signed=True),
            f"new SL {symbol}",
        )

        # Cancel SL lama
        try:
            self.cancel_order(symbol, oid)
        except Exception as e:
            log.warning("[%s] SL baru terpasang tapi gagal cancel SL lama oid=%s: %s", symbol, oid, e)

        return new_res

    def market_close_position(self, symbol: str) -> dict:
        """Tutup posisi market segera (reduce-only)."""
        pos = self.get_position(symbol)
        if pos is None:
            return {"status": "ok", "msg": "no open position"}

        close_side = "SELL" if pos["side"] == "B" else "BUY"
        qty = self.round_size(symbol, abs(pos["szi"]))

        params = {
            "symbol": symbol,
            "side": close_side,
            "type": "MARKET",
            "quantity": qty,
            "reduceOnly": "true",
        }
        return validate_order_result(
            self._request("POST", "/fapi/v1/order", params, signed=True),
            f"market_close {symbol}",
        )


if __name__ == "__main__":
    # Smoke test manual
    config = Config.from_env()
    client = BinanceFuturesClient(config)
    print(f"Terhubung ke Binance Futures ({'TESTNET' if config.use_testnet else 'MAINNET'})")
    mid = client.get_mid_price(config.symbol)
    print(f"Mid price {config.symbol}: {mid}")
    filters = client.get_symbol_filters(config.symbol)
    print(f"Filters {config.symbol}: {filters}")
