from decimal import Decimal
import base64
import hashlib
import hmac
import json

import numpy as np
import pandas as pd
import pytest

from btc_regime.bitget_uta import Credentials, UTAClient, UnknownWriteResult, sign
from btc_regime_v453.v452 import V452Params, generate_v452_signals
from deploy import bitget_v453_runner as runner


class Response:
    def __init__(self, result): self.result = result
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self): return json.dumps(self.result).encode()


def test_uta_signing_matches_official_get_preimage():
    message = b"16273667805456GET/api/v3/account/fee-rate?category=SPOT&symbol=BTCUSDT"
    expected = base64.b64encode(hmac.new(b"secret", message, hashlib.sha256).digest()).decode()
    assert sign("secret", "16273667805456", "GET",
                "/api/v3/account/fee-rate?category=SPOT&symbol=BTCUSDT") == expected


def test_signed_query_order_and_private_headers_are_deterministic():
    seen = []
    def opener(req, **kwargs):
        seen.append(req)
        return Response({"code": "00000", "data": []})
    client = UTAClient(Credentials("key", "secret", "pass"), opener=opener, clock=lambda: 1000)
    client.request("GET", "/api/v3/account/fee-rate",
                   params={"symbol": "BTCUSDT", "category": "USDT-FUTURES"})
    assert seen[0].full_url.endswith("?category=USDT-FUTURES&symbol=BTCUSDT")
    assert seen[0].get_header("Access-key") == "key"
    assert seen[0].get_header("Access-sign") == sign("secret", "1000000", "GET",
        "/api/v3/account/fee-rate?category=USDT-FUTURES&symbol=BTCUSDT")


def test_write_is_disabled_by_default_and_never_retried_on_ambiguous_result():
    creds = Credentials("key", "secret", "pass")
    with pytest.raises(PermissionError):
        UTAClient(creds).place_order({"clientOid": "x"})
    calls = []
    def fail(req, **kwargs):
        calls.append(req)
        raise TimeoutError("network timeout")
    client = UTAClient(creds, allow_writes=True, opener=fail)
    with pytest.raises(UnknownWriteResult):
        client.place_order({"clientOid": "x"})
    assert len(calls) == 1


def test_funding_v2_path_is_public_only():
    calls = []
    def opener(req, **kwargs):
        calls.append(req)
        return Response({"code": "00000", "data": []})
    client = UTAClient(opener=opener)
    assert client.funding_history(1) == []
    assert "/api/v2/mix/market/history-fund-rate" in calls[0].full_url
    with pytest.raises(ValueError):
        client.request("GET", "/api/v2/mix/market/history-fund-rate", private=True)


def test_strategy_orders_query_does_not_hide_non_tpsl_protective_orders():
    seen = []
    def opener(req, **kwargs):
        seen.append(req)
        return Response({"code": "00000", "data": []})
    UTAClient(Credentials("key", "secret", "pass"), opener=opener).strategy_orders()
    assert "category=USDT-FUTURES" in seen[0].full_url
    assert "symbol=BTCUSDT" in seen[0].full_url
    assert "type=" not in seen[0].full_url


def test_position_quantity_requires_isolated_seven_x():
    positions = {"list": [
        {"symbol": "BTCUSDT", "category": "USDT-FUTURES", "total": "0.25",
         "posSide": "long", "marginMode": "isolated", "leverage": "7"},
        {"symbol": "BTCUSDT", "category": "USDT-FUTURES", "total": "0.05",
         "posSide": "short", "marginMode": "isolated", "leverage": "7"},
    ]}
    assert runner.current_qty(positions) == Decimal("0.20")
    positions["list"][0]["marginMode"] = "crossed"
    with pytest.raises(RuntimeError, match="not isolated"):
        runner.current_qty(positions)


def test_settings_entry_prefers_isolated_seven_x_when_uta_returns_duplicates():
    settings = {"symbolConfigList": [
        {"category": "USDT-FUTURES", "symbol": "BTCUSDT",
         "marginMode": "crossed", "leverage": "10"},
        {"category": "USDT-FUTURES", "symbol": "BTCUSDT",
         "marginMode": "isolated", "leverage": "7",
         "longLeverage": "7", "shortLeverage": "7"},
    ]}
    assert runner._settings_entry(settings)["marginMode"] == "isolated"
    assert runner._settings_entry(settings)["leverage"] == "7"


def test_round_down_to_exchange_step():
    assert runner.round_down("0.01239", "0.0001") == Decimal("0.0123")


def test_entry_is_post_only_and_uses_bid_without_extra_leverage():
    class Fake:
        def orderbook(self): return {"b": [["80000.1", "2"]], "a": [["80000.2", "3"]]}
        def place_order(self, order): self.order = order; return {"orderId": "1", **order}
    fake = Fake()
    state = {}
    rule = {"quantityMultiplier": "0.0001", "priceMultiplier": "0.1", "minOrderAmount": "5"}
    runner._place_target_order(fake, Decimal("0.01"), Decimal("0"), 80000,
                               rule, pd.Series(dtype=float), "2026-10-26T00:00:00+00:00", state)
    assert fake.order["orderType"] == "limit"
    assert fake.order["timeInForce"] == "post_only"
    assert fake.order["price"] == "80000.1"
    assert Decimal(fake.order["qty"]) == Decimal("0.01")
    assert fake.order["marginMode"] == "isolated"


def test_reduction_is_market_reduce_only_and_reversal_waits_for_close(tmp_path, monkeypatch):
    class Fake:
        def place_order(self, order): self.order = order; return {"orderId": "2", **order}
    monkeypatch.setattr(runner, "STATE", tmp_path / "state.json")
    fake = Fake()
    state = {}
    rule = {"quantityMultiplier": "0.0001", "priceMultiplier": "0.1", "minOrderAmount": "5"}
    runner._place_target_order(fake, Decimal("-0.03"), Decimal("0.02"), 80000,
                               rule, pd.Series(dtype=float), "2026-10-26T00:00:00+00:00", state)
    assert Decimal(fake.order["qty"]) == Decimal("0.02")
    assert fake.order["orderType"] == "market"
    assert fake.order["reduceOnly"] == "yes"
    assert state["deferred_target_qty"] == "-0.01"


def test_reversal_preserves_deferred_entry_after_close_then_submits_it(tmp_path, monkeypatch):
    class Fake:
        def __init__(self): self.orders = []
        def place_order(self, order): self.orders.append(order); return {"orderId": str(len(self.orders)), **order}
        def orderbook(self): return {"b": [["80000.1", "2"]], "a": [["80000.2", "3"]]}
    monkeypatch.setattr(runner, "STATE", tmp_path / "state.json")
    fake = Fake()
    state = {}
    rule = {"quantityMultiplier": "0.0001", "priceMultiplier": "0.1", "minOrderAmount": "5"}
    runner.process_target_action(fake, Decimal("-0.01"), Decimal("0.02"), 80000,
        rule, pd.Series(dtype=float), "2026-10-26T00:00:00+00:00", state)
    assert state["deferred_target_qty"] == "-0.01"
    assert fake.orders[0]["side"] == "sell"
    assert fake.orders[0]["reduceOnly"] == "yes"

    runner.process_target_action(fake, Decimal("-0.01"), Decimal("0"), 80000,
        rule, pd.Series(dtype=float), "2026-10-26T00:00:00+00:00", state)
    assert "deferred_target_qty" not in state
    assert fake.orders[1]["side"] == "sell"
    assert fake.orders[1]["orderType"] == "limit"
    assert fake.orders[1]["timeInForce"] == "post_only"


def test_owned_strategy_cancel_must_be_confirmed_by_unfilled_list():
    class Fake:
        def __init__(self, keep): self.orders = [{"clientOid": "v453p1", "orderId": "1"}]; self.keep = keep
        def cancel_order(self, **kwargs): pass
        def strategy_orders(self): return self.orders if self.keep else []
    assert runner._cancel_owned(Fake(False), [{"clientOid": "v453p1", "orderId": "1"}],
                                strategy=True) == ["v453p1"]
    with pytest.raises(RuntimeError, match="still reports"):
        runner._cancel_owned(Fake(True), [{"clientOid": "v453p1", "orderId": "1"}],
                             strategy=True)


def test_frozen_strategy_loads_expected_parameters():
    params = runner.read_json(runner.PARAMS_PATH)["signal_params"]
    assert V452Params(**params) == V452Params(short_enabled=True, gate="structural", entry="break8",
        confirmation="activity", adx_min=32.0, protection="base", cooldown_hours=3, risk="higher")
    idx = pd.date_range("2024-01-01", periods=800, freq="h", tz="UTC")
    close = pd.Series(np.linspace(40000, 42000, len(idx)), index=idx)
    market = pd.DataFrame({"open": close, "high": close * 1.001, "low": close * .999,
                           "close": close, "volume": 1000., "quote_volume": close * 1000,
                           "funding_rate": 0., "funding_event": False}, index=idx)
    result = generate_v452_signals(market, V452Params(**params))
    assert len(result) == len(market)
    assert {"signal", "stop_price", "take_profit_price", "cycle_id", "source"}.issubset(result.columns)
