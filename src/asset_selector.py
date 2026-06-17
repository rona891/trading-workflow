"""Uses Claude to select the best asset and timeframe for today's session."""

import json
import os

import anthropic
import pandas as pd
import pandas_ta as ta


def compute_opportunity_metrics(data: dict) -> list[dict]:
    """
    For each asset/timeframe pair, computes:
    - ATR% (volatility relative to price)
    - Volume ratio (recent vs average)
    - ADX (trend strength)
    - Recent return (last 5 bars %)
    """
    metrics = []
    for asset, tfs in data.items():
        for tf, df in tfs.items():
            if df is None or len(df) < 30:
                continue
            try:
                close = df["close"]
                atr   = ta.atr(df["high"], df["low"], df["close"], length=14)
                adx   = ta.adx(df["high"], df["low"], df["close"], length=14)
                vol_ratio = df["volume"].tail(5).mean() / df["volume"].tail(20).mean()
                atr_pct   = float(atr.iloc[-1] / close.iloc[-1] * 100) if atr is not None else 0
                adx_val   = float(adx["ADX_14"].iloc[-1]) if adx is not None else 0
                ret_5     = float((close.iloc[-1] / close.iloc[-6] - 1) * 100)

                metrics.append({
                    "asset":      asset,
                    "timeframe":  tf,
                    "atr_pct":    round(atr_pct, 3),
                    "vol_ratio":  round(float(vol_ratio), 3),
                    "adx":        round(adx_val, 1),
                    "return_5b":  round(ret_5, 3),
                    "bars":       len(df),
                })
            except Exception:
                continue
    return metrics


def select_best_asset(data: dict, cfg: dict) -> tuple[str, str]:
    """
    Calls Claude to pick the best asset and timeframe based on opportunity metrics.
    Returns (asset, timeframe).
    """
    metrics = compute_opportunity_metrics(data)
    if not metrics:
        raise ValueError("No metrics computed — check data fetching.")

    metrics_str = json.dumps(metrics, indent=2)
    model = cfg.get("anthropic_model", "claude-sonnet-4-6")

    client = anthropic.Anthropic()
    prompt = f"""You are a quantitative trading analyst. Based on these market metrics,
select the single best asset and timeframe combination for day trading today.

Metrics (one entry per asset/timeframe):
{metrics_str}

Selection criteria:
1. ATR% > 0.5% (enough volatility to profit)
2. vol_ratio > 1.0 (above-average volume)
3. ADX > 20 (trending, not choppy)
4. Prefer timeframes 15m or 1h for day trading balance

Respond with a JSON object only, no explanation:
{{"asset": "...", "timeframe": "...", "reason": "one sentence"}}"""

    message = client.messages.create(
        model=model,
        max_tokens=256,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    result = json.loads(raw[start:end])
    return result["asset"], result["timeframe"], result.get("reason", "")


def select_best_asset_local(data: dict) -> tuple[str, str, str]:
    """
    Fallback: picks asset/timeframe with highest combined score without Claude API.
    """
    metrics = compute_opportunity_metrics(data)
    if not metrics:
        raise ValueError("No metrics available")

    df = pd.DataFrame(metrics)
    df["score"] = (
        df["atr_pct"].clip(0, 3) / 3 * 0.4 +
        df["vol_ratio"].clip(0, 3) / 3 * 0.3 +
        df["adx"].clip(0, 50) / 50 * 0.3
    )
    tf_pref = {"15m": 1.2, "1h": 1.1, "5m": 0.9, "4h": 0.8}
    df["score"] *= df["timeframe"].map(tf_pref).fillna(1.0)

    best = df.sort_values("score", ascending=False).iloc[0]
    reason = f"ATR%={best['atr_pct']}, vol_ratio={best['vol_ratio']}, ADX={best['adx']}"
    return best["asset"], best["timeframe"], reason
