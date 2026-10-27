import base64
import hashlib
import hmac
import json
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from btc_regime.bitget_uta import BitgetError, Credentials, UTAClient, UnknownWriteResult, sign


CREDS = Credentials("test-key", "test-secret", "test-passphrase")


class Response:
    def __init__(self, result): self.result = result
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.result).encode()


def test_signature_matches_official_get_preimage():
    preimage = b"16273667805456GET/api/v3/account/fee-rate?category=SPOT&symbol=BTCUSDT"
    expected = base64.b64encode(hmac.new(b"test-secret", preimage, hashlib.sha256).digest()).decode()
    assert sign("test-secret", "16273667805456", "get",
                "/api/v3/account/fee-rate?category=SPOT&symbol=BTCUSDT") == expected


def test_signed_query_matches_bytes_sent_and_keys_are_sorted():
    seen = []
    def opener(req, **kwargs):
        seen.append(req)
        return Response({"code": "00000", "data": {"ok": True}})
    client = UTAClient(CREDS, opener=opener, clock=lambda: 1000)
    assert client.request("GET", "/api/v3/account/fee-rate",
                          params={"symbol": "BTCUSDT", "category": "USDT-FUTURES"}) == {"ok": True}
    req = seen[0]
    assert req.full_url.endswith("?category=USDT-FUTURES&symbol=BTCUSDT")
    assert req.get_header("Access-sign") == sign("test-secret", "1000000", "GET",
        "/api/v3/account/fee-rate?category=USDT-FUTURES&symbol=BTCUSDT")


def test_writes_default_to_blocked():
    with pytest.raises(PermissionError):
        UTAClient(CREDS).request("POST", "/api/v3/trade/place-order", body={})


def test_get_retries_but_write_timeout_never_retries():
    seen = []
    def broken(req, **kwargs):
        seen.append(req)
        raise URLError("temporary")
    client = UTAClient(CREDS, opener=broken, sleep=lambda _: None, allow_writes=True)
    with pytest.raises(UnknownWriteResult):
        client.request("POST", "/api/v3/trade/place-order", body={"clientOid": "test"})
    assert len(seen) == 1
    seen.clear()
    with pytest.raises(RuntimeError):
        client.settings()
    assert len(seen) == 3


@pytest.mark.parametrize("code", ["40010", "40725", "45001"])
def test_ambiguous_exchange_order_result_requires_reconciliation(code):
    client = UTAClient(CREDS, allow_writes=True,
                       opener=lambda *a, **kw: Response({"code": code}))
    with pytest.raises(UnknownWriteResult):
        client.request("POST", "/api/v3/trade/place-order", body={"clientOid": "test"})


def test_demo_header_and_public_request_has_no_api_key():
    seen = []
    def opener(req, **kwargs):
        seen.append(req)
        return Response({"code": "00000", "data": []})
    UTAClient(demo=True, opener=opener).instruments()
    assert seen[0].get_header("Paptrading") == "1"
    assert seen[0].get_header("Access-key") is None


def test_history_candles_uses_uta_safe_limit():
    seen = []
    def opener(req, **kwargs):
        seen.append(req)
        return Response({"code": "00000", "data": []})
    UTAClient(opener=opener).candles(1, 2)
    assert "limit=100" in seen[0].full_url


def test_get_error_includes_http_status_and_exchange_detail_without_credentials():
    error = HTTPError("https://api.bitget.com/api/v3/public", 400, "Bad Request", {},
                      BytesIO(b'{"code":"40020","msg":"Parameter limit error"}'))
    client = UTAClient(opener=lambda *a, **kw: (_ for _ in ()).throw(error))
    with pytest.raises(BitgetError, match="HTTP 400.*40020.*Parameter limit error"):
        client.request("GET", "/api/v3/market/history-candles", private=False)


def test_order_info_includes_required_product_and_symbol_parameters():
    seen = []
    def opener(req, **kwargs):
        seen.append(req)
        return Response({"code": "00000", "data": {"orderStatus": "live"}})
    result = UTAClient(CREDS, opener=opener).order_info("v453-test")
    assert result["orderStatus"] == "live"
    assert seen[0].full_url.endswith(
        "/api/v3/trade/order-info?category=USDT-FUTURES&clientOid=v453-test&symbol=BTCUSDT")
