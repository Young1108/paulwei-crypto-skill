#!/usr/bin/env python3
"""
BTC Paper 合约机器人 v1。

只模拟 MEXC BTC_USDT 永续合约，不连接真实账户，不读取或保存任何 API Key。
所有命令输出 JSON，便于 Codex skill 或其他本地工具调用。
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_STATE_PATH = ROOT_DIR / "data" / "paper_state.json"
ANALYZE_SCRIPT = ROOT_DIR / "scripts" / "analyze.py"
MEXC_API_BASE = "https://contract.mexc.com/api/v1"

SUPPORTED_SYMBOL = "BTCUSDT"
MEXC_SYMBOL = "BTC_USDT"
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}USDT$")

CONTRACT_SIZE_BTC = 0.0001
MIN_VOL = 1
VOL_UNIT = 1
PRICE_UNIT = 0.1
MAKER_FEE_RATE = 0.0
TAKER_FEE_RATE = 0.0001

DEFAULT_BALANCE = 500.0
STANDARD_RISK_PCT = 0.005
MAX_RISK_PCT = 0.01
MAX_LEVERAGE = 3.0
DAILY_LOSS_LOCK_PCT = 0.02
PLAN_EXPIRY_SECONDS = 4 * 60 * 60
CANDLE_INTERVAL_MS = 60 * 1000
MARKET_STALE_SECONDS = 30


class PaperBotError(Exception):
    """Paper 机器人可预期错误。"""


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch_ms():
    return int(time.time() * 1000)


def current_candle_time_ms(now_ms=None):
    value = now_ms if now_ms is not None else epoch_ms()
    return (int(value) // CANDLE_INTERVAL_MS) * CANDLE_INTERVAL_MS


def parse_utc_ms(value):
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp() * 1000)
    except ValueError:
        return None


def today_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def json_print(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))


def error_exit(message, code=1):
    json_print({"ok": False, "error": message})
    sys.exit(code)


def state_path_from_args(args):
    raw_path = getattr(args, "state_path", None) or os.environ.get("PAPER_BOT_STATE_PATH")
    return Path(raw_path).expanduser().resolve() if raw_path else DEFAULT_STATE_PATH


def normalize_symbol(raw_symbol):
    symbol = raw_symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise PaperBotError(
            "Invalid symbol format. Use BTCUSDT only for paper v1; "
            "query strings or special characters are rejected."
        )
    if symbol != SUPPORTED_SYMBOL:
        raise PaperBotError("Paper v1 only supports BTCUSDT / MEXC BTC_USDT.")
    return symbol


def round_price(price, mode="nearest"):
    units = price / PRICE_UNIT
    if mode == "up":
        return round(math.ceil(units) * PRICE_UNIT, 1)
    if mode == "down":
        return round(math.floor(units) * PRICE_UNIT, 1)
    return round(round(units) * PRICE_UNIT, 1)


def round_contracts(raw_contracts):
    contracts = math.floor(raw_contracts / VOL_UNIT) * VOL_UNIT
    return int(contracts) if contracts >= MIN_VOL else 0


def contracts_from_notional(notional_usdt, price):
    return round_contracts(notional_usdt / (price * CONTRACT_SIZE_BTC))


def notional_from_contracts(contracts, price):
    return contracts * CONTRACT_SIZE_BTC * price


def validate_leverage(leverage):
    if leverage <= 0:
        raise PaperBotError("leverage must be positive.")
    if leverage > MAX_LEVERAGE:
        raise PaperBotError(f"Paper v1 leverage cap is {MAX_LEVERAGE}x.")


def load_state(path):
    if not path.exists():
        raise PaperBotError("Paper state not initialized. Run init first.")
    with path.open("r", encoding="utf-8") as handle:
        return migrate_state(json.load(handle))


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = utc_now()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")
    tmp_path.replace(path)


def initial_state(balance):
    now = utc_now()
    return {
        "version": 1,
        "mode": "paper",
        "exchange": "mexc",
        "symbol_scope": ["BTCUSDT"],
        "created_at": now,
        "updated_at": now,
        "initial_balance": round(float(balance), 4),
        "cash_balance": round(float(balance), 4),
        "equity": round(float(balance), 4),
        "peak_equity": round(float(balance), 4),
        "max_drawdown_pct": 0.0,
        "positions": [],
        "open_orders": [],
        "pending_plans": [],
        "closed_trades": [],
        "risk_events": [],
        "funding_snapshots": [],
        "equity_snapshots": [],
        "last_tick_at": None,
        "last_candle_time": None,
        "last_processed_candle_time": None,
        "last_market_timestamp": None,
        "last_action": "initialized"
    }


def migrate_state(state):
    state.setdefault("version", 1)
    state.setdefault("positions", [])
    state.setdefault("open_orders", [])
    state.setdefault("pending_plans", [])
    state.setdefault("closed_trades", [])
    state.setdefault("risk_events", [])
    state.setdefault("funding_snapshots", [])
    state.setdefault("equity_snapshots", [])
    state.setdefault("last_tick_at", None)
    state.setdefault("last_candle_time", None)
    state.setdefault("last_processed_candle_time", None)
    state.setdefault("last_market_timestamp", None)
    state.setdefault("last_action", None)
    return state


def daily_realized_pnl(state, day=None):
    day = day or today_utc()
    total = 0.0
    for trade in state.get("closed_trades", []):
        if str(trade.get("closed_at", "")).startswith(day):
            total += float(trade.get("realized_pnl", 0))
    return round(total, 8)


def is_risk_locked(state):
    daily_pnl = daily_realized_pnl(state)
    lock_amount = -float(state["initial_balance"]) * DAILY_LOSS_LOCK_PCT
    return daily_pnl <= lock_amount, daily_pnl, lock_amount


def active_entry_orders(state):
    return [
        order for order in state.get("open_orders", [])
        if order.get("status") == "open" and not order.get("reduce_only", False)
    ]


def active_pending_plans(state):
    return [
        plan for plan in state.get("pending_plans", [])
        if plan.get("status") == "pending"
    ]


def active_position(state):
    positions = [
        position for position in state.get("positions", [])
        if int(position.get("remaining_contracts", 0)) > 0
    ]
    return positions[0] if positions else None


def market_age_seconds(market):
    if not market:
        return None
    timestamp = market.get("timestamp")
    if not timestamp:
        return None
    try:
        value = int(float(timestamp))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value < 1_000_000_000_000:
        value *= 1000
    return round(max(0, epoch_ms() - value) / 1000, 1)


def market_status(market):
    if not market:
        return "unavailable"
    age = market_age_seconds(market)
    if age is None:
        return "unknown"
    return "live" if age <= MARKET_STALE_SECONDS else "stale"


def expire_stale_items(state, now_ms=None):
    now_value = now_ms if now_ms is not None else epoch_ms()
    expired = []
    current_time = utc_now()

    for plan in state.get("pending_plans", []):
        if plan.get("status") != "pending":
            continue
        expires_at_ms = parse_utc_ms(plan.get("expires_at"))
        if expires_at_ms and expires_at_ms <= now_value:
            plan["status"] = "expired"
            plan["expired_at"] = current_time
            plan["expire_reason"] = "plan_expired"
            expired.append({"type": "plan", "plan_id": plan.get("plan_id")})

    for order in state.get("open_orders", []):
        if order.get("status") != "open" or order.get("reduce_only", False):
            continue
        expires_at_ms = parse_utc_ms(order.get("expires_at"))
        if not expires_at_ms:
            created_at_ms = order.get("created_at_ms") or parse_utc_ms(order.get("created_at"))
            if created_at_ms:
                expires_at_ms = int(created_at_ms) + PLAN_EXPIRY_SECONDS * 1000
        if expires_at_ms and expires_at_ms <= now_value:
            order["status"] = "expired"
            order["expired_at"] = current_time
            order["expire_reason"] = "order_expired"
            expired.append({"type": "order", "order_id": order.get("order_id"), "plan_id": order.get("plan_id")})

    return expired


def cancel_items(state, plan_id=None, order_id=None, cancel_all=False, reason="manual_cancel"):
    if not cancel_all and not plan_id and not order_id:
        raise PaperBotError("cancel requires --all, --plan-id or --order-id.")

    current_time = utc_now()
    cancelled_plans = []
    cancelled_orders = []

    for plan in state.get("pending_plans", []):
        matches = cancel_all or (plan_id and plan.get("plan_id") == plan_id)
        if matches and plan.get("status") == "pending":
            plan["status"] = "cancelled"
            plan["cancelled_at"] = current_time
            plan["cancel_reason"] = reason
            cancelled_plans.append(plan.get("plan_id"))

    for order in state.get("open_orders", []):
        matches = (
            cancel_all
            or (plan_id and order.get("plan_id") == plan_id)
            or (order_id and order.get("order_id") == order_id)
        )
        if matches and order.get("status") == "open" and not order.get("reduce_only", False):
            order["status"] = "cancelled"
            order["cancelled_at"] = current_time
            order["cancel_reason"] = reason
            cancelled_orders.append(order.get("order_id"))

    if not cancel_all and not cancelled_plans and not cancelled_orders:
        raise PaperBotError("No cancellable pending plan or open entry order matched.")

    state["last_action"] = "cancelled" if (cancelled_plans or cancelled_orders) else "cancel_noop"
    return {
        "cancelled_plans": cancelled_plans,
        "cancelled_orders": cancelled_orders,
        "cancelled_count": len(cancelled_plans) + len(cancelled_orders)
    }


def cancel_open_entries_for_plan(state, plan_id, reason):
    if not plan_id:
        return []
    current_time = utc_now()
    cancelled = []
    for order in state.get("open_orders", []):
        if (
            order.get("plan_id") == plan_id
            and order.get("status") == "open"
            and not order.get("reduce_only", False)
        ):
            order["status"] = "cancelled"
            order["cancelled_at"] = current_time
            order["cancel_reason"] = reason
            cancelled.append(order.get("order_id"))
    return cancelled


def append_daily_loss_lock_event(state, daily_pnl, lock_amount):
    day = today_utc()
    for event in reversed(state.get("risk_events", [])):
        if event.get("type") == "daily_loss_lock" and str(event.get("created_at", "")).startswith(day):
            return None
    event = {
        "event_id": f"risk_{uuid.uuid4().hex[:12]}",
        "type": "daily_loss_lock",
        "created_at": utc_now(),
        "daily_realized_pnl": daily_pnl,
        "lock_amount": lock_amount
    }
    state.setdefault("risk_events", []).append(event)
    return event


def http_get_json(url, timeout=4.0):
    req = Request(url, headers={"User-Agent": "paulwei-paper-bot/1.0"})
    try:
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise PaperBotError(f"MEXC HTTP error {exc.code}: {body}") from exc
    except URLError as exc:
        raise PaperBotError(f"MEXC network error: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise PaperBotError("MEXC returned non-JSON response.") from exc


def fetch_mexc(endpoint, **params):
    query = urlencode(params)
    url = f"{MEXC_API_BASE}/{endpoint}?{query}" if query else f"{MEXC_API_BASE}/{endpoint}"
    payload = http_get_json(url)
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise PaperBotError(f"MEXC API error for {endpoint}: {payload}")
    return payload.get("data")


def latest_mexc_candle():
    fixture = os.environ.get("PAPER_BOT_MARKET_FIXTURE")
    if fixture:
        with Path(fixture).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if "candle" in payload:
            return payload["candle"]

    data = fetch_mexc(f"contract/kline/{MEXC_SYMBOL}", interval="Min1", limit=1)
    required = ["time", "open", "close", "high", "low", "vol"]
    if not isinstance(data, dict) or any(key not in data for key in required):
        raise PaperBotError("MEXC candle response is malformed.")
    if not data["time"]:
        raise PaperBotError("MEXC candle response is empty.")
    return {
        "time": int(data["time"][-1]) * 1000,
        "open": float(data["open"][-1]),
        "close": float(data["close"][-1]),
        "high": float(data["high"][-1]),
        "low": float(data["low"][-1]),
        "volume": float(data["vol"][-1])
    }


def latest_mexc_ticker():
    fixture = os.environ.get("PAPER_BOT_MARKET_FIXTURE")
    if fixture:
        with Path(fixture).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if "ticker" in payload:
            return payload["ticker"]

    data = fetch_mexc("contract/ticker", symbol=MEXC_SYMBOL)
    if not isinstance(data, dict):
        raise PaperBotError("MEXC ticker response is malformed.")
    return {
        "price": float(data["lastPrice"]),
        "fair_price": float(data.get("fairPrice", data["lastPrice"])),
        "funding_rate": float(data.get("fundingRate", 0)),
        "timestamp": int(data.get("timestamp", 0)),
        "change_pct_24h": float(data.get("riseFallRate", 0)) * 100,
        "high_24h": float(data.get("high24Price", 0) or 0),
        "low_24h": float(data.get("lower24Price", 0) or 0),
        "bid": float(data.get("bid1", 0) or 0),
        "ask": float(data.get("ask1", 0) or 0),
        "volume_24h": float(data.get("volume24", 0) or 0)
    }


def run_analyze(symbol):
    fixture = os.environ.get("PAPER_BOT_ANALYSIS_FIXTURE")
    if fixture:
        with Path(fixture).open("r", encoding="utf-8") as handle:
            return json.load(handle)

    env = os.environ.copy()
    env["PAULWEI_MARKET_PROVIDERS"] = "mexc"
    env.setdefault("PAULWEI_MARKET_REQUEST_TIMEOUT", "2.5")
    env.setdefault("PAULWEI_MARKET_ROUTE_TIMEOUT", "4.5")
    completed = subprocess.run(
        [sys.executable, str(ANALYZE_SCRIPT), symbol],
        capture_output=True,
        text=True,
        timeout=8,
        env=env,
        check=False
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise PaperBotError(f"analyze.py returned invalid JSON: {completed.stderr}") from exc
    if completed.returncode != 0 or "error" in payload:
        raise PaperBotError(payload.get("error", "analyze.py failed."))
    return payload


def short_psych_price(target, ending):
    base = math.floor(target / 1000) * 1000 + ending
    while base < target:
        base += 1000
    return round_price(base, "up")


def choose_short_setup(analysis):
    price = float(analysis["price"]["current"])
    trend4h = analysis["structure_4h"]["trend"]
    supports = [float(value) for value in analysis["levels"].get("support", [])]
    resistances = [float(value) for value in analysis["levels"].get("resistance", [])]
    zones = analysis["structure_4h"].get("key_zones", [])
    ma7 = float(analysis["ma"]["ma7"])
    ma14 = float(analysis["ma"]["ma14"])

    nearest_support = supports[0] if supports else None
    near_support = bool(
        nearest_support and nearest_support < price and (price - nearest_support) / price <= 0.012
    )
    if near_support and trend4h != "下降趋势":
        return {
            "status": "wait",
            "reason": "现价贴近关键支撑且 4h 不是明确下降趋势，不追空。",
            "price": price,
            "nearest_support": nearest_support
        }

    if nearest_support and price < nearest_support * 0.998:
        entry_low = nearest_support * 1.001
        entry_high = nearest_support * 1.008
        return {
            "status": "placeable",
            "setup_type": "breakdown_retest_short",
            "entry_zone": [round_price(entry_low, "up"), round_price(entry_high, "up")],
            "reason": "价格跌破关键支撑后等待反抽失败。",
            "invalid_above": round_price(nearest_support * 1.018, "up")
        }

    weak_below_ma = price < ma7 and price < ma14
    if trend4h != "下降趋势" and not weak_below_ma:
        return {
            "status": "wait",
            "reason": "短线空头确认不足，等待反弹压力或跌破支撑后再评估。",
            "price": price
        }

    above_zones = [
        zone for zone in zones
        if float(zone.get("high", 0)) > price
    ]
    if above_zones:
        zone = above_zones[0]
        entry_low = max(float(zone["low"]), price * 1.002)
        entry_high = max(float(zone["high"]), entry_low * 1.006)
    elif resistances:
        entry_low = max(resistances[0], price * 1.003)
        entry_high = max(resistances[-1], entry_low * 1.01)
    else:
        entry_low = price * 1.006
        entry_high = price * 1.018

    return {
        "status": "placeable",
        "setup_type": "rebound_failure_short",
        "entry_zone": [round_price(entry_low, "up"), round_price(entry_high, "up")],
        "reason": "4h/均线结构偏弱，等待反弹到压力区承压。",
        "invalid_above": round_price(entry_high * 1.012, "up")
    }


def split_contracts(total_contracts):
    first = math.floor(total_contracts * 0.5)
    second = math.floor(total_contracts * 0.3)
    third = total_contracts - first - second
    parts = [first, second, third]
    return [int(part) for part in parts if part > 0]


def build_short_plan(state, analysis, risk_pct, leverage):
    validate_leverage(leverage)
    if risk_pct <= 0 or risk_pct > MAX_RISK_PCT:
        raise PaperBotError(f"risk_pct must be > 0 and <= {MAX_RISK_PCT}.")

    setup = choose_short_setup(analysis)
    if setup["status"] != "placeable":
        return {
            "ok": True,
            "status": setup["status"],
            "reason": setup["reason"],
            "analysis": {
                "price": analysis["price"]["current"],
                "provider": analysis["data_source"]["provider"],
                "timestamp": analysis["timestamp"]
            }
        }

    entry_low, entry_high = setup["entry_zone"]
    raw_entries = [
        short_psych_price(entry_low, 111),
        short_psych_price((entry_low + entry_high) / 2, 222),
        short_psych_price(entry_high, 333),
    ]
    entry_prices = sorted(set(raw_entries))
    while len(entry_prices) < 3:
        entry_prices.append(round_price(entry_prices[-1] + 111, "up"))
    entry_prices = entry_prices[:3]

    stop_loss = max(setup["invalid_above"], round_price(max(entry_prices) * 1.008, "up"))
    weighted_entry = sum(price * weight for price, weight in zip(entry_prices, [0.5, 0.3, 0.2]))
    stop_distance_pct = (stop_loss - weighted_entry) / weighted_entry
    if stop_distance_pct <= 0:
        raise PaperBotError("invalid stop distance for short plan.")

    equity = float(state["equity"])
    risk_amount = round(equity * risk_pct, 4)
    raw_notional = risk_amount / stop_distance_pct
    max_notional = equity * leverage
    notional = min(raw_notional, max_notional)
    total_contracts = contracts_from_notional(notional, weighted_entry)
    if total_contracts < MIN_VOL:
        raise PaperBotError("calculated contracts below MEXC minVol.")

    notional = notional_from_contracts(total_contracts, weighted_entry)
    required_margin = notional / leverage
    if required_margin > float(state["cash_balance"]):
        raise PaperBotError("required margin exceeds paper cash balance.")
    max_loss = round(notional * stop_distance_pct, 4)

    supports = [float(value) for value in analysis["levels"].get("support", [])]
    price = float(analysis["price"]["current"])
    tp1 = next((support for support in supports if support < weighted_entry), price * 0.985)
    tp2 = supports[1] if len(supports) > 1 and supports[1] < tp1 else weighted_entry * (1 - 2 * stop_distance_pct)
    tp1 = round_price(tp1, "down")
    tp2 = round_price(tp2, "down")
    if tp2 >= tp1:
        tp2 = round_price(tp1 * 0.985, "down")

    contracts_parts = split_contracts(total_contracts)
    weights = [0.5, 0.3, 0.2][:len(contracts_parts)]
    entries = []
    for index, contracts in enumerate(contracts_parts):
        price_i = entry_prices[index]
        entries.append({
            "order_id": f"po_{uuid.uuid4().hex[:12]}",
            "batch": index + 1,
            "weight": weights[index],
            "side": "short",
            "order_type": "limit",
            "price": price_i,
            "contracts": contracts,
            "notional_usdt": round(notional_from_contracts(contracts, price_i), 4),
            "fee_rate": MAKER_FEE_RATE
        })

    plan_id = f"plan_{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    return {
        "ok": True,
        "status": "placeable",
        "plan": {
            "plan_id": plan_id,
            "created_at": utc_now(),
            "expires_at": datetime.fromtimestamp(now + PLAN_EXPIRY_SECONDS, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "exchange": "mexc",
            "symbol": SUPPORTED_SYMBOL,
            "instrument": MEXC_SYMBOL,
            "side": "short",
            "setup_type": setup["setup_type"],
            "reason": setup["reason"],
            "account_equity": round(equity, 4),
            "risk_pct": risk_pct,
            "risk_amount_usdt": risk_amount,
            "max_loss_usdt": max_loss,
            "leverage": leverage,
            "weighted_entry": round_price(weighted_entry),
            "stop_loss": stop_loss,
            "stop_distance_pct": round(stop_distance_pct * 100, 4),
            "notional_usdt": round(notional, 4),
            "required_margin_usdt": round(required_margin, 4),
            "total_contracts": total_contracts,
            "entries": entries,
            "take_profits": [
                {"tp_id": f"tp_{uuid.uuid4().hex[:12]}", "price": tp1, "close_pct": 0.5, "status": "open"},
                {"tp_id": f"tp_{uuid.uuid4().hex[:12]}", "price": tp2, "close_pct": 1.0, "status": "open"}
            ],
            "invalidation": f"1h/4h 收回 {stop_loss} 上方，paper 空单失效。",
            "analysis_snapshot": {
                "timestamp": analysis["timestamp"],
                "provider": analysis["data_source"]["provider"],
                "price": analysis["price"]["current"],
                "ma30_dev_pct": analysis["ma"]["ma30_dev_pct"],
                "structure_4h": analysis["structure_4h"]["trend"],
                "weekly_trend": analysis["weekly"]["trend"],
                "funding_avg_8period_pct": analysis["funding"]["avg_8period_pct"]
            }
        }
    }


def upsert_pending_plan(state, plan):
    state["pending_plans"] = [
        item for item in state.get("pending_plans", [])
        if item.get("plan_id") != plan["plan_id"] and item.get("status") == "pending"
    ]
    stored_plan = dict(plan)
    stored_plan["status"] = "pending"
    state.setdefault("pending_plans", []).append(stored_plan)


def command_init(args):
    balance = float(args.balance)
    if balance <= 0:
        raise PaperBotError("balance must be positive.")
    path = state_path_from_args(args)
    state = initial_state(balance)
    save_state(path, state)
    return {"ok": True, "command": "init", "state_path": str(path), "state": state}


def command_propose(args):
    symbol = normalize_symbol(args.symbol)
    if args.side != "short":
        raise PaperBotError("Paper v1 only supports --side short.")
    path = state_path_from_args(args)
    state = load_state(path)
    expired_items = expire_stale_items(state)

    locked, daily_pnl, lock_amount = is_risk_locked(state)
    if locked:
        append_daily_loss_lock_event(state, daily_pnl, lock_amount)
        save_state(path, state)
        return {
            "ok": True,
            "status": "risk_locked",
            "reason": "日内累计亏损达到 2%，停止生成新计划。",
            "daily_realized_pnl": daily_pnl,
            "lock_amount": lock_amount
        }

    if active_position(state) or active_entry_orders(state) or active_pending_plans(state):
        if expired_items:
            save_state(path, state)
        return {
            "ok": True,
            "status": "wait",
            "reason": "已有持仓、开放入场挂单或待确认草案，v1 不叠加新方向。",
            "expired_items": expired_items
        }

    analysis = run_analyze(symbol)
    result = build_short_plan(state, analysis, args.risk_pct, args.leverage)
    if result.get("status") == "placeable":
        upsert_pending_plan(state, result["plan"])
        save_state(path, state)
    elif expired_items:
        save_state(path, state)
    return result


def command_place(args):
    path = state_path_from_args(args)
    state = load_state(path)
    expire_stale_items(state)
    plan = next(
        (item for item in state.get("pending_plans", []) if item.get("plan_id") == args.plan_id),
        None
    )
    if not plan:
        raise PaperBotError(f"plan_id not found: {args.plan_id}")
    if plan.get("status") != "pending":
        save_state(path, state)
        raise PaperBotError(f"plan is not pending: {args.plan_id}")
    if active_position(state) or active_entry_orders(state):
        raise PaperBotError("existing position or open entry orders detected.")

    open_orders = []
    created_at = utc_now()
    created_at_ms = epoch_ms()
    created_candle_time = current_candle_time_ms(created_at_ms)
    for entry in plan["entries"]:
        order = {
            "order_id": entry["order_id"],
            "plan_id": plan["plan_id"],
            "created_at": created_at,
            "created_at_ms": created_at_ms,
            "created_candle_time": created_candle_time,
            "expires_at": plan["expires_at"],
            "symbol": plan["symbol"],
            "instrument": plan["instrument"],
            "side": plan["side"],
            "order_type": "limit",
            "price": entry["price"],
            "contracts": entry["contracts"],
            "status": "open",
            "reduce_only": False,
            "stop_loss": plan["stop_loss"],
            "take_profits": plan["take_profits"],
            "leverage": plan["leverage"],
            "fee_rate": entry["fee_rate"]
        }
        open_orders.append(order)

    state.setdefault("open_orders", []).extend(open_orders)
    for item in state.get("pending_plans", []):
        if item.get("plan_id") == plan["plan_id"]:
            item["status"] = "placed"
            item["placed_at"] = created_at
    state["last_action"] = "placed"
    save_state(path, state)
    return {
        "ok": True,
        "command": "place",
        "plan_id": plan["plan_id"],
        "open_orders": open_orders
    }


def command_cancel(args):
    path = state_path_from_args(args)
    state = load_state(path)
    expired_items = expire_stale_items(state)
    result = cancel_items(
        state,
        plan_id=getattr(args, "plan_id", None),
        order_id=getattr(args, "order_id", None),
        cancel_all=bool(getattr(args, "all", False)),
    )
    save_state(path, state)
    return {
        "ok": True,
        "command": "cancel",
        "expired_items": expired_items,
        **result
    }


def realized_pnl(side, entry_price, exit_price, contracts):
    quantity_btc = contracts * CONTRACT_SIZE_BTC
    if side == "short":
        return (entry_price - exit_price) * quantity_btc
    return (exit_price - entry_price) * quantity_btc


def close_position(state, position, contracts, exit_price, reason):
    contracts = min(int(contracts), int(position["remaining_contracts"]))
    if contracts <= 0:
        return None
    pnl = realized_pnl(position["side"], position["entry_price"], exit_price, contracts)
    exit_notional = notional_from_contracts(contracts, exit_price)
    fee = exit_notional * TAKER_FEE_RATE
    net_pnl = pnl - fee
    state["cash_balance"] = round(float(state["cash_balance"]) + net_pnl, 8)
    position["remaining_contracts"] = int(position["remaining_contracts"]) - contracts
    position["fees_paid"] = round(float(position.get("fees_paid", 0)) + fee, 8)
    position["realized_pnl"] = round(float(position.get("realized_pnl", 0)) + net_pnl, 8)

    trade = {
        "trade_id": f"tr_{uuid.uuid4().hex[:12]}",
        "position_id": position["position_id"],
        "symbol": position["symbol"],
        "side": position["side"],
        "contracts": contracts,
        "entry_price": position["entry_price"],
        "exit_price": exit_price,
        "gross_pnl": round(pnl, 8),
        "fee": round(fee, 8),
        "realized_pnl": round(net_pnl, 8),
        "reason": reason,
        "closed_at": utc_now()
    }
    state.setdefault("closed_trades", []).append(trade)
    return trade


def fill_entry_order(state, order, candle):
    order_candle_time = order.get("created_candle_time")
    if order_candle_time is not None and int(candle["time"]) <= int(order_candle_time):
        return None

    filled = False
    if order["side"] == "short" and float(candle["high"]) >= float(order["price"]):
        filled = True
    if order["side"] == "long" and float(candle["low"]) <= float(order["price"]):
        filled = True
    if not filled:
        return None

    order["status"] = "filled"
    order["filled_at"] = utc_now()
    order["filled_price"] = order["price"]

    position = active_position(state)
    contracts = int(order["contracts"])
    entry_price = float(order["price"])
    if position:
        old_contracts = int(position["remaining_contracts"])
        new_contracts = old_contracts + contracts
        position["entry_price"] = round(
            (position["entry_price"] * old_contracts + entry_price * contracts) / new_contracts,
            1
        )
        position["remaining_contracts"] = new_contracts
        position["original_contracts"] = int(position["original_contracts"]) + contracts
    else:
        position = {
            "position_id": f"pos_{uuid.uuid4().hex[:12]}",
            "plan_id": order["plan_id"],
            "opened_at": utc_now(),
            "symbol": order["symbol"],
            "instrument": order["instrument"],
            "side": order["side"],
            "entry_price": entry_price,
            "original_contracts": contracts,
            "remaining_contracts": contracts,
            "stop_loss": order["stop_loss"],
            "take_profits": order["take_profits"],
            "leverage": order["leverage"],
            "fees_paid": 0.0,
            "realized_pnl": 0.0
        }
        state.setdefault("positions", []).append(position)
    return order


def process_exits(state, candle):
    position = active_position(state)
    if not position:
        return []

    events = []
    high = float(candle["high"])
    low = float(candle["low"])
    side = position["side"]
    stop_loss = float(position["stop_loss"])

    stop_hit = high >= stop_loss if side == "short" else low <= stop_loss
    if stop_hit:
        plan_id = position.get("plan_id")
        trade = close_position(
            state,
            position,
            int(position["remaining_contracts"]),
            stop_loss,
            "stop_loss"
        )
        if trade:
            events.append(trade)
        cancelled_orders = cancel_open_entries_for_plan(state, plan_id, "position_stopped")
        if cancelled_orders:
            events.append({
                "event_type": "cancel_remaining_entries",
                "reason": "position_stopped",
                "plan_id": plan_id,
                "order_ids": cancelled_orders,
                "created_at": utc_now()
            })
        return events

    for tp in position.get("take_profits", []):
        if tp.get("status") != "open" or int(position["remaining_contracts"]) <= 0:
            continue
        tp_price = float(tp["price"])
        hit = low <= tp_price if side == "short" else high >= tp_price
        if not hit:
            continue

        if float(tp.get("close_pct", 1.0)) >= 1.0:
            contracts = int(position["remaining_contracts"])
        else:
            contracts = max(1, math.floor(int(position["remaining_contracts"]) * float(tp["close_pct"])))
        trade = close_position(state, position, contracts, tp_price, "take_profit")
        tp["status"] = "filled"
        tp["filled_at"] = utc_now()
        if trade:
            events.append(trade)

    if events and not active_position(state):
        plan_id = position.get("plan_id")
        cancelled_orders = cancel_open_entries_for_plan(state, plan_id, "position_closed")
        if cancelled_orders:
            events.append({
                "event_type": "cancel_remaining_entries",
                "reason": "position_closed",
                "plan_id": plan_id,
                "order_ids": cancelled_orders,
                "created_at": utc_now()
            })

    return events


def update_equity_snapshot(state, mark_price):
    unrealized = 0.0
    for position in state.get("positions", []):
        contracts = int(position.get("remaining_contracts", 0))
        if contracts <= 0:
            continue
        unrealized += realized_pnl(position["side"], position["entry_price"], mark_price, contracts)
    equity = float(state["cash_balance"]) + unrealized
    state["equity"] = round(equity, 8)
    state["peak_equity"] = round(max(float(state.get("peak_equity", equity)), equity), 8)
    if state["peak_equity"] > 0:
        drawdown_pct = (state["peak_equity"] - equity) / state["peak_equity"] * 100
        state["max_drawdown_pct"] = round(max(float(state.get("max_drawdown_pct", 0)), drawdown_pct), 4)
    return round(unrealized, 8)


def record_equity_snapshot(state, mark_price, unrealized, source):
    snapshot = {
        "created_at": utc_now(),
        "source": source,
        "equity": state.get("equity"),
        "cash_balance": state.get("cash_balance"),
        "unrealized_pnl": round(float(unrealized), 8),
        "mark_price": round(float(mark_price), 4),
        "open_position_contracts": sum(
            int(position.get("remaining_contracts", 0))
            for position in state.get("positions", [])
            if int(position.get("remaining_contracts", 0)) > 0
        )
    }
    snapshots = state.setdefault("equity_snapshots", [])
    snapshots.append(snapshot)
    if len(snapshots) > 500:
        del snapshots[:-500]
    return snapshot


def performance_summary(state, unrealized=0.0):
    trades = state.get("closed_trades", [])
    realized_values = [float(trade.get("realized_pnl", 0)) for trade in trades]
    total_realized = round(sum(realized_values), 8)
    gross_profit = round(sum(value for value in realized_values if value > 0), 8)
    gross_loss = round(abs(sum(value for value in realized_values if value < 0)), 8)
    wins = sum(1 for value in realized_values if value > 0)
    losses = sum(1 for value in realized_values if value < 0)
    trade_count = len(trades)
    win_rate_pct = round(wins / trade_count * 100, 2) if trade_count else 0.0
    profit_factor = round(gross_profit / gross_loss, 4) if gross_loss > 0 else None
    equity = float(state.get("equity", state.get("cash_balance", 0)))
    peak_equity = float(state.get("peak_equity", equity))
    current_drawdown_pct = round((peak_equity - equity) / peak_equity * 100, 4) if peak_equity > 0 else 0.0
    return {
        "trade_count": trade_count,
        "wins": wins,
        "losses": losses,
        "win_rate_pct": win_rate_pct,
        "gross_profit_usdt": gross_profit,
        "gross_loss_usdt": gross_loss,
        "profit_factor": profit_factor,
        "realized_pnl_usdt": total_realized,
        "unrealized_pnl_usdt": round(float(unrealized), 8),
        "net_pnl_usdt": round(total_realized + float(unrealized), 8),
        "current_drawdown_pct": current_drawdown_pct,
        "max_drawdown_pct": state.get("max_drawdown_pct", 0),
        "equity_snapshots_count": len(state.get("equity_snapshots", [])),
    }


def command_tick(args):
    path = state_path_from_args(args)
    state = load_state(path)
    expired_items = expire_stale_items(state)
    candle = latest_mexc_candle()
    ticker = latest_mexc_ticker()
    mark_price = float(ticker.get("fair_price") or ticker["price"])
    candle_time = int(candle["time"])
    last_processed = state.get("last_processed_candle_time")

    filled_orders = []
    exit_events = []
    tick_status = "processed"
    if last_processed is not None and candle_time <= int(last_processed):
        tick_status = "already_processed"
    else:
        for order in state.get("open_orders", []):
            if order.get("status") != "open" or order.get("reduce_only", False):
                continue
            filled = fill_entry_order(state, order, candle)
            if filled:
                filled_orders.append(filled)
        exit_events = process_exits(state, candle)
        state["last_processed_candle_time"] = candle_time

    unrealized = update_equity_snapshot(state, mark_price)
    last_market_timestamp = state.get("last_market_timestamp")
    should_record_market_snapshot = tick_status == "processed" or ticker.get("timestamp") != last_market_timestamp
    equity_snapshot = None
    if should_record_market_snapshot:
        state.setdefault("funding_snapshots", []).append({
            "created_at": utc_now(),
            "symbol": SUPPORTED_SYMBOL,
            "funding_rate": ticker.get("funding_rate", 0),
            "mark_price": mark_price
        })
        equity_snapshot = record_equity_snapshot(state, mark_price, unrealized, tick_status)
    locked, daily_pnl, lock_amount = is_risk_locked(state)
    if locked:
        append_daily_loss_lock_event(state, daily_pnl, lock_amount)

    state["last_tick_at"] = utc_now()
    state["last_candle_time"] = candle_time
    state["last_market_timestamp"] = ticker.get("timestamp")
    state["last_action"] = tick_status
    save_state(path, state)
    return {
        "ok": True,
        "command": "tick",
        "status": tick_status,
        "candle": candle,
        "ticker": ticker,
        "expired_items": expired_items,
        "filled_orders": filled_orders,
        "exit_events": exit_events,
        "unrealized_pnl": unrealized,
        "equity_snapshot": equity_snapshot,
        "equity": state["equity"],
        "risk_locked": locked
    }


def decorate_orders_with_market(orders, mark_price):
    decorated = []
    for order in orders:
        item = dict(order)
        if mark_price:
            item["distance_to_market_pct"] = round((float(order["price"]) - mark_price) / mark_price * 100, 4)
        decorated.append(item)
    return decorated


def status_payload(state, market=None, market_error=None, expired_items=None):
    active_pos = active_position(state)
    unrealized = 0.0
    mark_price = market.get("fair_price") if market else None
    if mark_price is not None:
        unrealized = update_equity_snapshot(state, mark_price)
    open_orders = [
        order for order in state.get("open_orders", [])
        if order.get("status") == "open"
    ]
    return {
        "ok": True,
        "command": "status",
        "mode": state.get("mode"),
        "exchange": state.get("exchange"),
        "market": market,
        "market_status": market_status(market),
        "market_age_seconds": market_age_seconds(market),
        "market_error": market_error,
        "cash_balance": state.get("cash_balance"),
        "equity": state.get("equity"),
        "unrealized_pnl": unrealized,
        "daily_realized_pnl": daily_realized_pnl(state),
        "max_drawdown_pct": state.get("max_drawdown_pct", 0),
        "performance": performance_summary(state, unrealized),
        "risk_locked": is_risk_locked(state)[0],
        "position": active_pos,
        "open_orders": decorate_orders_with_market(open_orders, mark_price),
        "pending_plans": [
            plan for plan in state.get("pending_plans", [])
            if plan.get("status") == "pending"
        ],
        "closed_trades_count": len(state.get("closed_trades", [])),
        "closed_trades": state.get("closed_trades", [])[-20:],
        "equity_snapshots": state.get("equity_snapshots", [])[-100:],
        "risk_events": state.get("risk_events", [])[-5:],
        "expired_items": expired_items or [],
        "last_tick_at": state.get("last_tick_at"),
        "last_candle_time": state.get("last_candle_time"),
        "last_processed_candle_time": state.get("last_processed_candle_time"),
        "last_market_timestamp": state.get("last_market_timestamp"),
        "last_action": state.get("last_action")
    }


def command_status(args):
    path = state_path_from_args(args)
    state = load_state(path)
    expired_items = expire_stale_items(state)
    market = None
    market_error = None
    if not args.no_market:
        try:
            market = latest_mexc_ticker()
        except PaperBotError as exc:
            market_error = str(exc)
            market = None
    if market is not None:
        state["last_market_timestamp"] = market.get("timestamp")
    payload = status_payload(state, market, market_error, expired_items)
    if expired_items or market is not None:
        save_state(path, state)
    return payload


def build_parser():
    parser = argparse.ArgumentParser(description="BTC MEXC paper futures bot.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init")
    init_parser.add_argument("--balance", type=float, default=DEFAULT_BALANCE)
    init_parser.add_argument("--state-path")
    init_parser.set_defaults(func=command_init)

    propose_parser = subparsers.add_parser("propose")
    propose_parser.add_argument("--symbol", required=True)
    propose_parser.add_argument("--side", required=True, choices=["short"])
    propose_parser.add_argument("--risk-pct", type=float, default=STANDARD_RISK_PCT)
    propose_parser.add_argument("--leverage", type=float, default=MAX_LEVERAGE)
    propose_parser.add_argument("--state-path")
    propose_parser.set_defaults(func=command_propose)

    place_parser = subparsers.add_parser("place")
    place_parser.add_argument("--plan-id", required=True)
    place_parser.add_argument("--state-path")
    place_parser.set_defaults(func=command_place)

    cancel_parser = subparsers.add_parser("cancel")
    cancel_parser.add_argument("--all", action="store_true")
    cancel_parser.add_argument("--plan-id")
    cancel_parser.add_argument("--order-id")
    cancel_parser.add_argument("--state-path")
    cancel_parser.set_defaults(func=command_cancel)

    tick_parser = subparsers.add_parser("tick")
    tick_parser.add_argument("--state-path")
    tick_parser.set_defaults(func=command_tick)

    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--state-path")
    status_parser.add_argument("--no-market", action="store_true")
    status_parser.set_defaults(func=command_status)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        payload = args.func(args)
    except PaperBotError as exc:
        error_exit(str(exc))
    json_print(payload)


if __name__ == "__main__":
    main()
