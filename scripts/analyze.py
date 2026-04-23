#!/usr/bin/env python3
"""
paulwei-crypto market analyzer
Fetches live Binance USDT-M futures data and computes Paul Wei framework indicators.

Usage:
    python analyze.py BTCUSDT
    python analyze.py SOLUSDT

Output: JSON with all computed indicators, ready for Claude to format.
No API key required — Binance public endpoints only.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone


def fetch(endpoint, **params):
    """Fetch from Binance USDT-M futures public API via curl."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://fapi.binance.com/fapi/v1/{endpoint}?{qs}"
    r = subprocess.run(
        ["curl", "-s", "--connect-timeout", "10", "--max-time", "15", url],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        raise ConnectionError(f"curl failed for {endpoint}: {r.stderr}")
    return json.loads(r.stdout)


def ma(closes, n):
    if len(closes) < n:
        return sum(closes) / len(closes)  # use available if < n
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
    """Infer weekly trend from last 8 weekly candles."""
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
    Find nearest psychological round-number levels above and below price.
    Uses two granularities: major (e.g. $10k for BTC) and minor (e.g. $1k).
    """
    # Determine interval scales based on price magnitude
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
    return levels[:n * 2]  # return n above + n below candidates, deduped by dist


def entry_score(ma30_dev, trend4h, w_trend, avg_funding):
    """
    Score entry favorability for both long and short based on Paul Wei's framework.
    Primary driver: MA30 deviation state.
    Modifiers: 4h trend alignment, weekly trend alignment, funding rate cost.
    Returns scores 1-10 with labels and one-line advice.
    """
    # MA30 base score for long (higher score = more favorable for long)
    if ma30_dev < -10:
        long_base = 9    # 超跌区 — historical best long zone
    elif ma30_dev < -5:
        long_base = 7    # 偏低区 — lean long
    elif ma30_dev < 5:
        long_base = 5    # 均衡区 — neutral, both directions viable
    elif ma30_dev < 10:
        long_base = 3    # 偏高区 — cautious long
    else:
        long_base = 1    # 过热区 — avoid long

    # Modifiers
    long_adj = 0
    if trend4h == "上升趋势":
        long_adj += 1
    elif trend4h == "下降趋势":
        long_adj -= 1

    if w_trend == "上升":
        long_adj += 1
    elif w_trend == "下降":
        long_adj -= 1

    if avg_funding < -0.0001:   # shorts paying = cheap to hold long
        long_adj += 1
    elif avg_funding > 0.0003:  # expensive to hold long
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
        if s >= 8:  return f"框架信号强，可在关注区分批挂限价{direction}单"
        if s >= 6:  return f"{direction}条件较好，等价格回踩关注区再挂单"
        if s >= 4:  return f"{direction}有一定依据，信号尚未完全确认，仓位需小"
        if s >= 2:  return f"当前{direction}属逆势，若操作仓位需极小（≤0.25%账户）"
        return f"当前不适合{direction}，等待更好的结构机会"

    # Driving factors (for transparency)
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

    symbol = sys.argv[1].upper()

    try:
        klines_1d = fetch("klines", symbol=symbol, interval="1d", limit=90)
        klines_4h = fetch("klines", symbol=symbol, interval="4h", limit=60)
        klines_1w = fetch("klines", symbol=symbol, interval="1w", limit=30)
        ticker    = fetch("ticker/24hr", symbol=symbol)
        funding   = fetch("fundingRate", symbol=symbol, limit=8)
    except Exception as e:
        print(json.dumps({"error": f"Data fetch failed: {e}"}))
        sys.exit(1)

    if isinstance(klines_1d, dict) and "code" in klines_1d:
        print(json.dumps({"error": f"{symbol} not found on Binance USDT-M futures. Check symbol spelling."}))
        sys.exit(1)

    price    = float(ticker["lastPrice"])
    chg      = float(ticker["priceChangePercent"])
    vol_24h  = float(ticker["volume"])

    # ── Daily indicators ─────────────────────────────────────────────
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

    # ── Weekly indicators ────────────────────────────────────────────
    w_closes = [float(c[4]) for c in klines_1w]
    w_highs  = [float(c[2]) for c in klines_1w]
    w_lows   = [float(c[3]) for c in klines_1w]
    w_ma30   = ma(w_closes, 30)
    w_dev30  = (price - w_ma30) / w_ma30 * 100 if w_ma30 else 0
    w_high8  = max(w_highs[-8:]) if len(w_highs) >= 8 else max(w_highs)
    w_low8   = min(w_lows[-8:])  if len(w_lows)  >= 8 else min(w_lows)
    w_trend  = weekly_trend(klines_1w)

    # ── 4h structure ─────────────────────────────────────────────────
    trend4h = trend_4h(klines_4h)
    zones4h = key_zone_4h(klines_4h, price)

    # ── Funding rate ─────────────────────────────────────────────────
    rates      = [float(f["fundingRate"]) for f in funding]
    latest_rate = rates[-1] if rates else 0
    avg_rate    = sum(rates) / len(rates) if rates else 0

    if avg_rate > 0.0001:
        funding_desc = "多头持续付费，市场偏乐观，注意过热风险"
    elif avg_rate < -0.0001:
        funding_desc = "空头持续付费，市场偏悲观，可能接近底部"
    else:
        funding_desc = "多空费率接近零，情绪均衡"

    # ── Volume ───────────────────────────────────────────────────────
    vols    = [float(c[5]) for c in klines_1d]
    avg_vol = sum(vols[-30:]) / 30 if len(vols) >= 30 else sum(vols) / len(vols)
    vol_ratio  = round(vol_24h / avg_vol, 2) if avg_vol else 1.0
    vol_status = "放量" if vol_ratio > 1.3 else ("缩量" if vol_ratio < 0.7 else "正常")

    # ── Psychological price levels ───────────────────────────────────
    psych = psych_levels(price, n=4)

    # ── Entry score ──────────────────────────────────────────────────
    score = entry_score(dev30, trend4h, w_trend, avg_rate)

    # ── Output ───────────────────────────────────────────────────────
    out = {
        "symbol":    symbol,
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
