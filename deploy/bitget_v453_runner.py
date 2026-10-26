"""Live Bitget UTA execution for the frozen V4.5.3 signal model."""
from __future__ import annotations

from decimal import Decimal, ROUND_DOWN
import json
import math
import os
from pathlib import Path
import re
import signal
import sys
import time

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from btc_regime.bitget_uta import BitgetError, Credentials, UTAClient, UnknownWriteResult
from btc_regime_v453.v452 import V452Params, generate_v452_signals

CONFIG = Path(os.getenv("BITGET_V453_CONFIG", "runtime/bitget_v453/config.json"))
STATE = Path("runtime/bitget_v453/state.json")
MARKET_CACHE = Path("runtime/bitget_v453/market.pkl")
LOCK = Path("runtime/bitget_v453/runner.lock")
PARAMS_PATH = ROOT / "configs/v4_5_3_params.json"
SOURCE_COMMIT = "39d0675f350ae40caba4b4025b091e7df61bd2a5"
HOUR_MS = 3_600_000
WARMUP_DAYS = 150
POLL_SECONDS = 10
MAKER_TTL_SECONDS = 60 * 60
OWN_PREFIX = "v453"
PROTECT_PREFIX = "v453p"


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default if default is not None else {}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name != "nt":
        os.chmod(temp, 0o600)
        os.chmod(path.parent, 0o700)
    temp.replace(path)


def client_from_config(*, allow_writes=False):
    cfg = read_json(CONFIG)
    return UTAClient(Credentials(cfg.get("api_key", ""), cfg.get("api_secret", ""),
                                 cfg.get("passphrase", "")), allow_writes=allow_writes)


def response_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("list", "orders", "data"):
            if isinstance(value.get(key), list):
                return value[key]
    return []


def parse_candles(rows):
    parsed = []
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        try:
            parsed.append((pd.to_datetime(int(row[0]), unit="ms", utc=True),
                           *(float(row[i]) for i in range(1, 5)),
                           float(row[5]) if len(row) > 5 else 0.0,
                           float(row[6]) if len(row) > 6 else 0.0))
        except (TypeError, ValueError, OverflowError):
            continue
    if not parsed:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "quote_volume"])
    frame = pd.DataFrame(parsed, columns=["timestamp", "open", "high", "low", "close", "volume", "quote_volume"])
    return frame.drop_duplicates("timestamp").set_index("timestamp").sort_index()


def download_candle_history(client, start_ms, end_ms, kind):
    chunk_ms = 900 * HOUR_MS
    frames = []
    left = start_ms
    while left < end_ms:
        right = min(left + chunk_ms, end_ms)
        rows = client.candles(left, right, interval="1H", kind=kind)
        frames.append(parse_candles(rows))
        left = right
        time.sleep(0.08)
    frames = [f for f in frames if not f.empty]
    if not frames:
        raise RuntimeError("Bitget returned no hourly " + kind + " candles")
    return pd.concat(frames).loc[lambda f: ~f.index.duplicated(keep="last")].sort_index()


def download_funding(client):
    rows = []
    for page in range(1, 8):
        payload = client.funding_history(page)
        batch = response_list(payload)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < 100:
            break
        time.sleep(0.08)
    events = {}
    for item in rows:
        try:
            stamp = pd.to_datetime(int(item["fundingTime"]), unit="ms", utc=True)
            events[stamp] = float(item["fundingRate"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
    return events


def refresh_market(client, *, force=False):
    now = pd.Timestamp.now(tz="UTC")
    current_hour = now.floor("h")
    start_ms = int((current_hour - pd.Timedelta(days=WARMUP_DAYS)).timestamp() * 1000)
    end_ms = int(current_hour.timestamp() * 1000)
    funding_due = True
    if MARKET_CACHE.exists() and not force:
        cached = pd.read_pickle(MARKET_CACHE)
        if not cached.empty and cached.index.max() >= current_hour - pd.Timedelta(hours=2):
            last = cached.index.max()
            start_ms = int((last - pd.Timedelta(hours=1)).timestamp() * 1000)
            funding_due = bool(cached.attrs.get("funding_checked_at", 0) < time.time() - 6 * 3600)
        else:
            cached = pd.DataFrame()
    else:
        cached = pd.DataFrame()
    if cached.empty:
        market = download_candle_history(client, start_ms, end_ms, "market")
        mark = download_candle_history(client, start_ms, end_ms, "mark")
        data = market.join(mark[["high", "low"]].rename(columns={"high": "mark_high", "low": "mark_low"}),
                           how="inner")
        events = download_funding(client)
        data["funding_rate"] = 0.0
        data["funding_event"] = False
        for stamp, rate in events.items():
            if stamp in data.index:
                data.loc[stamp, ["funding_rate", "funding_event"]] = [rate, True]
        data.attrs["funding_checked_at"] = time.time()
    else:
        market = parse_candles(client.candles(start_ms, end_ms, interval="1H", kind="market"))
        mark = parse_candles(client.candles(start_ms, end_ms, interval="1H", kind="mark"))
        if not market.empty and not mark.empty:
            new = market.join(mark[["high", "low"]].rename(columns={"high": "mark_high", "low": "mark_low"}),
                              how="inner")
            cached = pd.concat([cached.drop(columns=["funding_checked_at"], errors="ignore"), new])
            cached = cached.loc[~cached.index.duplicated(keep="last")].sort_index()
        data = cached
        if funding_due:
            for stamp, rate in download_funding(client).items():
                if stamp in data.index:
                    data.loc[stamp, ["funding_rate", "funding_event"]] = [rate, True]
            data.attrs["funding_checked_at"] = time.time()
    data = data.loc[data.index + pd.Timedelta(hours=1) <= current_hour]
    needed = {"open", "high", "low", "close", "volume", "quote_volume", "mark_high", "mark_low",
              "funding_rate", "funding_event"}
    for column in needed - set(data.columns):
        data[column] = False if column == "funding_event" else 0.0
    data["funding_rate"] = pd.to_numeric(data.funding_rate, errors="coerce").fillna(0.0)
    data["funding_event"] = data.funding_event.fillna(False).astype(bool)
    data = data.sort_index().loc[lambda f: ~f.index.duplicated(keep="last")]
    if len(data) < 90 * 24:
        raise RuntimeError("Need at least 90 days of complete hourly candles for V4.5.3 warm-up")
    if data.index.has_duplicates or not data.index.to_series().diff().dropna().eq(pd.Timedelta(hours=1)).all():
        raise RuntimeError("Hourly Bitget candles contain a gap; trading is paused until data is complete")
    temp = MARKET_CACHE.with_suffix(".tmp")
    temp.parent.mkdir(parents=True, exist_ok=True)
    data.to_pickle(temp)
    if os.name != "nt":
        os.chmod(temp, 0o600)
    temp.replace(MARKET_CACHE)
    return data


def current_qty(positions):
    qty = Decimal("0")
    for pos in response_list(positions):
        if pos.get("symbol") != "BTCUSDT" or pos.get("category") != "USDT-FUTURES":
            continue
        total = Decimal(str(pos.get("total", "0")))
        if pos.get("marginMode") != "isolated" or str(pos.get("leverage")) != "7":
            raise RuntimeError("BTCUSDT position is not isolated at 7x; trading paused")
        side = pos.get("posSide")
        if side == "long":
            qty += total
        elif side == "short":
            qty -= total
        elif total != 0:
            raise RuntimeError("Unrecognized Bitget one-way position side; trading paused")
    return qty


def _settings_entry(settings):
    items = [x for x in settings.get("symbolConfigList", [])
             if x.get("category") == "USDT-FUTURES" and x.get("symbol") == "BTCUSDT"]
    return items[0] if items else None


def ensure_ready(client, state):
    server_time = client.server_time()
    if isinstance(server_time, dict):
        remote_ms = int(server_time.get("serverTime", server_time.get("ts", 0)))
        if not remote_ms or abs(remote_ms - int(time.time() * 1000)) > 10_000:
            raise RuntimeError("Local system clock differs from Bitget server by more than 10 seconds")
    settings = client.settings()
    if settings.get("accountMode") not in {"unified", "hybrid"}:
        raise RuntimeError("Bitget account is not in UTA mode")
    if settings.get("holdMode") != "one_way_mode":
        raise RuntimeError("Switch the Bitget UTA contract position mode to one-way, then retry")
    entry = _settings_entry(settings)
    if state.get("initialized") and (not entry or entry.get("marginMode") != "isolated"
                                      or str(entry.get("leverage")) != "7"):
        raise RuntimeError("BTCUSDT exchange settings changed; isolated margin at 7x is required")
    positions = client.positions()
    if not state.get("initialized"):
        if any(Decimal(str(p.get("total", "0"))) != 0 for p in response_list(positions)):
            raise RuntimeError("Initial start requires a flat BTCUSDT account; existing positions are left untouched")
        if response_list(client.open_orders()) or response_list(client.strategy_orders()):
            raise RuntimeError("Initial start requires no open BTCUSDT orders; existing orders are left untouched")
        client.set_leverage("long")
        client.set_leverage("short")
        settings = client.settings()
        entry = _settings_entry(settings)
        if not entry or entry.get("marginMode") != "isolated" or str(entry.get("leverage")) != "7":
            raise RuntimeError("Bitget did not confirm isolated margin and 7x leverage")
        state["initialized"] = True
        state["account_mode"] = "one_way_mode"
        state["margin_mode"] = "isolated"
        state["exchange_leverage"] = 7
        write_json(STATE, state)
    current_qty(positions)
    return settings, positions


def usdt_equity(assets):
    value = float(assets.get("usdtEquity", 0) or 0)
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError("Bitget returned no positive USDT equity")
    return value


def round_down(value, step):
    value, step = Decimal(str(value)), Decimal(str(step))
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def instrument_rules(client):
    items = response_list(client.instruments())
    item = next((x for x in items if x.get("symbol") == "BTCUSDT"), None)
    if not item or item.get("status") != "online" or item.get("type") != "perpetual":
        raise RuntimeError("BTCUSDT USDT perpetual is unavailable for trading")
    return item


def signal_snapshot(data):
    params_data = read_json(PARAMS_PATH)
    params = V452Params(**params_data["signal_params"])
    signals = generate_v452_signals(data, params)
    latest = signals.iloc[-1]
    values = signals.signal.fillna(0.0)
    changed = values.ne(values.shift(1).fillna(0.0))
    changed.iloc[0] = True
    event_stamp = signals.index[changed][-1]
    return signals, latest, values, event_stamp


def _order_status(info):
    if isinstance(info, dict):
        return str(info.get("orderStatus", "")).lower()
    return ""


def _cancel_owned(client, orders, *, strategy=False):
    prefix = PROTECT_PREFIX if strategy else OWN_PREFIX
    owned = [order for order in response_list(orders)
             if str(order.get("clientOid", "")).startswith(prefix)]
    cancelled = []
    for order in owned:
        oid = str(order.get("clientOid", ""))
        client.cancel_order(order_id=order.get("orderId"), client_oid=oid, strategy=strategy)
        cancelled.append(oid)
    if strategy:
        remaining = [order for order in response_list(client.strategy_orders())
                     if str(order.get("clientOid", "")) in cancelled]
    else:
        remaining = [order for order in response_list(client.open_orders())
                     if str(order.get("clientOid", "")) in cancelled]
    if remaining:
        raise RuntimeError("Exchange still reports an owned order after cancellation")
    return cancelled


def _format(value, precision):
    quantum = Decimal(1).scaleb(-int(precision))
    return format(Decimal(str(value)).quantize(quantum), "f")


def _protect(client, position, latest, rule, state):
    qty = current_qty(position)
    existing = [o for o in response_list(client.strategy_orders())
                if str(o.get("clientOid", "")).startswith(PROTECT_PREFIX)]
    if qty == 0:
        _cancel_owned(client, existing, strategy=True)
        state["protection"] = None
        return
    target_side = float(latest.get("signal", 0.0) or 0.0)
    if target_side == 0 or np.sign(target_side) != np.sign(float(qty)):
        # A reducing/reversal market order is still settling. Keep the old
        # exchange protection in place until target and actual sides agree.
        return
    stop_value = latest.get("stop_price")
    take_value = latest.get("take_profit_price")
    stop = None if pd.isna(stop_value) else _format(stop_value, int(rule.get("pricePrecision", 1)))
    take = None if pd.isna(take_value) else _format(take_value, int(rule.get("pricePrecision", 1)))
    if stop is None and take is None:
        return
    desired = {"stop": stop, "take": take, "side": "sell" if qty > 0 else "buy"}
    matching = [o for o in existing if not o.get("posSide") or
                o.get("posSide") == ("long" if qty > 0 else "short")]
    mismatched = [o for o in existing if o not in matching]
    if mismatched:
        _cancel_owned(client, mismatched, strategy=True)
    if state.get("protection") == desired and matching:
        return
    if matching:
        result = client.modify_strategy_order(client_oid=matching[0]["clientOid"], qty=format(abs(qty), "f"),
                                              stop=stop, take=take)
        state["protection"] = desired
        state["protection_order"] = result
        write_json(STATE, state)
        if matching[1:]:
            _cancel_owned(client, matching[1:], strategy=True)
        return
    client_oid = PROTECT_PREFIX + str(int(time.time()))
    result = client.place_protection(side=desired["side"], stop=stop, take=take, client_oid=client_oid)
    state["protection"] = desired
    state["protection_order"] = result
    write_json(STATE, state)
    stale = [old for old in existing if old.get("clientOid") != client_oid]
    if stale:
        _cancel_owned(client, stale, strategy=True)


def _place_target_order(client, delta, current, mark, rule, latest, event_key, state):
    step = Decimal(str(rule["quantityMultiplier"]))
    qty = round_down(abs(delta), step)
    if qty <= 0 or qty * Decimal(str(mark)) < Decimal(str(rule["minOrderAmount"])):
        state["last_order"] = None
        state["order_note"] = "target delta is below Bitget minimum order amount"
        return
    reducing = current != 0 and (abs(current + delta) < abs(current) or (current + delta) * current < 0)
    side = "buy" if delta > 0 else "sell"
    sequence = int(state.get("order_sequence", 0)) + 1
    state["order_sequence"] = sequence
    client_oid = OWN_PREFIX + str(int(pd.Timestamp(event_key).timestamp())) + "_" + str(sequence)
    order = {"category": "USDT-FUTURES", "symbol": "BTCUSDT", "qty": format(qty, "f"),
             "side": side, "clientOid": client_oid, "marginMode": "isolated"}
    if reducing:
        if (current + delta) * current < 0:
            qty = abs(current)
            order["qty"] = format(qty, "f")
            state["deferred_target_qty"] = format(current + delta, "f")
        else:
            order["qty"] = format(min(qty, abs(current)), "f")
        order.update({"orderType": "market", "reduceOnly": "yes"})
    else:
        book = client.orderbook()
        bids, asks = book.get("b", []), book.get("a", [])
        levels = bids if side == "buy" else asks
        if not levels:
            raise RuntimeError("Bitget order book did not return a best bid and ask")
        price = round_down(Decimal(str(levels[0][0])), Decimal(str(rule["priceMultiplier"])))
        order.update({"orderType": "limit", "price": format(price, "f"), "timeInForce": "post_only"})
    state["pending_order"] = {"clientOid": client_oid, "created_at": time.time(),
                               "signal_event": event_key, "order": order}
    state["last_order"] = {"clientOid": client_oid, "side": side, "qty": order["qty"],
                           "type": order["orderType"], "status": "submitting"}
    write_json(STATE, state)
    try:
        result = client.place_order(order)
    except UnknownWriteResult:
        state["last_order"]["status"] = "unknown_write_result_reconcile_by_clientOid"
        write_json(STATE, state)
        raise
    state["last_order"] = result
    write_json(STATE, state)


def process_target_action(client, target_qty, current_qty_value, mark, rule, latest, event_key, state):
    """Submit a target change while preserving a reversal's deferred second leg."""
    delta = target_qty - current_qty_value
    state.pop("deferred_target_qty", None)
    if delta != 0:
        _place_target_order(client, delta, current_qty_value, mark, rule, latest, event_key, state)
    state["signal_event"] = event_key


def preflight(client=None):
    client = client or client_from_config()
    rule = instrument_rules(client)
    settings = client.settings()
    assets = client.assets()
    positions = client.positions()
    open_orders = response_list(client.open_orders())
    protections = response_list(client.strategy_orders())
    fees = client.fees()
    open_rows = response_list(open_orders)
    protection_rows = response_list(protections)
    position_rows = response_list(positions)
    has_position = any(Decimal(str(x.get("total", "0"))) != 0 for x in position_rows)
    return {"strategy": "V4.5.3", "source_commit": SOURCE_COMMIT, "live": True,
            "read_only": True, "symbol": "BTCUSDT", "category": "USDT-FUTURES",
            "account_mode": settings.get("accountMode"), "hold_mode": settings.get("holdMode"),
            "symbol_config": _settings_entry(settings), "usdt_equity": assets.get("usdtEquity"),
            "available_usdt": next((x.get("available") for x in assets.get("assets", [])
                                     if x.get("coin") == "USDT"), None),
            "positions": positions, "open_orders": len(open_rows), "strategy_orders": len(protection_rows),
            "open_order_details": [{k: x.get(k) for k in ("clientOid", "orderId", "orderStatus")} for x in open_rows],
            "strategy_order_details": [{k: x.get(k) for k in ("clientOid", "orderId", "status")} for x in protection_rows],
            "fees": fees, "instrument": rule,
            "ready": settings.get("accountMode") in {"unified", "hybrid"}
                     and settings.get("holdMode") == "one_way_mode" and not has_position
                     and not open_rows and not protection_rows}


def cycle(client=None):
    client = client or client_from_config(allow_writes=True)
    state = read_json(STATE)
    settings, positions = ensure_ready(client, state)
    data = refresh_market(client)
    signals, latest, signal_values, event_stamp = signal_snapshot(data)
    rule = instrument_rules(client)
    assets = client.assets()
    equity = usdt_equity(assets)
    ticker = client.ticker()
    ticker_item = next((x for x in response_list(ticker) if x.get("symbol") == "BTCUSDT"), None)
    if not ticker_item:
        raise RuntimeError("Bitget returned no BTCUSDT ticker")
    mark = float(ticker_item.get("markPrice") or ticker_item.get("lastPrice") or 0)
    if not math.isfinite(mark) or mark <= 0:
        raise RuntimeError("Bitget returned an invalid mark price")
    qty = current_qty(positions)
    event_key = event_stamp.isoformat()
    signal = float(latest.signal)
    if abs(signal) > 7:
        raise RuntimeError("Frozen strategy target exceeds configured 7x account leverage")
    target_abs = round_down(Decimal(str(abs(signal) * equity / mark)),
                            Decimal(str(rule["quantityMultiplier"])))
    target_qty = target_abs if signal > 0 else -target_abs if signal < 0 else Decimal("0")
    min_qty = Decimal(str(rule["minOrderQty"]))
    min_value = Decimal(str(rule["minOrderAmount"]))
    if target_abs < min_qty or target_abs * Decimal(str(mark)) < min_value:
        target_qty = Decimal("0")

    pending = state.get("pending_order")
    changed_event = state.get("signal_event") != event_key
    if not pending:
        open_rows = response_list(client.open_orders())
        if any(not str(x.get("clientOid", "")).startswith(OWN_PREFIX) for x in open_rows):
            raise RuntimeError("Unrecognized open BTCUSDT orders exist; refusing to trade")
        if len(open_rows) > 1:
            raise RuntimeError("Multiple owned orders exist; reconcile before trading")
        if open_rows:
            oid = str(open_rows[0].get("clientOid", ""))
            match = re.fullmatch(r"v453(\d{10})_\d+", oid)
            if not match:
                raise RuntimeError("Owned order ID cannot be recovered safely; refusing replacement")
            info = client.order_info(oid)
            pending = {"clientOid": oid, "created_at": float(match.group(1)),
                       "signal_event": state.get("signal_event", event_key), "order": info}
            state["pending_order"] = pending
            state["last_order"] = info
            state["recovered_order"] = True
            write_json(STATE, state)
    if pending:
        try:
            info = client.order_info(pending["clientOid"])
            status = _order_status(info)
        except BitgetError:
            state["updated_at"] = int(time.time())
            state["error"] = "Could not reconcile pending order by clientOid; no replacement order sent"
            write_json(STATE, state)
            raise RuntimeError(state["error"])
        state["last_order"] = info
        age = time.time() - float(pending["created_at"])
        if changed_event or age >= MAKER_TTL_SECONDS:
            if status in {"live", "new", "partially_filled"}:
                client.cancel_order(order_id=info.get("orderId"), client_oid=pending["clientOid"])
                info = client.order_info(pending["clientOid"])
                state["last_order"] = info
                status = _order_status(info)
            if status not in {"filled", "cancelled", "rejected", "failed"}:
                state.update({"updated_at": int(time.time()),
                              "error": "Cancel acknowledgement is not final; replacement order withheld"})
                write_json(STATE, state)
                raise RuntimeError("Maker cancellation is not confirmed; waiting before replacing the order")
            if not changed_event:
                state["maker_expired_event"] = pending.get("signal_event")
            state["pending_order"] = None
            positions = client.positions()
            qty = current_qty(positions)
            pending = None
        elif status in {"filled", "cancelled", "rejected", "failed"}:
            state["pending_order"] = None
            positions = client.positions()
            qty = current_qty(positions)
            pending = None
        elif status in {"live", "new", "partially_filled"}:
            if state.get("maker_expired_event") == pending.get("signal_event"):
                client.cancel_order(order_id=info.get("orderId"), client_oid=pending["clientOid"])
                info = client.order_info(pending["clientOid"])
                if _order_status(info) not in {"filled", "cancelled", "rejected", "failed"}:
                    state["error"] = "Expired Maker order cancellation is not final"
                    write_json(STATE, state)
                    raise RuntimeError(state["error"])
                state["pending_order"] = None
                state["last_order"] = info
                pending = None
            else:
                pending_age = int(age)
                state.update({"updated_at": int(time.time()), "strategy": "V4.5.3", "last_bar": data.index[-1].isoformat(),
                              "last_signal": signal, "target_qty": format(target_qty, "f"),
                              "current_qty": format(qty, "f"), "equity": equity, "mark_price": mark,
                              "pending_order_age_seconds": pending_age, "error": None})
                _protect(client, positions, latest, rule, state)
                write_json(STATE, state)
                return state

    if state.get("signal_event") is None:
        # First use begins from the latest closed signal and never imports an old exchange position.
        changed_event = True
        state["bootstrap"] = True
    needs_target_action = changed_event or state.get("deferred_target_qty") is not None
    if needs_target_action and state.get("maker_expired_event") != event_key and pending is None:
        process_target_action(client, target_qty, qty, mark, rule, latest, event_key, state)
    positions = client.positions()
    qty = current_qty(positions)
    _protect(client, positions, latest, rule, state)
    state.update({"strategy": "V4.5.3", "source_commit": SOURCE_COMMIT,
                  "updated_at": int(time.time()), "last_bar": data.index[-1].isoformat(),
                  "signal_event": state.get("signal_event", event_key), "last_signal": signal,
                  "last_reason": str(latest.get("source", "")), "equity": equity,
                  "current_qty": format(qty, "f"), "target_qty": format(target_qty, "f"),
                  "mark_price": mark, "margin_mode": "isolated", "leverage": 7,
                  "error": None})
    write_json(STATE, state)
    return state


def flatten(client=None):
    client = client or client_from_config(allow_writes=True)
    state = read_json(STATE)
    if not state.get("initialized"):
        raise RuntimeError("Runner has not initialized this account; no automatic close is allowed")
    orders = client.open_orders()
    if any(not str(x.get("clientOid", "")).startswith(OWN_PREFIX) for x in response_list(orders)):
        raise RuntimeError("Unrecognized open BTCUSDT order exists; refusing to flatten")
    protections = client.strategy_orders()
    if any(not str(x.get("clientOid", "")).startswith(PROTECT_PREFIX) for x in response_list(protections)):
        raise RuntimeError("Unrecognized BTCUSDT protection order exists; refusing to flatten")
    cancelled_orders = _cancel_owned(client, orders)
    positions = client.positions()
    qty = current_qty(positions)
    close_result = None
    if qty != 0:
        rule = instrument_rules(client)
        amount = round_down(abs(qty), Decimal(str(rule["quantityMultiplier"])))
        close_result = client.place_order({"category": "USDT-FUTURES", "symbol": "BTCUSDT",
                                           "qty": format(amount, "f"), "side": "sell" if qty > 0 else "buy",
                                           "orderType": "market", "reduceOnly": "yes",
                                           "marginMode": "isolated", "clientOid": OWN_PREFIX + "close" + str(int(time.time()))})
        residual = current_qty(client.positions())
        if residual != 0:
            state["close_residual_qty"] = format(residual, "f")
            state["last_order"] = close_result
            write_json(STATE, state)
            raise RuntimeError("Close order submitted but position is not flat; exchange protections remain active")
    cancelled_protection = _cancel_owned(client, protections, strategy=True)
    state.update({"pending_order": None, "protection": None, "last_order": close_result,
                  "updated_at": int(time.time()), "last_action": "flatten_requested"})
    write_json(STATE, state)
    return {"cancelled_orders": cancelled_orders, "close_order": close_result,
            "cancelled_protections": cancelled_protection, "previous_qty": format(qty, "f")}


def cancel_pending_entry(client=None):
    state = read_json(STATE)
    client = client or client_from_config(allow_writes=True)
    cancelled = _cancel_owned(client, client.open_orders())
    pending = state.get("pending_order")
    if not pending and not cancelled:
        return None
    info = client.order_info(pending["clientOid"]) if pending else None
    state["pending_order"] = None
    if info:
        state["last_order"] = info
    state["last_action"] = "pending_entry_cancelled_by_operator"
    state["updated_at"] = int(time.time())
    write_json(STATE, state)
    return info


def acquire_lock():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return
        except FileExistsError:
            try:
                pid = int(LOCK.read_text(encoding="ascii"))
                os.kill(pid, 0)
                if os.name == "posix":
                    try:
                        status = Path(f"/proc/{pid}/stat").read_text().split()[2]
                    except (FileNotFoundError, IndexError):
                        status = ""
                    if status == "Z":
                        try:
                            os.waitpid(pid, os.WNOHANG)
                        except ChildProcessError:
                            pass
                        LOCK.unlink(missing_ok=True)
                        continue
                raise RuntimeError("V4.5.3 runner already holds the execution lock")
            except ProcessLookupError:
                LOCK.unlink(missing_ok=True)
            except ValueError:
                raise RuntimeError("Runner lock is invalid; inspect it before removing")
    raise RuntimeError("Could not acquire V4.5.3 runner lock")


def run():
    def terminate(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate)
    acquire_lock()
    try:
        while True:
            try:
                state = cycle()
                print(json.dumps({"strategy": "V4.5.3", "bar": state.get("last_bar"),
                                  "signal": state.get("last_signal"), "target_qty": state.get("target_qty"),
                                  "current_qty": state.get("current_qty")}, ensure_ascii=False), flush=True)
            except Exception as exc:
                state = read_json(STATE)
                state.update({"updated_at": int(time.time()), "error": str(exc)[:500]})
                write_json(STATE, state)
                print("V4.5.3 cycle failed: " + str(exc)[:300], file=sys.stderr, flush=True)
            time.sleep(POLL_SECONDS)
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--once"]:
        print(json.dumps(cycle(), ensure_ascii=False, indent=2))
    else:
        run()
