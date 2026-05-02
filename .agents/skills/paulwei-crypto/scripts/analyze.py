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
import re
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, getproxies, urlopen


BINANCE_API_BASE = "https://fapi.binance.com/fapi/v1"
OKX_API_BASE = "https://www.okx.com/api/v5"
SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,20}USDT$")


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


def parse_json_body(body):
    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise DataFetchError("Binance returned a non-JSON response.") from exc


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


def http_get_json(provider, base_url, endpoint, **params):
    """通过公开行情接口获取 JSON 数据。"""
    url = f"{base_url}/{endpoint}?{urlencode(params)}"
    req = Request(url, headers={"User-Agent": "paulwei-crypto-skill/1.0"})

    try:
        with urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise DataFetchError(format_http_error(provider, endpoint, exc.code, body)) from exc
    except URLError as exc:
        raise DataFetchError(f"{provider} network error while fetching {endpoint}: {exc.reason}") from exc
    except TimeoutError as exc:
        raise DataFetchError(f"{provider} timed out while fetching {endpoint}.") from exc

    return parse_json_body(body)


def fetch_binance(endpoint, **params):
    """通过 Binance USDT-M 公开行情接口获取 JSON 数据。"""
    data = http_get_json("Binance", BINANCE_API_BASE, endpoint, **params)
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


def fetch_okx(endpoint, **params):
    """通过 OKX SWAP 公开行情接口获取 data 字段。"""
    payload = http_get_json("OKX", OKX_API_BASE, endpoint, **params)
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


def okx_inst_id(symbol):
    """将 BTCUSDT 转换为 OKX SWAP 的 BTC-USDT-SWAP。"""
    base = symbol[:-4]
    return f"{base}-USDT-SWAP"


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


def fetch_market_data_binance(symbol):
    """获取 Binance USDT-M 行情，并统一成内部数据结构。"""
    klines_1d = require_list("daily klines", fetch_binance("klines", symbol=symbol, interval="1d", limit=90), 30)
    klines_4h = require_list("4h klines", fetch_binance("klines", symbol=symbol, interval="4h", limit=60), 20)
    klines_1w = require_list("weekly klines", fetch_binance("klines", symbol=symbol, interval="1w", limit=30), 1)
    ticker = require_dict_fields(
        "24hr ticker",
        fetch_binance("ticker/24hr", symbol=symbol),
        ["lastPrice", "priceChangePercent", "volume"]
    )
    funding = require_list("funding rate", fetch_binance("fundingRate", symbol=symbol, limit=8), 0)
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


def fetch_market_data_okx(symbol, fallback_reason=None):
    """获取 OKX SWAP 行情，并统一成内部数据结构。"""
    inst_id = okx_inst_id(symbol)
    candles_1d = require_list(
        "OKX daily candles",
        normalize_okx_candles(fetch_okx("market/candles", instId=inst_id, bar="1D", limit=90)),
        30
    )
    candles_4h = require_list(
        "OKX 4h candles",
        normalize_okx_candles(fetch_okx("market/candles", instId=inst_id, bar="4H", limit=60)),
        20
    )
    candles_1w = require_list(
        "OKX weekly candles",
        normalize_okx_candles(fetch_okx("market/candles", instId=inst_id, bar="1W", limit=30)),
        1
    )

    ticker_rows = require_list("OKX ticker", fetch_okx("market/ticker", instId=inst_id), 1)
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

    funding_rows = fetch_okx("public/funding-rate-history", instId=inst_id, limit=8)
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


def fetch_market_data(symbol):
    """优先 Binance；受限或不可用时使用 OKX 公共 SWAP 行情。"""
    try:
        return fetch_market_data_binance(symbol)
    except DataFetchError as binance_error:
        try:
            return fetch_market_data_okx(symbol, fallback_reason=str(binance_error))
        except DataFetchError as okx_error:
            raise DataFetchError(
                f"Binance failed: {binance_error}; OKX fallback failed: {okx_error}"
            ) from okx_error


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
            "fallback_reason": market["fallback_reason"]
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
