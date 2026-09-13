#!/usr/bin/env python3
"""Binance USD-M Demo runner for the three preserved strategy profiles.

This runner deliberately talks only to Binance's Futures Demo endpoint.  It
uses completed 4h candles, then reconciles the signed BTCUSDT position to the
strategy's target exposure once per candle.  API credentials are read from the
local, git-ignored runtime/demo_accounts.json file created by demo_gui.py.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import math
import sys
import time
import traceback
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from btc_regime.v43 import V43Params, generate_v43_signals  # noqa: E402
from btc_regime.v7 import V7Params, generate_v7_signals  # noqa: E402
from btc_regime.v71_live import V71LiveParams, generate_v71_live_signals  # noqa: E402

BASE_URL = "https://demo-fapi.binance.com"
CONFIG = ROOT / "runtime/demo_accounts.json"
STATE_DIR = ROOT / "runtime/strategy_state"
POLL_SECONDS = 60


@dataclass(frozen=True)
class StrategySpec:
    name: str
    params_file: Path
    param_type: type
    generator: Callable[..., pd.DataFrame]
    execution_file: Path | None = None


SPECS = {
    "v43": StrategySpec("V4.3", ROOT / "configs/v4_3_params.json", V43Params, generate_v43_signals),
    "v71": StrategySpec("V7.1", ROOT / "configs/v71_params.json", V7Params, generate_v7_signals),
    "v72": StrategySpec("V7.2", ROOT / "configs/wzy_v72_tp_refined_params.json", V71LiveParams, generate_v71_live_signals, ROOT / "configs/wzy_v72_execution.json"),
}


class DemoClient:
    def __init__(self, api_key: str, api_secret: str) -> None:
        if not api_key or not api_secret:
            raise ValueError("API Key / Secret has not been saved in the GUI")
        self.api_key, self.api_secret = api_key, api_secret

    def request(self, method: str, path: str, params: dict[str, Any] | None = None, *, signed: bool = False) -> Any:
        values = {k: str(v) for k, v in (params or {}).items() if v is not None}
        headers = {"User-Agent": "binance-btc-demo-runner/1.0"}
        if signed:
            values.update(timestamp=str(int(time.time() * 1000)), recvWindow="5000")
            query = urlencode(values)
            values["signature"] = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
            headers["X-MBX-APIKEY"] = self.api_key
        query = urlencode(values)
        if method.upper() == "GET":
            request = Request(BASE_URL + path + ("?" + query if query else ""), headers=headers)
        else:
            request = Request(BASE_URL + path, data=query.encode(), headers=headers, method=method.upper())
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode())

    def signed(self, method: str, path: str, **params: Any) -> Any:
        return self.request(method, path, params, signed=True)


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def api_error(payload: Any) -> None:
    if isinstance(payload, dict) and "code" in payload and int(payload["code"]) < 0:
        raise RuntimeError(f"Binance Demo API error {payload['code']}: {payload.get('msg', '')}")


def completed_klines(client: DemoClient, symbol: str) -> pd.DataFrame:
    rows = client.request("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": "4h", "limit": 1000})
    if not isinstance(rows, list) or len(rows) < 300:
        raise RuntimeError("Demo API returned too few 4h candles for indicator warm-up")
    columns = ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume", "ignore"]
    frame = pd.DataFrame(rows, columns=columns)
    frame["timestamp"] = pd.to_datetime(frame["open_time"], unit="ms", utc=True)
    frame["close_timestamp"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True)
    for column in ("open", "high", "low", "close", "volume", "quote_volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    now = pd.Timestamp.now(tz="UTC")
    frame = frame.loc[frame["close_timestamp"] < now].set_index("timestamp")
    return frame[["open", "high", "low", "close", "volume", "quote_volume"]].dropna()


def add_funding(client: DemoClient, frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Attach causal latest-known funding rates; absent demo history means zero."""
    result = frame.copy()
    result["funding_rate"] = 0.0
    try:
        funding = client.request("GET", "/fapi/v1/fundingRate", {"symbol": symbol, "limit": 1000})
        if not isinstance(funding, list) or not funding:
            return result
        rates = pd.DataFrame(funding)
        rates["timestamp"] = pd.to_datetime(rates["fundingTime"], unit="ms", utc=True)
        rates["funding_rate"] = pd.to_numeric(rates["fundingRate"], errors="coerce").fillna(0.0)
        left = result.reset_index().sort_values("timestamp")
        right = rates[["timestamp", "funding_rate"]].sort_values("timestamp")
        merged = pd.merge_asof(left, right, on="timestamp", direction="backward", suffixes=("", "_event"))
        result["funding_rate"] = merged["funding_rate_event"].fillna(0.0).to_numpy()
    except Exception:
        # A missing public funding history must not make strategy execution use
        # an uncompleted candle or block a protective flat signal.
        pass
    return result


def filters(client: DemoClient, symbol: str) -> tuple[Decimal, Decimal]:
    info = client.request("GET", "/fapi/v1/exchangeInfo")
    item = next((x for x in info.get("symbols", []) if x.get("symbol") == symbol), None)
    if not item:
        raise RuntimeError(f"{symbol} is not available in the Demo exchangeInfo response")
    values = {x["filterType"]: x for x in item.get("filters", [])}
    lot = values.get("LOT_SIZE") or values.get("MARKET_LOT_SIZE")
    if not lot:
        raise RuntimeError("exchangeInfo did not include a BTCUSDT lot-size filter")
    return Decimal(lot["stepSize"]), Decimal((values.get("MIN_NOTIONAL") or {}).get("notional", "5"))


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def account_snapshot(client: DemoClient, symbol: str) -> tuple[dict[str, Any], dict[str, Any]]:
    account = client.signed("GET", "/fapi/v2/account")
    api_error(account)
    positions = client.signed("GET", "/fapi/v2/positionRisk", symbol=symbol)
    api_error(positions)
    position = next((p for p in positions if p.get("symbol") == symbol), None)
    if not position:
        raise RuntimeError(f"No {symbol} position record returned")
    return account, position


def ensure_account_mode(client: DemoClient, symbol: str, required_leverage: int) -> None:
    account = client.signed("GET", "/fapi/v1/positionSide/dual")
    api_error(account)
    if account.get("dualSidePosition"):
        raise RuntimeError("Please disable Hedge Mode for this Demo account; the runner requires One-way Mode")
    try:
        response = client.signed("POST", "/fapi/v1/marginType", symbol=symbol, marginType="ISOLATED")
    except HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        if "-4046" not in detail and "No need to change margin type" not in detail:
            raise
        response = {"code": -4046}
    if isinstance(response, dict) and int(response.get("code", 200)) not in (200, -4046):
        api_error(response)
    response = client.signed("POST", "/fapi/v1/leverage", symbol=symbol, leverage=required_leverage)
    api_error(response)


def governor_scale(key: str, equity: float, state: dict[str, Any], spec: StrategySpec) -> float:
    """Keep V7.2's own account-drawdown governor isolated to V7.2 only."""
    if key != "v72" or not spec.execution_file:
        return 1.0
    cfg = read_json(spec.execution_file, {})
    if not cfg.get("strategy_drawdown_enabled", False):
        return 1.0
    peak = max(float(state.get("peak_equity", equity)), equity)
    state["peak_equity"] = peak
    drawdown = 1.0 - equity / peak if peak > 0 else 0.0
    state["drawdown"] = drawdown
    for level in (3, 2, 1):
        if drawdown >= float(cfg.get(f"strategy_drawdown_level_{level}", 2)):
            return float(cfg.get(f"strategy_drawdown_scale_{level}", 1))
    return 1.0


def replace_protective_orders(client: DemoClient, symbol: str, target_qty: Decimal, latest: pd.Series) -> list[dict[str, Any]]:
    """Replace bracket exits on a dedicated strategy account.

    The repository's V4.3 and V7.2 generators expose causal stop/take levels.
    Binance's closePosition conditional orders protect the entire one-way
    position without changing the strategy's entry or target-sizing rules.
    """
    cancelled = client.signed("DELETE", "/fapi/v1/allOpenOrders", symbol=symbol)
    api_error(cancelled)
    if target_qty == 0:
        return []
    stop = latest.get("stop_price")
    take = latest.get("take_profit_price")
    if not pd.notna(stop) or not pd.notna(take):
        return []
    side = "SELL" if target_qty > 0 else "BUY"
    created = []
    for order_type, price in (("STOP_MARKET", stop), ("TAKE_PROFIT_MARKET", take)):
        response = client.signed(
            "POST", "/fapi/v1/order", symbol=symbol, side=side, type=order_type,
            stopPrice=f"{float(price):.2f}", closePosition="true", workingType="MARK_PRICE",
            priceProtect="TRUE", newClientOrderId=f"btcprotect{int(time.time() * 1000)}{len(created)}",
        )
        api_error(response)
        created.append(response)
    return created


def cycle(key: str, *, force: bool = False) -> dict[str, Any]:
    spec = SPECS[key]
    config = read_json(CONFIG, {})
    c = config.get(key) or {}
    symbol = str(c.get("symbol", "BTCUSDT")).upper()
    client = DemoClient(str(c.get("api_key", "")), str(c.get("api_secret", "")))
    params = spec.param_type(**read_json(spec.params_file, {}))
    # The exchange leverage must accommodate the original strategy's maximum
    # target exposure.  This does not modify the strategy configuration.
    ensure_account_mode(client, symbol, math.ceil(float(params.max_leverage)))
    market = add_funding(client, completed_klines(client, symbol), symbol)
    signals = spec.generator(market, params)
    latest = signals.iloc[-1]
    bar = str(signals.index[-1])
    state_path = STATE_DIR / f"{key}.json"
    state = read_json(state_path, {})
    account, position = account_snapshot(client, symbol)
    equity = float(account.get("totalMarginBalance") or account.get("totalWalletBalance") or 0)
    cap = float(c.get("capital_cap_usdt", 4000 if key == "v72" else 0) or 0)
    usable_equity = min(equity, cap) if cap > 0 else equity
    scale = governor_scale(key, equity, state, spec)
    signal = float(latest["signal"]) * scale
    mark = float(position.get("markPrice") or latest["close"])
    target_notional = abs(signal) * usable_equity
    step, min_notional = filters(client, symbol)
    target_qty = floor_step(Decimal(str(target_notional / mark)), step)
    if target_notional < float(min_notional):
        target_qty = Decimal("0")
    if signal < 0:
        target_qty = -target_qty
    current_qty = Decimal(str(position.get("positionAmt", "0")))
    delta = target_qty - current_qty
    order: dict[str, Any] | None = None
    protective_orders: list[dict[str, Any]] = []
    if force or state.get("last_bar") != bar:
        if abs(delta) * Decimal(str(mark)) >= min_notional and delta != 0:
            order = client.signed(
                "POST", "/fapi/v1/order", symbol=symbol,
                side="BUY" if delta > 0 else "SELL", type="MARKET",
                quantity=format(abs(delta), "f"), newOrderRespType="RESULT",
                newClientOrderId=f"btc{key}{int(time.time())}",
            )
            api_error(order)
        protective_orders = replace_protective_orders(client, symbol, target_qty, latest)
        state["last_bar"] = bar
    state.update({
        "strategy": spec.name, "updated_at": int(time.time()), "last_signal": signal,
        "last_reason": str(latest.get("v71_live_reason", latest.get("regime", ""))),
        "equity": equity, "usable_equity": usable_equity, "governor_scale": scale,
        "current_qty": str(current_qty), "target_qty": str(target_qty), "mark_price": mark,
        "last_order": order, "protective_orders": protective_orders,
    })
    write_json(state_path, state)
    return state


def run(key: str) -> None:
    while True:
        try:
            state = cycle(key)
            print(json.dumps({"strategy": key, "bar": state.get("last_bar"), "signal": state.get("last_signal"), "target_qty": state.get("target_qty")}, ensure_ascii=False), flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            path = STATE_DIR / f"{key}.json"
            state = read_json(path, {})
            state.update({"updated_at": int(time.time()), "error": str(exc), "traceback": traceback.format_exc(limit=3)})
            write_json(path, state)
            print(f"{key}: {exc}", file=sys.stderr, flush=True)
        time.sleep(POLL_SECONDS)


def close(key: str) -> dict[str, Any]:
    config = read_json(CONFIG, {})
    c = config.get(key) or {}
    symbol = str(c.get("symbol", "BTCUSDT")).upper()
    client = DemoClient(str(c.get("api_key", "")), str(c.get("api_secret", "")))
    cancelled = client.signed("DELETE", "/fapi/v1/allOpenOrders", symbol=symbol)
    api_error(cancelled)
    _, position = account_snapshot(client, symbol)
    quantity = Decimal(str(position.get("positionAmt", "0")))
    if quantity == 0:
        return {"message": "already flat", "cancelled": cancelled}
    result = client.signed("POST", "/fapi/v1/order", symbol=symbol, side="SELL" if quantity > 0 else "BUY", type="MARKET", quantity=format(abs(quantity), "f"), reduceOnly="true", newOrderRespType="RESULT", newClientOrderId=f"btc{key}close{int(time.time())}")
    api_error(result)
    return {"cancelled": cancelled, "close_order": result}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=sorted(SPECS), required=True)
    parser.add_argument("--once", action="store_true", help="Evaluate the completed candle and reconcile once")
    parser.add_argument("--force", action="store_true", help="Allow an order on the current completed candle")
    parser.add_argument("--close", action="store_true", help="Market-close this strategy's BTCUSDT position")
    args = parser.parse_args()
    if args.close:
        print(json.dumps(close(args.strategy), ensure_ascii=False, indent=2))
    elif args.once:
        print(json.dumps(cycle(args.strategy, force=args.force), ensure_ascii=False, indent=2))
    else:
        run(args.strategy)


if __name__ == "__main__":
    main()
