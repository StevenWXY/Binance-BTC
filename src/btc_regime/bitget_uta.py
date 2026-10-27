"""Bitget UTA v3 REST transport with narrowly scoped public funding v2 reads."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True, repr=False)
class Credentials:
    key: str
    secret: str
    passphrase: str

    def __post_init__(self):
        if not all((self.key, self.secret, self.passphrase)):
            raise ValueError("API key, secret and passphrase are all required")


class BitgetError(RuntimeError):
    pass


class UnknownWriteResult(BitgetError):
    """A write may have succeeded; reconcile by clientOid before further action."""


def sign(secret: str, timestamp: str, method: str, path_and_query: str, body: str = "") -> str:
    message = timestamp + method.upper() + path_and_query + body
    digest = hmac.new(secret.encode(), message.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class UTAClient:
    BASE = "https://api.bitget.com"
    PUBLIC_V2_PREFIX = "/api/v2/mix/market/"

    def __init__(self, credentials=None, *, allow_writes=False, demo=False, opener=urlopen,
                 clock=time.time, sleep=time.sleep):
        self.credentials = credentials
        self.allow_writes = allow_writes
        self.demo = demo
        self.opener = opener
        self.clock = clock
        self.sleep = sleep

    def request(self, method, path, *, params=None, body=None, private=True):
        method = method.upper()
        if method not in {"GET", "POST"}:
            raise ValueError("Unsupported HTTP method")
        if not (path.startswith("/api/v3/") or (not private and path.startswith(self.PUBLIC_V2_PREFIX))):
            raise ValueError("Path is outside the supported Bitget API surface")
        if private and not path.startswith("/api/v3/"):
            raise ValueError("Private calls must use the UTA v3 API")
        if method != "GET" and not self.allow_writes:
            raise PermissionError("Writes disabled; this client is read-only")
        if method == "GET" and body is not None:
            raise ValueError("GET body is not supported")
        if private and self.credentials is None:
            raise ValueError("Credentials are required for private requests")
        query = urlencode(sorted((str(k), str(v)) for k, v in (params or {}).items()))
        target = path + ("?" + query if query else "")
        payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body is not None else ""
        for attempt in range(3 if method == "GET" else 1):
            headers = {"Content-Type": "application/json", "locale": "en-US"}
            if self.demo:
                headers["paptrading"] = "1"
            if private:
                c = self.credentials
                timestamp = str(int(self.clock() * 1000))
                headers.update({"ACCESS-KEY": c.key, "ACCESS-PASSPHRASE": c.passphrase,
                                "ACCESS-TIMESTAMP": timestamp,
                                "ACCESS-SIGN": sign(c.secret, timestamp, method, target, payload)})
            req = Request(self.BASE + target, data=payload.encode() if method == "POST" else None,
                          headers=headers, method=method)
            try:
                with self.opener(req, timeout=20) as response:
                    result = json.loads(response.read())
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                transient = not isinstance(exc, HTTPError) or exc.code in {429, 500, 502, 503, 504}
                if method == "GET" and transient and attempt < 2:
                    self.sleep(2 ** attempt)
                    continue
                if method != "GET":
                    raise UnknownWriteResult("Write response uncertain; query by clientOid before retrying") from None
                if isinstance(exc, HTTPError):
                    try:
                        detail = exc.read(512).decode("utf-8", "replace").replace("\n", " ")
                    except OSError:
                        detail = ""
                    message = f"GET failed (HTTP {exc.code}): {path}"
                    if detail:
                        message += ": " + detail
                    raise BitgetError(message[:800]) from None
                raise BitgetError("GET failed: " + path) from None
            if not isinstance(result, dict) or "code" not in result:
                if method != "GET":
                    raise UnknownWriteResult("Invalid write response; reconcile before retrying")
                raise BitgetError("Invalid response envelope")
            code = str(result["code"])
            if code != "00000":
                if method != "GET" and code in {"40010", "40725", "45001"}:
                    raise UnknownWriteResult("Exchange returned ambiguous code " + code)
                raise BitgetError("Bitget error " + code + " at " + path)
            return result.get("data")

    def instruments(self):
        return self.request("GET", "/api/v3/market/instruments", private=False,
                            params={"category": "USDT-FUTURES", "symbol": "BTCUSDT"})

    def candles(self, start_ms, end_ms, *, interval="1H", kind="market"):
        return self.request("GET", "/api/v3/market/history-candles", private=False,
                            params={"category": "USDT-FUTURES", "symbol": "BTCUSDT",
                                    "interval": interval, "type": kind, "limit": 100,
                                    "startTime": start_ms, "endTime": end_ms})

    def funding_history(self, page_no):
        return self.request("GET", self.PUBLIC_V2_PREFIX + "history-fund-rate", private=False,
                            params={"symbol": "BTCUSDT", "productType": "USDT-FUTURES",
                                    "pageSize": 100, "pageNo": page_no})

    def settings(self):
        return self.request("GET", "/api/v3/account/settings")

    def assets(self):
        return self.request("GET", "/api/v3/account/assets")

    def positions(self):
        return self.request("GET", "/api/v3/position/current-position",
                            params={"category": "USDT-FUTURES", "symbol": "BTCUSDT"})

    def fees(self):
        return self.request("GET", "/api/v3/account/fee-rate",
                            params={"category": "USDT-FUTURES", "symbol": "BTCUSDT"})

    def orderbook(self):
        return self.request("GET", "/api/v3/market/orderbook", private=False,
                            params={"category": "USDT-FUTURES", "symbol": "BTCUSDT", "limit": 5})

    def ticker(self):
        return self.request("GET", "/api/v3/market/tickers", private=False,
                            params={"category": "USDT-FUTURES", "symbol": "BTCUSDT"})

    def server_time(self):
        return self.request("GET", "/api/v3/market/time", private=False)

    def open_orders(self):
        return self.request("GET", "/api/v3/trade/unfilled-orders",
                            params={"category": "USDT-FUTURES", "symbol": "BTCUSDT"})

    def strategy_orders(self):
        return self.request("GET", "/api/v3/trade/unfilled-strategy-orders",
                            params={"category": "USDT-FUTURES", "symbol": "BTCUSDT"})

    def order_info(self, client_oid):
        return self.request("GET", "/api/v3/trade/order-info", params={"clientOid": client_oid})

    def set_leverage(self, pos_side):
        return self.request("POST", "/api/v3/account/set-leverage", body={
            "category": "USDT-FUTURES", "symbol": "BTCUSDT", "leverage": "7",
            "posSide": pos_side, "marginMode": "isolated"})

    def place_order(self, order):
        return self.request("POST", "/api/v3/trade/place-order", body=order)

    def cancel_order(self, *, order_id=None, client_oid=None, strategy=False):
        path = "/api/v3/trade/cancel-strategy-order" if strategy else "/api/v3/trade/cancel-order"
        body = {"orderId": order_id} if order_id else {"clientOid": client_oid}
        if not strategy:
            body["category"] = "USDT-FUTURES"
            body["symbol"] = "BTCUSDT"
        return self.request("POST", path, body=body)

    def modify_strategy_order(self, *, client_oid, qty, stop, take):
        body = {"clientOid": client_oid, "qty": qty,
                "slTriggerBy": "mark", "slOrderType": "market"}
        if stop is not None:
            body["stopLoss"] = stop
        if take is not None:
            body.update({"takeProfit": take, "tpTriggerBy": "mark", "tpOrderType": "market"})
        return self.request("POST", "/api/v3/trade/modify-strategy-order", body=body)

    def place_protection(self, *, side, stop, take, client_oid):
        body = {"category": "USDT-FUTURES", "symbol": "BTCUSDT", "type": "tpsl",
                "tpslMode": "full", "side": side, "reduceOnly": "yes",
                "marginMode": "isolated", "clientOid": client_oid,
                "slTriggerBy": "mark", "slOrderType": "market"}
        if stop is not None:
            body["stopLoss"] = stop
        if take is not None:
            body["takeProfit"] = take
            body["tpTriggerBy"] = "mark"
            body["tpOrderType"] = "market"
        return self.request("POST", "/api/v3/trade/place-strategy-order", body=body)
