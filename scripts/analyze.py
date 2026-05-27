#!/usr/bin/env python3
"""
paulwei-crypto 市场分析脚本
获取 Binance USDT-M 永续合约公开行情，并计算 Paul Wei 框架指标。

Usage:
    python analyze.py BTCUSDT
    python analyze.py SOLUSDT

输出：包含所有计算指标的 JSON，供 Claude 格式化。
无需 API Key，仅使用 Binance 公开接口。
"""

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, ProxyHandler, build_opener, getproxies, urlopen


BINANCE_API_BASE = "https://fapi.binance.com/fapi/v1"
OKX_API_BASE = "https://www.okx.com/api/v5"
BYBIT_API_BASE = "https://api.bybit.com/v5"
MEXC_API_BASE = "https://contract.mexc.com/api/v1"
BITGET_API_BASE = "https://api.bitget.com/api/v2"
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}USDT$")
DEFAULT_PROVIDERS = ("mexc", "bitget", "binance", "okx", "bybit")


def env_float(name, default):
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    try:
        value = float(raw_value)
    except ValueError:
        return default
    return value if value > 0 else default


MARKET_REQUEST_TIMEOUT = env_float("PAULWEI_MARKET_REQUEST_TIMEOUT", 2.5)
MARKET_ROUTE_TIMEOUT = env_float("PAULWEI_MARKET_ROUTE_TIMEOUT", 4.5)
MARKET_PROXY_MODE = os.environ.get("PAULWEI_MARKET_PROXY_MODE", "direct").strip().lower()
MARKET_HTTP_CLIENT = os.environ.get("PAULWEI_MARKET_HTTP_CLIENT", "curl").strip().lower()
DIRECT_OPENER = build_opener(ProxyHandler({}))


class DataFetchError(Exception):
    """行情数据获取或校验失败。"""


def error_exit(message):
    print(json.dumps({"error": message}, ensure_ascii=False))
    sys.exit(1)


def normalize_symbol(raw_symbol):
    """只允许 Binance USDT-M 合约 symbol，禁止 query 污染和 shell 特殊字符。"""
    symbol = raw_symbol.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValueError(
            "Invalid symbol format. Use a Binance USDT-M symbol like BTCUSDT; "
            "only A-Z, 0-9, and USDT suffix are allowed."
        )
    return symbol


def parse_json_body(provider, body):
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise DataFetchError(f"{provider} returned a non-JSON response.") from exc


def proxy_summary():
    """输出当前进程可见的代理配置摘要，避免泄露代理认证信息。"""
    proxies = getproxies()
    visible_env = [
        name for name in (
            "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY",
            "https_proxy", "http_proxy", "all_proxy"
        )
        if os.environ.get(name)
    ]
    if not proxies:
        return "no proxy environment variables detected"
    schemes = ", ".join(sorted(proxies.keys()))
    env_names = ", ".join(visible_env) if visible_env else "system proxy detected"
    return f"proxy schemes visible to Python: {schemes}; env: {env_names}"


def format_http_error(provider, endpoint, status_code, body):
    msg = body.strip()
    try:
        payload = json.loads(body)
        msg = payload.get("msg") or msg
    except json.JSONDecodeError:
        pass

    if status_code == 451:
        return (
            f"{provider} public market API is unavailable from the current location "
            "(HTTP 451). Do not bypass regional restrictions; use a compliant "
            "market-data source before making any trading decision. "
            f"Proxy diagnostics: {proxy_summary()}."
        )
    if status_code == 403:
        return f"{provider} rejected the request for {endpoint} (HTTP 403): {msg}"
    if status_code == 429:
        return f"{provider} rate limited the request for {endpoint} (HTTP 429): {msg}"
    if status_code >= 500:
        return f"{provider} server error for {endpoint} (HTTP {status_code}): {msg}"
    return f"{provider} request failed for {endpoint} (HTTP {status_code}): {msg}"


def http_get_body_with_curl(provider, endpoint, url, timeout):
    """使用 curl 快速请求，避免 urllib 在部分本机代理/IPv6 环境下长时间卡住。"""
    if not shutil.which("curl"):
        raise DataFetchError("curl is not available")

    command = [
        "curl", "-sS", "--compressed",
        "--max-time", str(timeout),
        "-A", "paulwei-crypto-skill/1.0",
        "-w", "\n%{http_code}",
    ]
    if MARKET_PROXY_MODE == "direct":
        command.extend(["--noproxy", "*"])
    elif MARKET_PROXY_MODE != "system":
        raise DataFetchError("Invalid PAULWEI_MARKET_PROXY_MODE. Use 'direct' or 'system'.")
    command.append(url)

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout + 0.8,
            check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise DataFetchError(f"{provider} timed out while fetching {endpoint}.") from exc

    stdout = completed.stdout or ""
    if "\n" not in stdout:
        reason = (completed.stderr or "").strip() or f"curl exit code {completed.returncode}"
        raise DataFetchError(f"{provider} network error while fetching {endpoint}: {reason}")

    body, status_text = stdout.rsplit("\n", 1)
    try:
        status_code = int(status_text)
    except ValueError as exc:
        raise DataFetchError(f"{provider} returned an invalid HTTP status: {status_text}") from exc

    if completed.returncode != 0:
        reason = (completed.stderr or "").strip() or f"curl exit code {completed.returncode}"
        if status_code >= 400:
            raise DataFetchError(format_http_error(provider, endpoint, status_code, body))
        raise DataFetchError(f"{provider} network error while fetching {endpoint}: {reason}")

    if status_code >= 400:
        raise DataFetchError(format_http_error(provider, endpoint, status_code, body))
    return body


def http_get_body_with_urllib(provider, endpoint, url, timeout):
    """使用 Python urllib 请求，保留为无 curl 环境的后备路径。"""
    req = Request(url, headers={"User-Agent": "paulwei-crypto-skill/1.0"})
    try:
        if MARKET_PROXY_MODE == "system":
            response_context = urlopen(req, timeout=timeout)
        elif MARKET_PROXY_MODE == "direct":
            response_context = DIRECT_OPENER.open(req, timeout=timeout)
        else:
            raise DataFetchError("Invalid PAULWEI_MARKET_PROXY_MODE. Use 'direct' or 'system'.")
        with response_context as response:
            return response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise DataFetchError(format_http_error(provider, endpoint, exc.code, body)) from exc
    except URLError as exc:
        raise DataFetchError(f"{provider} network error while fetching {endpoint}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise DataFetchError(f"{provider} timed out while fetching {endpoint}.") from exc

def http_get_json(provider, base_url, endpoint, request_timeout=None, **params):
    """通过公开行情接口获取 JSON 数据。"""
    query = urlencode(params)
    url = f"{base_url}/{endpoint}?{query}" if query else f"{base_url}/{endpoint}"
    timeout = request_timeout or MARKET_REQUEST_TIMEOUT

    if MARKET_HTTP_CLIENT == "curl":
        try:
            body = http_get_body_with_curl(provider, endpoint, url, timeout)
        except DataFetchError as exc:
            if "curl is not available" not in str(exc):
                raise
            body = http_get_body_with_urllib(provider, endpoint, url, timeout)
    elif MARKET_HTTP_CLIENT == "urllib":
        body = http_get_body_with_urllib(provider, endpoint, url, timeout)
    else:
        raise DataFetchError("Invalid PAULWEI_MARKET_HTTP_CLIENT. Use 'curl' or 'urllib'.")

    return parse_json_body(provider, body)


def fetch_binance(endpoint, request_timeout=None, **params):
    """通过 Binance USDT-M 公开行情接口获取 JSON 数据。"""
    data = http_get_json(
        "Binance", BINANCE_API_BASE, endpoint,
        request_timeout=request_timeout, **params
    )
    if isinstance(data, dict) and "code" in data:
        code = data.get("code")
        msg = data.get("msg", "")
        symbol = params.get("symbol", "symbol")
        if code == -1121 or "Invalid symbol" in msg:
            raise DataFetchError(
                f"{symbol} not found on Binance USDT-M futures. Check symbol spelling."
            )
        raise DataFetchError(f"Binance API error for {endpoint}: code={code}, msg={msg}")
    return data


def fetch_okx(endpoint, request_timeout=None, **params):
    """通过 OKX SWAP 公开行情接口获取 data 字段。"""
    payload = http_get_json(
        "OKX", OKX_API_BASE, endpoint,
        request_timeout=request_timeout, **params
    )
    if not isinstance(payload, dict):
        raise DataFetchError(f"OKX response for {endpoint} is malformed.")

    code = payload.get("code")
    msg = payload.get("msg", "")
    if code != "0":
        if code == "51001":
            inst_id = params.get("instId", "instrument")
            raise DataFetchError(f"{inst_id} not found on OKX SWAP market.")
        raise DataFetchError(f"OKX API error for {endpoint}: code={code}, msg={msg}")

    data = payload.get("data")
    if not isinstance(data, list):
        raise DataFetchError(f"OKX response for {endpoint} is missing data.")
    return data


def fetch_bybit(endpoint, request_timeout=None, **params):
    """通过 Bybit USDT linear 公共行情接口获取 result 字段。"""
    payload = http_get_json(
        "Bybit", BYBIT_API_BASE, endpoint,
        request_timeout=request_timeout, **params
    )
    if not isinstance(payload, dict):
        raise DataFetchError(f"Bybit response for {endpoint} is malformed.")

    code = payload.get("retCode")
    msg = payload.get("retMsg", "")
    if code != 0:
        symbol = params.get("symbol", "symbol")
        if code in (10001, 10029) or "symbol" in msg.lower():
            raise DataFetchError(f"{symbol} not found on Bybit USDT linear market.")
        raise DataFetchError(f"Bybit API error for {endpoint}: code={code}, msg={msg}")

    result = payload.get("result")
    if not isinstance(result, dict):
        raise DataFetchError(f"Bybit response for {endpoint} is missing result.")
    return result


def fetch_mexc(endpoint, request_timeout=None, **params):
    """通过 MEXC USDT 永续公共行情接口获取 data 字段。"""
    payload = http_get_json(
        "MEXC", MEXC_API_BASE, endpoint,
        request_timeout=request_timeout, **params
    )
    if not isinstance(payload, dict):
        raise DataFetchError(f"MEXC response for {endpoint} is malformed.")

    success = payload.get("success")
    code = payload.get("code")
    message = payload.get("message") or payload.get("msg") or ""
    if success is not True or code not in (0, "0", None):
        raise DataFetchError(f"MEXC API error for {endpoint}: code={code}, msg={message}")

    if "data" not in payload:
        raise DataFetchError(f"MEXC response for {endpoint} is missing data.")
    return payload["data"]


def fetch_bitget(endpoint, request_timeout=None, **params):
    """通过 Bitget USDT futures 公共行情接口获取 data 字段。"""
    payload = http_get_json(
        "Bitget", BITGET_API_BASE, endpoint,
        request_timeout=request_timeout, **params
    )
    if not isinstance(payload, dict):
        raise DataFetchError(f"Bitget response for {endpoint} is malformed.")

    code = payload.get("code")
    msg = payload.get("msg", "")
    if code != "00000":
        raise DataFetchError(f"Bitget API error for {endpoint}: code={code}, msg={msg}")

    if "data" not in payload:
        raise DataFetchError(f"Bitget response for {endpoint} is missing data.")
    return payload["data"]


def okx_inst_id(symbol):
    """将 BTCUSDT 转换为 OKX SWAP 的 BTC-USDT-SWAP。"""
    base = symbol[:-4]
    return f"{base}-USDT-SWAP"


def mexc_symbol(symbol):
    """将 BTCUSDT 转换为 MEXC 永续合约 BTC_USDT。"""
    return f"{symbol[:-4]}_USDT"


def normalize_okx_candles(rows):
    """将 OKX K 线转换为脚本内部使用的 Binance K 线形状。"""
    normalized = []
    for row in rows:
        if len(row) < 6:
            raise DataFetchError("OKX candle response contains malformed rows.")
        ts, open_, high, low, close, volume = row[:6]
        normalized.append([int(ts), open_, high, low, close, volume])
    normalized.sort(key=lambda row: row[0])
    return normalized


def normalize_bybit_candles(rows):
    """将 Bybit K 线转换为脚本内部使用的 Binance K 线形状。"""
    normalized = []
    for row in rows:
        if len(row) < 6:
            raise DataFetchError("Bybit candle response contains malformed rows.")
        ts, open_, high, low, close, volume = row[:6]
        normalized.append([int(ts), open_, high, low, close, volume])
    normalized.sort(key=lambda row: row[0])
    return normalized


def normalize_mexc_candles(data):
    """将 MEXC K 线字典转换为脚本内部使用的 Binance K 线形状。"""
    if not isinstance(data, dict):
        raise DataFetchError("MEXC candle response is malformed.")
    required = ["time", "open", "high", "low", "close", "vol"]
    missing = [key for key in required if key not in data or not isinstance(data[key], list)]
    if missing:
        raise DataFetchError(f"MEXC candle response is missing fields: {', '.join(missing)}")

    lengths = [len(data[key]) for key in required]
    if not lengths or min(lengths) != max(lengths):
        raise DataFetchError("MEXC candle response contains inconsistent array lengths.")

    normalized = []
    for ts, open_, high, low, close, volume in zip(
        data["time"], data["open"], data["high"], data["low"], data["close"], data["vol"]
    ):
        normalized.append([int(ts) * 1000, open_, high, low, close, volume])
    normalized.sort(key=lambda row: row[0])
    return normalized


def normalize_bitget_candles(rows):
    """将 Bitget K 线转换为脚本内部使用的 Binance K 线形状。"""
    normalized = []
    for row in rows:
        if len(row) < 6:
            raise DataFetchError("Bitget candle response contains malformed rows.")
        ts, open_, high, low, close, volume = row[:6]
        normalized.append([int(ts), open_, high, low, close, volume])
    normalized.sort(key=lambda row: row[0])
    return normalized


def fetch_market_data_binance(symbol, request_timeout=None):
    """获取 Binance USDT-M 行情，并统一成内部数据结构。"""
    klines_1d = require_list(
        "daily klines",
        fetch_binance("klines", request_timeout=request_timeout, symbol=symbol, interval="1d", limit=90),
        30
    )
    klines_4h = require_list(
        "4h klines",
        fetch_binance("klines", request_timeout=request_timeout, symbol=symbol, interval="4h", limit=60),
        20
    )
    klines_1w = require_list(
        "weekly klines",
        fetch_binance("klines", request_timeout=request_timeout, symbol=symbol, interval="1w", limit=30),
        1
    )
    ticker = require_dict_fields(
        "24hr ticker",
        fetch_binance("ticker/24hr", request_timeout=request_timeout, symbol=symbol),
        ["lastPrice", "priceChangePercent", "volume"]
    )
    funding = require_list(
        "funding rate",
        fetch_binance("fundingRate", request_timeout=request_timeout, symbol=symbol, limit=8),
        0
    )
    return {
        "source": "binance",
        "instrument": symbol,
        "klines_1d": klines_1d,
        "klines_4h": klines_4h,
        "klines_1w": klines_1w,
        "ticker": ticker,
        "funding": funding,
        "fallback_reason": None
    }


def fetch_market_data_okx(symbol, fallback_reason=None, request_timeout=None):
    """获取 OKX SWAP 行情，并统一成内部数据结构。"""
    inst_id = okx_inst_id(symbol)
    candles_1d = require_list(
        "OKX daily candles",
        normalize_okx_candles(fetch_okx(
            "market/candles", request_timeout=request_timeout,
            instId=inst_id, bar="1D", limit=90
        )),
        30
    )
    candles_4h = require_list(
        "OKX 4h candles",
        normalize_okx_candles(fetch_okx(
            "market/candles", request_timeout=request_timeout,
            instId=inst_id, bar="4H", limit=60
        )),
        20
    )
    candles_1w = require_list(
        "OKX weekly candles",
        normalize_okx_candles(fetch_okx(
            "market/candles", request_timeout=request_timeout,
            instId=inst_id, bar="1W", limit=30
        )),
        1
    )

    ticker_rows = require_list(
        "OKX ticker",
        fetch_okx("market/ticker", request_timeout=request_timeout, instId=inst_id),
        1
    )
    ticker_row = require_dict_fields(
        "OKX ticker",
        ticker_rows[0],
        ["last", "open24h", "vol24h"]
    )
    last = float(ticker_row["last"])
    open24h = float(ticker_row["open24h"])
    change_pct = (last - open24h) / open24h * 100 if open24h else 0
    ticker = {
        "lastPrice": ticker_row["last"],
        "priceChangePercent": str(change_pct),
        "volume": ticker_row["vol24h"]
    }

    funding_rows = fetch_okx(
        "public/funding-rate-history", request_timeout=request_timeout,
        instId=inst_id, limit=8
    )
    funding_rows.sort(key=lambda row: int(row.get("fundingTime", "0")))
    funding = [
        {"fundingRate": row.get("fundingRate") or row.get("realizedRate") or "0"}
        for row in funding_rows
    ]

    return {
        "source": "okx",
        "instrument": inst_id,
        "klines_1d": candles_1d,
        "klines_4h": candles_4h,
        "klines_1w": candles_1w,
        "ticker": ticker,
        "funding": funding,
        "fallback_reason": fallback_reason
    }


def fetch_market_data_bybit(symbol, fallback_reason=None, request_timeout=None):
    """获取 Bybit USDT linear 行情，并统一成内部数据结构。"""
    candles_1d_result = fetch_bybit(
        "market/kline", request_timeout=request_timeout,
        category="linear", symbol=symbol, interval="D", limit=90
    )
    candles_4h_result = fetch_bybit(
        "market/kline", request_timeout=request_timeout,
        category="linear", symbol=symbol, interval="240", limit=60
    )
    candles_1w_result = fetch_bybit(
        "market/kline", request_timeout=request_timeout,
        category="linear", symbol=symbol, interval="W", limit=30
    )

    candles_1d = require_list(
        "Bybit daily candles",
        normalize_bybit_candles(candles_1d_result.get("list", [])),
        30
    )
    candles_4h = require_list(
        "Bybit 4h candles",
        normalize_bybit_candles(candles_4h_result.get("list", [])),
        20
    )
    candles_1w = require_list(
        "Bybit weekly candles",
        normalize_bybit_candles(candles_1w_result.get("list", [])),
        1
    )

    ticker_result = fetch_bybit(
        "market/tickers", request_timeout=request_timeout,
        category="linear", symbol=symbol
    )
    ticker_rows = require_list("Bybit ticker", ticker_result.get("list", []), 1)
    ticker_row = require_dict_fields(
        "Bybit ticker",
        ticker_rows[0],
        ["lastPrice", "price24hPcnt", "volume24h"]
    )
    change_pct = float(ticker_row["price24hPcnt"]) * 100
    ticker = {
        "lastPrice": ticker_row["lastPrice"],
        "priceChangePercent": str(change_pct),
        "volume": ticker_row["volume24h"]
    }

    funding_result = fetch_bybit(
        "market/funding/history", request_timeout=request_timeout,
        category="linear", symbol=symbol, limit=8
    )
    funding_rows = funding_result.get("list", [])
    if not isinstance(funding_rows, list):
        raise DataFetchError("Bybit funding response is malformed.")
    funding_rows.sort(key=lambda row: int(row.get("fundingRateTimestamp", "0")))
    funding = [{"fundingRate": row.get("fundingRate") or "0"} for row in funding_rows]

    return {
        "source": "bybit",
        "instrument": symbol,
        "klines_1d": candles_1d,
        "klines_4h": candles_4h,
        "klines_1w": candles_1w,
        "ticker": ticker,
        "funding": funding,
        "fallback_reason": fallback_reason
    }


def fetch_market_data_mexc(symbol, fallback_reason=None, request_timeout=None):
    """获取 MEXC USDT 永续行情，并统一成内部数据结构。"""
    inst_id = mexc_symbol(symbol)
    raw = fetch_tasks_parallel("MEXC", {
        "daily candles": lambda: fetch_mexc(
            f"contract/kline/{inst_id}", request_timeout=request_timeout,
            interval="Day1", limit=90
        ),
        "4h candles": lambda: fetch_mexc(
            f"contract/kline/{inst_id}", request_timeout=request_timeout,
            interval="Hour4", limit=60
        ),
        "weekly candles": lambda: fetch_mexc(
            f"contract/kline/{inst_id}", request_timeout=request_timeout,
            interval="Week1", limit=30
        ),
        "ticker": lambda: fetch_mexc(
            "contract/ticker", request_timeout=request_timeout, symbol=inst_id
        ),
        "funding": lambda: fetch_mexc(
            "contract/funding_rate/history", request_timeout=request_timeout,
            symbol=inst_id, page_num=1, page_size=8
        ),
    }, request_timeout=request_timeout)

    candles_1d = require_list(
        "MEXC daily candles",
        normalize_mexc_candles(raw["daily candles"]),
        30
    )
    candles_4h = require_list(
        "MEXC 4h candles",
        normalize_mexc_candles(raw["4h candles"]),
        20
    )
    candles_1w = require_list(
        "MEXC weekly candles",
        normalize_mexc_candles(raw["weekly candles"]),
        1
    )

    ticker = require_dict_fields(
        "MEXC ticker",
        raw["ticker"],
        ["lastPrice", "riseFallRate", "volume24"]
    )
    unified_ticker = {
        "lastPrice": str(ticker["lastPrice"]),
        "priceChangePercent": str(float(ticker["riseFallRate"]) * 100),
        "volume": str(ticker["volume24"])
    }

    funding_data = raw["funding"]
    funding_rows = funding_data.get("resultList", []) if isinstance(funding_data, dict) else []
    if not isinstance(funding_rows, list):
        raise DataFetchError("MEXC funding response is malformed.")
    funding_rows.sort(key=lambda row: int(row.get("settleTime", "0")))
    funding = [{"fundingRate": str(row.get("fundingRate", "0"))} for row in funding_rows]

    return {
        "source": "mexc",
        "instrument": inst_id,
        "klines_1d": candles_1d,
        "klines_4h": candles_4h,
        "klines_1w": candles_1w,
        "ticker": unified_ticker,
        "funding": funding,
        "fallback_reason": fallback_reason
    }


def fetch_market_data_bitget(symbol, fallback_reason=None, request_timeout=None):
    """获取 Bitget USDT futures 行情，并统一成内部数据结构。"""
    product_type = "usdt-futures"
    raw = fetch_tasks_parallel("Bitget", {
        "daily candles": lambda: fetch_bitget(
            "mix/market/candles", request_timeout=request_timeout,
            symbol=symbol, productType=product_type, granularity="1D", limit=90
        ),
        "4h candles": lambda: fetch_bitget(
            "mix/market/candles", request_timeout=request_timeout,
            symbol=symbol, productType=product_type, granularity="4H", limit=60
        ),
        "weekly candles": lambda: fetch_bitget(
            "mix/market/candles", request_timeout=request_timeout,
            symbol=symbol, productType=product_type, granularity="1W", limit=30
        ),
        "ticker": lambda: fetch_bitget(
            "mix/market/ticker", request_timeout=request_timeout,
            symbol=symbol, productType=product_type
        ),
        "funding": lambda: fetch_bitget(
            "mix/market/history-fund-rate", request_timeout=request_timeout,
            symbol=symbol, productType=product_type, pageSize=8
        ),
    }, request_timeout=request_timeout)

    candles_1d = require_list(
        "Bitget daily candles",
        normalize_bitget_candles(raw["daily candles"]),
        30
    )
    candles_4h = require_list(
        "Bitget 4h candles",
        normalize_bitget_candles(raw["4h candles"]),
        20
    )
    candles_1w = require_list(
        "Bitget weekly candles",
        normalize_bitget_candles(raw["weekly candles"]),
        1
    )

    ticker_rows = require_list(
        "Bitget ticker",
        raw["ticker"],
        1
    )
    ticker_row = require_dict_fields(
        "Bitget ticker",
        ticker_rows[0],
        ["lastPr", "change24h", "baseVolume"]
    )
    unified_ticker = {
        "lastPrice": ticker_row["lastPr"],
        "priceChangePercent": str(float(ticker_row["change24h"]) * 100),
        "volume": ticker_row["baseVolume"]
    }

    funding_rows = raw["funding"]
    if not isinstance(funding_rows, list):
        raise DataFetchError("Bitget funding response is malformed.")
    funding_rows.sort(key=lambda row: int(row.get("fundingTime", "0")))
    funding = [{"fundingRate": row.get("fundingRate") or "0"} for row in funding_rows]

    return {
        "source": "bitget",
        "instrument": symbol,
        "klines_1d": candles_1d,
        "klines_4h": candles_4h,
        "klines_1w": candles_1w,
        "ticker": unified_ticker,
        "funding": funding,
        "fallback_reason": fallback_reason
    }


MARKET_PROVIDER_FETCHERS = {
    "mexc": fetch_market_data_mexc,
    "bitget": fetch_market_data_bitget,
    "binance": fetch_market_data_binance,
    "okx": fetch_market_data_okx,
    "bybit": fetch_market_data_bybit,
}


def enabled_market_providers():
    raw_providers = os.environ.get("PAULWEI_MARKET_PROVIDERS")
    if not raw_providers:
        return list(DEFAULT_PROVIDERS)

    providers = []
    invalid = []
    for item in raw_providers.split(","):
        name = item.strip().lower()
        if not name:
            continue
        if name not in MARKET_PROVIDER_FETCHERS:
            invalid.append(name)
            continue
        if name not in providers:
            providers.append(name)

    if invalid:
        raise DataFetchError(
            "Invalid PAULWEI_MARKET_PROVIDERS entries: " + ", ".join(invalid)
        )
    if not providers:
        raise DataFetchError("PAULWEI_MARKET_PROVIDERS did not contain any valid providers.")
    return providers


def route_reason(selected_provider, errors, pending):
    parts = [f"Fastest routing selected {selected_provider}; this is not a sequential fallback."]
    if errors:
        failed = "; ".join(f"{name}: {message}" for name, message in sorted(errors.items()))
        parts.append(f"Completed failures before selection: {failed}.")
    if pending:
        parts.append(f"Still pending when selected: {', '.join(pending)}.")
    return " ".join(parts)


def fetch_market_data(symbol):
    """并发竞速多个合规公共行情源，返回最快的完整有效结果。"""
    providers = enabled_market_providers()
    result_queue = queue.Queue()
    started_at = time.monotonic()
    errors = {}

    def worker(provider_name):
        provider_started = time.monotonic()
        try:
            market = MARKET_PROVIDER_FETCHERS[provider_name](
                symbol,
                request_timeout=MARKET_REQUEST_TIMEOUT
            )
            elapsed_ms = round((time.monotonic() - provider_started) * 1000)
            result_queue.put(("success", provider_name, market, elapsed_ms, None))
        except Exception as exc:  # noqa: BLE001 - 路由层必须聚合所有源失败原因。
            elapsed_ms = round((time.monotonic() - provider_started) * 1000)
            result_queue.put(("error", provider_name, None, elapsed_ms, str(exc)))

    for provider_name in providers:
        thread = threading.Thread(target=worker, args=(provider_name,), daemon=True)
        thread.start()

    remaining = len(providers)
    deadline = started_at + MARKET_ROUTE_TIMEOUT
    while remaining > 0 and time.monotonic() < deadline:
        wait_seconds = max(0.05, min(0.25, deadline - time.monotonic()))
        try:
            status, provider_name, market, elapsed_ms, message = result_queue.get(
                timeout=wait_seconds
            )
        except queue.Empty:
            continue

        remaining -= 1
        if status == "success":
            pending = [
                name for name in providers
                if name != provider_name and name not in errors
            ]
            if provider_name != "binance" or errors or pending:
                market["fallback_reason"] = route_reason(provider_name, errors, pending)
            market["routing"] = {
                "strategy": "fastest_first_success",
                "providers": providers,
                "selected": provider_name,
                "elapsed_ms": round((time.monotonic() - started_at) * 1000),
                "provider_elapsed_ms": elapsed_ms,
                "request_timeout_sec": MARKET_REQUEST_TIMEOUT,
                "route_timeout_sec": MARKET_ROUTE_TIMEOUT,
                "proxy_mode": MARKET_PROXY_MODE,
                "http_client": MARKET_HTTP_CLIENT,
                "failed_providers": errors,
                "pending_providers": pending
            }
            return market

        errors[provider_name] = message

    pending = [name for name in providers if name not in errors]
    failures = "; ".join(f"{name}: {message}" for name, message in sorted(errors.items()))
    if pending:
        failures = f"{failures}; pending/timed out: {', '.join(pending)}" if failures else (
            f"pending/timed out: {', '.join(pending)}"
        )
    raise DataFetchError(
        "All market data routes failed or timed out within "
        f"{MARKET_ROUTE_TIMEOUT}s. {failures}"
    )


def require_list(name, data, min_len=1):
    if not isinstance(data, list) or len(data) < min_len:
        raise DataFetchError(f"{name} response is empty or malformed.")
    return data


def require_dict_fields(name, data, fields):
    if not isinstance(data, dict):
        raise DataFetchError(f"{name} response is malformed.")
    missing = [field for field in fields if field not in data]
    if missing:
        raise DataFetchError(f"{name} response is missing fields: {', '.join(missing)}")
    return data


def fetch_tasks_parallel(provider, tasks, request_timeout=None):
    """并发获取同一 provider 的多个接口，减少完整指标等待时间。"""
    if not tasks:
        return {}

    timeout = (request_timeout or MARKET_REQUEST_TIMEOUT) + 1.0
    results = {}
    with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
        futures = {executor.submit(task): name for name, task in tasks.items()}
        try:
            for future in as_completed(futures, timeout=timeout):
                name = futures[future]
                try:
                    results[name] = future.result()
                except Exception as exc:  # noqa: BLE001 - 需要保留接口名以便定位。
                    raise DataFetchError(f"{provider} {name} request failed: {exc}") from exc
        except FuturesTimeoutError as exc:
            pending = [name for future, name in futures.items() if not future.done()]
            raise DataFetchError(
                f"{provider} parallel requests timed out: {', '.join(pending)}"
            ) from exc

    return results


def ma(closes, n):
    if len(closes) < n:
        return sum(closes) / len(closes)  # 数据不足时使用已有样本
    return sum(closes[-n:]) / n


def atr14(candles):
    trs = []
    for i in range(1, len(candles)):
        h = float(candles[i][2])
        l = float(candles[i][3])
        pc = float(candles[i - 1][4])
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < 14:
        return None
    return sum(trs[-14:]) / 14


def find_pivots(candles, window=2):
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    res, sup = [], []
    for i in range(window, len(candles) - window):
        if all(highs[i] > highs[j] for j in range(i - window, i + window + 1) if j != i):
            res.append(round(highs[i], 4))
        if all(lows[i] < lows[j] for j in range(i - window, i + window + 1) if j != i):
            sup.append(round(lows[i], 4))
    return res, sup


def trend_4h(candles_4h):
    if len(candles_4h) < 20:
        return "横盘震荡"
    recent = candles_4h[-20:]
    mid = len(recent) // 2
    highs = [float(c[2]) for c in recent]
    lows = [float(c[3]) for c in recent]
    fh, lh = max(highs[:mid]), max(highs[mid:])
    fl, ll = min(lows[:mid]), min(lows[mid:])
    if lh > fh and ll > fl:
        return "上升趋势"
    if lh < fh and ll < fl:
        return "下降趋势"
    return "横盘震荡"


def weekly_trend(klines_1w):
    """根据最近 8 根周线推断周线趋势。"""
    if len(klines_1w) < 8:
        return "横盘"
    recent = klines_1w[-8:]
    mid = len(recent) // 2
    closes = [float(c[4]) for c in recent]
    highs = [float(c[2]) for c in recent]
    lows = [float(c[3]) for c in recent]
    fh, lh = max(highs[:mid]), max(highs[mid:])
    fl, ll = min(lows[:mid]), min(lows[mid:])
    if lh > fh and ll > fl:
        return "上升"
    if lh < fh and ll < fl:
        return "下降"
    return "横盘"


def key_zone_4h(candles_4h, price):
    bucket = price * 0.005
    counts = {}
    for c in candles_4h:
        lb = int(float(c[3]) / bucket)
        hb = int(float(c[2]) / bucket)
        for b in range(lb, hb + 1):
            counts[b] = counts.get(b, 0) + 1
    zones = []
    for b, n in sorted(counts.items(), key=lambda x: -x[1]):
        zl = round(b * bucket, 4)
        zh = round((b + 1) * bucket, 4)
        if abs(zl - price) / price < 0.20:
            zones.append({"low": zl, "high": zh, "touches": n})
        if len(zones) >= 2:
            break
    return zones


def ma30_state(dev_pct):
    if dev_pct > 10:
        return "⚠️ 过热区"
    if dev_pct > 5:
        return "🟡 偏高区"
    if dev_pct > -5:
        return "🟢 均衡区"
    if dev_pct > -10:
        return "🟡 偏低区"
    return "✅ 超跌区"


def psych_levels(price, n=4):
    """
    查找现价上下方最近的心理整数位。
    使用主要和次要两个粒度，例如 BTC 的 10000 和 1000。
    """
    # 根据价格数量级确定整数位粒度。
    if price >= 50000:
        scales = [10000, 5000, 1000]
    elif price >= 10000:
        scales = [5000, 1000, 500]
    elif price >= 1000:
        scales = [500, 100, 50]
    elif price >= 100:
        scales = [50, 10, 5]
    elif price >= 10:
        scales = [5, 1, 0.5]
    elif price >= 1:
        scales = [0.5, 0.1, 0.05]
    else:
        scales = [0.05, 0.01, 0.001]

    seen = set()
    levels = []
    for scale in scales:
        base = round(round(price / scale) * scale, 10)
        candidates = [base - scale, base, base + scale, base + 2 * scale, base - 2 * scale]
        for c in candidates:
            c = round(c, 8)
            if c <= 0 or c in seen:
                continue
            dist_pct = abs(c - price) / price * 100
            if dist_pct < 15:
                seen.add(c)
                tag = "major" if scale == scales[0] else "minor"
                levels.append({
                    "price": c,
                    "dist_pct": round(dist_pct, 2),
                    "side": "above" if c > price else "below",
                    "tag": tag,
                    "interval": scale
                })

    levels.sort(key=lambda x: x["dist_pct"])
    return levels[:n * 2]  # 返回按距离排序后的上下方候选位。


def entry_score(ma30_dev, trend4h, w_trend, avg_funding):
    """
    基于 Paul Wei 框架评估多空关注价值。
    主要驱动：MA30 偏离状态。
    修正因子：4h 趋势、周线趋势、资金费率成本。
    返回 1-10 分、标签和一句风险提示。
    """
    # 多头基础分：分数越高，越接近框架里的多头关注区。
    if ma30_dev < -10:
        long_base = 9    # 超跌区
    elif ma30_dev < -5:
        long_base = 7    # 偏低区
    elif ma30_dev < 5:
        long_base = 5    # 均衡区
    elif ma30_dev < 10:
        long_base = 3    # 偏高区
    else:
        long_base = 1    # 过热区

    # 根据趋势和资金费率修正基础分。
    long_adj = 0
    if trend4h == "上升趋势":
        long_adj += 1
    elif trend4h == "下降趋势":
        long_adj -= 1

    if w_trend == "上升":
        long_adj += 1
    elif w_trend == "下降":
        long_adj -= 1

    if avg_funding < -0.0001:   # 空头付费，多头持仓成本相对低
        long_adj += 1
    elif avg_funding > 0.0003:  # 多头持仓成本偏高
        long_adj -= 1

    long_score = max(1, min(10, long_base + long_adj))
    short_score = max(1, min(10, (10 - long_base + 1) + (-long_adj)))

    def label(s):
        if s >= 8:  return "★★★★★ 强势入场区"
        if s >= 6:  return "★★★★  较优入场区"
        if s >= 4:  return "★★★   可关注等信号"
        if s >= 2:  return "★★    谨慎逆势区"
        return              "★     不宜操作"

    def advice(s, direction):
        if s >= 8:  return f"框架信号较强，可将关注区作为限价{direction}的风险参考"
        if s >= 6:  return f"{direction}条件较好，等待价格回踩关注区后再做风险复核"
        if s >= 4:  return f"{direction}有一定依据，信号尚未完全确认，仓位需小"
        if s >= 2:  return f"当前{direction}属逆势，若操作仓位需极小（≤0.25%账户）"
        return f"当前不适合{direction}，等待更好的结构机会"

    # 输出主要驱动因素，便于审计判断依据。
    factors = []
    state = ma30_state(ma30_dev)
    factors.append(f"MA30 {state}（主要驱动）")
    if trend4h != "横盘震荡":
        factors.append(f"4h {trend4h}")
    if w_trend != "横盘":
        factors.append(f"周线{w_trend}趋势")
    if avg_funding < -0.0001:
        factors.append("资金费率负值（利多方）")
    elif avg_funding > 0.0003:
        factors.append("资金费率偏高（增加多方持仓成本）")

    return {
        "long":  {"score": long_score,  "label": label(long_score),  "advice": advice(long_score, "做多")},
        "short": {"score": short_score, "label": label(short_score), "advice": advice(short_score, "做空")},
        "factors": factors
    }


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: python analyze.py SYMBOL (e.g. BTCUSDT)"}))
        sys.exit(1)

    try:
        symbol = normalize_symbol(sys.argv[1])
    except ValueError as e:
        error_exit(str(e))

    try:
        market = fetch_market_data(symbol)
    except DataFetchError as e:
        error_exit(f"Data fetch failed: {e}")

    klines_1d = market["klines_1d"]
    klines_4h = market["klines_4h"]
    klines_1w = market["klines_1w"]
    ticker    = market["ticker"]
    funding   = market["funding"]

    price    = float(ticker["lastPrice"])
    chg      = float(ticker["priceChangePercent"])
    vol_24h  = float(ticker["volume"])

    # ── 日线指标 ────────────────────────────────────────────────────
    closes = [float(c[4]) for c in klines_1d]
    highs  = [float(c[2]) for c in klines_1d]
    lows   = [float(c[3]) for c in klines_1d]

    m7   = ma(closes, 7)
    m14  = ma(closes, 14)
    m30  = ma(closes, 30)
    atr  = atr14(klines_1d)
    dev30 = (price - m30) / m30 * 100 if m30 else 0

    high30 = max(highs[-30:])
    low30  = min(lows[-30:])

    res, sup = find_pivots(klines_1d[-45:], window=2)
    resistances = sorted([r for r in res if r > price])[:2]
    supports    = sorted([s for s in sup if s < price], reverse=True)[:2]
    if not resistances:
        resistances = [round(high30, 4)]
    if not supports:
        supports = [round(low30, 4)]

    # ── 周线指标 ────────────────────────────────────────────────────
    w_closes = [float(c[4]) for c in klines_1w]
    w_highs  = [float(c[2]) for c in klines_1w]
    w_lows   = [float(c[3]) for c in klines_1w]
    w_ma30   = ma(w_closes, 30)
    w_dev30  = (price - w_ma30) / w_ma30 * 100 if w_ma30 else 0
    w_high8  = max(w_highs[-8:]) if len(w_highs) >= 8 else max(w_highs)
    w_low8   = min(w_lows[-8:])  if len(w_lows)  >= 8 else min(w_lows)
    w_trend  = weekly_trend(klines_1w)

    # ── 4h 结构 ─────────────────────────────────────────────────────
    trend4h = trend_4h(klines_4h)
    zones4h = key_zone_4h(klines_4h, price)

    # ── 资金费率 ────────────────────────────────────────────────────
    rates      = [float(f["fundingRate"]) for f in funding]
    latest_rate = rates[-1] if rates else 0
    avg_rate    = sum(rates) / len(rates) if rates else 0

    if avg_rate > 0.0001:
        funding_desc = "多头持续付费，市场偏乐观，注意过热风险"
    elif avg_rate < -0.0001:
        funding_desc = "空头持续付费，市场偏悲观，可能接近底部"
    else:
        funding_desc = "多空费率接近零，情绪均衡"

    # ── 成交量 ──────────────────────────────────────────────────────
    vols    = [float(c[5]) for c in klines_1d]
    avg_vol = sum(vols[-30:]) / 30 if len(vols) >= 30 else sum(vols) / len(vols)
    vol_ratio  = round(vol_24h / avg_vol, 2) if avg_vol else 1.0
    vol_status = "放量" if vol_ratio > 1.3 else ("缩量" if vol_ratio < 0.7 else "正常")

    # ── 心理整数位 ──────────────────────────────────────────────────
    psych = psych_levels(price, n=4)

    # ── 关注评分 ────────────────────────────────────────────────────
    score = entry_score(dev30, trend4h, w_trend, avg_rate)

    # ── 输出 ────────────────────────────────────────────────────────
    out = {
        "symbol":    symbol,
        "data_source": {
            "provider": market["source"],
            "instrument": market["instrument"],
            "fallback_reason": market["fallback_reason"],
            "routing": market.get("routing")
        },
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "price": {
            "current":        price,
            "change_pct_24h": chg
        },
        "ma": {
            "ma7":          round(m7,  4),
            "ma14":         round(m14, 4),
            "ma30":         round(m30, 4),
            "ma7_dev_pct":  round((price - m7)  / m7  * 100, 2),
            "ma14_dev_pct": round((price - m14) / m14 * 100, 2),
            "ma30_dev_pct": round(dev30, 2),
            "ma30_state":   ma30_state(dev30)
        },
        "range_30d": {
            "high":      round(high30, 4),
            "low":       round(low30,  4),
            "range_pct": round((high30 - low30) / low30 * 100, 1)
        },
        "atr14": {
            "value":        round(atr, 4),
            "pct_of_price": round(atr / price * 100, 2)
        },
        "levels": {
            "resistance": resistances,
            "support":    supports
        },
        "structure_4h": {
            "trend":     trend4h,
            "key_zones": zones4h
        },
        "weekly": {
            "trend":       w_trend,
            "ma30":        round(w_ma30, 4),
            "ma30_dev_pct": round(w_dev30, 2),
            "ma30_state":  ma30_state(w_dev30),
            "range_8w": {
                "high": round(w_high8, 4),
                "low":  round(w_low8,  4)
            }
        },
        "psych_levels": psych,
        "funding": {
            "latest_pct":      round(latest_rate * 100, 4),
            "avg_8period_pct": round(avg_rate    * 100, 4),
            "description":     funding_desc
        },
        "volume": {
            "volume_24h":       round(vol_24h, 2),
            "ratio_vs_30d_avg": vol_ratio,
            "status":           vol_status
        },
        "entry_score": score
    }

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
