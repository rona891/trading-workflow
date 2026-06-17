"""Computes technical indicators on OHLCV DataFrames using pandas-ta."""

import pandas as pd
import pandas_ta as ta


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds all supported indicators to a copy of df."""
    d = df.copy()

    d.ta.rsi(length=14, append=True)
    d.ta.rsi(length=7,  append=True)

    d.ta.macd(fast=12, slow=26, signal=9, append=True)

    d.ta.ema(length=9,  append=True)
    d.ta.ema(length=20, append=True)
    d.ta.ema(length=50, append=True)

    d.ta.bbands(length=20, std=2.0, append=True)
    # Rename BBands columns: pandas-ta creates BBL_20_2.0_2.0 with std as float
    bb_rename = {c: c.replace("_2.0_2.0", "_2.0") for c in d.columns if "_2.0_2.0" in c}
    d.rename(columns=bb_rename, inplace=True)

    d.ta.atr(length=14, append=True)

    d.ta.stoch(k=14, d=3, smooth_k=3, append=True)

    d.ta.adx(length=14, append=True)

    d.ta.vwap(append=True)

    d.ta.supertrend(length=10, multiplier=3.0, append=True)

    # SUPERTl/SUPERTs are NaN by design (directional lines) — exclude from dropna
    essential = [c for c in d.columns if c not in ("SUPERTl_10_3.0", "SUPERTs_10_3.0")]
    d.dropna(subset=essential, inplace=True)
    return d


INDICATOR_META = {
    "RSI_14":        {"col": "RSI_14",        "type": "oscillator", "overbought": 70, "oversold": 30},
    "RSI_7":         {"col": "RSI_7",          "type": "oscillator", "overbought": 70, "oversold": 30},
    "MACD":          {"col": "MACD_12_26_9",   "type": "momentum"},
    "MACD_SIGNAL":   {"col": "MACDs_12_26_9",  "type": "momentum"},
    "EMA_9":         {"col": "EMA_9",          "type": "trend"},
    "EMA_20":        {"col": "EMA_20",         "type": "trend"},
    "EMA_50":        {"col": "EMA_50",         "type": "trend"},
    "BB_UPPER":      {"col": "BBU_20_2.0",     "type": "volatility"},
    "BB_LOWER":      {"col": "BBL_20_2.0",     "type": "volatility"},
    "BB_MID":        {"col": "BBM_20_2.0",     "type": "volatility"},
    "ATR_14":        {"col": "ATRr_14",        "type": "volatility"},
    "STOCH_K":       {"col": "STOCHk_14_3_3",  "type": "oscillator", "overbought": 80, "oversold": 20},
    "STOCH_D":       {"col": "STOCHd_14_3_3",  "type": "oscillator"},
    "ADX_14":        {"col": "ADX_14",         "type": "trend_strength"},
    "VWAP":          {"col": "VWAP_D",         "type": "trend"},
    "SUPERTREND":    {"col": "SUPERTd_10_3.0", "type": "trend"},
}
