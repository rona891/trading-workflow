"""Downloads and caches OHLCV data from multiple free sources."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import ccxt
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

TF_MAP_CCXT = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "4h"}
TF_MAP_YF   = {"5m": "5m", "15m": "15m", "1h": "1h", "4h": "1h"}
TF_DAYS     = {"5m": 30,   "15m": 60,    "1h": 90,   "4h": 90}


def _cache_path(asset: str, timeframe: str) -> Path:
    safe = asset.replace("/", "-")
    return DATA_DIR / f"{safe}_{timeframe}.parquet"


def _is_fresh(path: Path, max_hours: int = 4) -> bool:
    if not path.exists():
        return False
    age = datetime.now().timestamp() - path.stat().st_mtime
    return age < max_hours * 3600


def fetch_crypto(asset: str, timeframe: str, days: int) -> pd.DataFrame:
    """Fetch crypto OHLCV from Binance via ccxt with pagination for longer histories."""
    exchange = ccxt.binance({"enableRateLimit": True})
    tf = TF_MAP_CCXT[timeframe]
    since = exchange.parse8601((datetime.utcnow() - timedelta(days=days)).isoformat() + "Z")

    all_raw = []
    current_since = since
    while True:
        batch = exchange.fetch_ohlcv(asset, tf, since=current_since, limit=1000)
        if not batch:
            break
        all_raw.extend(batch)
        if len(batch) < 1000:
            break
        current_since = batch[-1][0] + 1
        if current_since >= exchange.milliseconds():
            break

    df = pd.DataFrame(all_raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df.drop_duplicates("timestamp", inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    df.set_index("timestamp", inplace=True)
    return df


def fetch_stock(ticker: str, timeframe: str, days: int) -> pd.DataFrame:
    """Fetch stock/ETF OHLCV from Yahoo Finance."""
    interval = TF_MAP_YF[timeframe]
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    df = yf.download(ticker, start=start, interval=interval, progress=False, auto_adjust=True)
    df.index.name = "timestamp"
    df.columns = [c.lower() for c in df.columns]
    return df[["open", "high", "low", "close", "volume"]]


def get_ohlcv(asset: str, timeframe: str, force_refresh: bool = False) -> pd.DataFrame:
    """Returns OHLCV DataFrame, using cache when available."""
    path = _cache_path(asset, timeframe)
    if not force_refresh and _is_fresh(path):
        return pd.read_parquet(path)

    days = TF_DAYS.get(timeframe, 90)
    is_crypto = "/" in asset

    try:
        df = fetch_crypto(asset, timeframe, days) if is_crypto else fetch_stock(asset, timeframe, days)
    except Exception as e:
        if path.exists():
            print(f"[data_fetcher] Warning: refresh failed ({e}), using cached data")
            return pd.read_parquet(path)
        raise

    df.dropna(inplace=True)
    df.to_parquet(path)
    return df


def fetch_all(assets_cfg: dict, timeframes: list[str], force_refresh: bool = False) -> dict:
    """Fetch data for all configured assets and timeframes.
    Returns: {asset: {timeframe: DataFrame}}
    """
    result = {}
    all_assets = assets_cfg.get("crypto", []) + assets_cfg.get("stocks", [])
    for asset in all_assets:
        result[asset] = {}
        for tf in timeframes:
            try:
                result[asset][tf] = get_ohlcv(asset, tf, force_refresh)
                print(f"  [OK] {asset} {tf}: {len(result[asset][tf])} bars")
            except Exception as e:
                print(f"  [SKIP] {asset} {tf}: {e}")
    return result


if __name__ == "__main__":
    with open(ROOT / "config.json") as f:
        cfg = json.load(f)
    print("Fetching data...")
    data = fetch_all(cfg["assets"], cfg["timeframes"])
    print(f"\nDone. {sum(len(v) for v in data.values())} asset/timeframe combinations loaded.")
