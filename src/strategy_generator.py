"""Generates strategy signal combinations from indicator library."""

import itertools
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from indicator_library import INDICATOR_META, add_all_indicators


@dataclass
class Strategy:
    name: str
    entry_rules: list[dict]
    exit_rules: list[dict]
    stop_loss_atr_mult: float = 1.5
    take_profit_atr_mult: float = 2.5

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "entry_rules": self.entry_rules,
            "exit_rules": self.exit_rules,
            "stop_loss_atr_mult": self.stop_loss_atr_mult,
            "take_profit_atr_mult": self.take_profit_atr_mult,
        }


def _rsi_entry(df: pd.DataFrame, col: str, level: float, direction: str) -> pd.Series:
    """Returns True on bars where RSI crosses the level."""
    if direction == "long":
        return (df[col].shift(1) < level) & (df[col] >= level)
    return (df[col].shift(1) > level) & (df[col] <= level)


def _ema_cross_entry(df: pd.DataFrame, fast: str, slow: str, direction: str) -> pd.Series:
    cross_up = (df[fast].shift(1) < df[slow].shift(1)) & (df[fast] >= df[slow])
    cross_dn = (df[fast].shift(1) > df[slow].shift(1)) & (df[fast] <= df[slow])
    return cross_up if direction == "long" else cross_dn


def _macd_cross_entry(df: pd.DataFrame, direction: str) -> pd.Series:
    macd = df["MACD_12_26_9"]
    sig  = df["MACDs_12_26_9"]
    cross_up = (macd.shift(1) < sig.shift(1)) & (macd >= sig)
    cross_dn = (macd.shift(1) > sig.shift(1)) & (macd <= sig)
    return cross_up if direction == "long" else cross_dn


def _bb_entry(df: pd.DataFrame, direction: str) -> pd.Series:
    if direction == "long":
        return df["close"] < df["BBL_20_2.0"]
    return df["close"] > df["BBU_20_2.0"]


def _stoch_entry(df: pd.DataFrame, direction: str) -> pd.Series:
    k, d = df["STOCHk_14_3_3"], df["STOCHd_14_3_3"]
    cross_up = (k.shift(1) < d.shift(1)) & (k >= d) & (k < 20)
    cross_dn = (k.shift(1) > d.shift(1)) & (k <= d) & (k > 80)
    return cross_up if direction == "long" else cross_dn


def _supertrend_entry(df: pd.DataFrame, direction: str) -> pd.Series:
    st = df["SUPERTd_10_3.0"]
    flip_up = (st.shift(1) == -1) & (st == 1)
    flip_dn = (st.shift(1) == 1)  & (st == -1)
    return flip_up if direction == "long" else flip_dn


def _vwap_filter(df: pd.DataFrame, direction: str) -> pd.Series:
    if direction == "long":
        return df["close"] > df["VWAP_D"]
    return df["close"] < df["VWAP_D"]


def _adx_filter(df: pd.DataFrame, min_adx: float = 25.0) -> pd.Series:
    return df["ADX_14"] > min_adx


SIGNAL_BUILDERS = {
    "rsi_oversold":    lambda df, d: _rsi_entry(df, "RSI_14", 30, d),
    "rsi_overbought":  lambda df, d: _rsi_entry(df, "RSI_14", 70, d),
    "rsi7_oversold":   lambda df, d: _rsi_entry(df, "RSI_7", 30, d),
    "ema_cross_9_20":  lambda df, d: _ema_cross_entry(df, "EMA_9", "EMA_20", d),
    "ema_cross_20_50": lambda df, d: _ema_cross_entry(df, "EMA_20", "EMA_50", d),
    "macd_cross":      lambda df, d: _macd_cross_entry(df, d),
    "bb_bounce":       lambda df, d: _bb_entry(df, d),
    "stoch_cross":     lambda df, d: _stoch_entry(df, d),
    "supertrend_flip": lambda df, d: _supertrend_entry(df, d),
}

FILTER_BUILDERS = {
    "vwap_filter": _vwap_filter,
    "adx_filter":  lambda df, d: _adx_filter(df),
}


def build_signals(df: pd.DataFrame, strategy: Strategy, direction: str = "long") -> pd.Series:
    """Combines all entry rules with AND logic into a single signal Series."""
    signals = pd.Series(True, index=df.index)
    for rule in strategy.entry_rules:
        name = rule["name"]
        if name in SIGNAL_BUILDERS:
            signals &= SIGNAL_BUILDERS[name](df, direction)
        elif name in FILTER_BUILDERS:
            signals &= FILTER_BUILDERS[name](df, direction)
    return signals


def generate_strategies() -> list[Strategy]:
    """Generates all viable strategy combinations."""
    strategies = []

    trigger_names   = ["rsi_oversold", "ema_cross_9_20", "ema_cross_20_50",
                       "macd_cross", "bb_bounce", "stoch_cross", "supertrend_flip"]
    filter_names    = ["vwap_filter", "adx_filter"]
    sl_mults        = [1.0, 1.5, 2.0]
    tp_mults        = [2.0, 2.5, 3.0]

    for trigger in trigger_names:
        for filt in filter_names:
            for sl, tp in itertools.product(sl_mults, tp_mults):
                if tp <= sl:
                    continue
                name = f"{trigger}+{filt}_SL{sl}_TP{tp}"
                s = Strategy(
                    name=name,
                    entry_rules=[{"name": trigger}, {"name": filt}],
                    exit_rules=[],
                    stop_loss_atr_mult=sl,
                    take_profit_atr_mult=tp,
                )
                strategies.append(s)

    for t1, t2 in itertools.combinations(trigger_names, 2):
        for sl, tp in [(1.5, 2.5), (1.0, 2.0)]:
            name = f"{t1}+{t2}_SL{sl}_TP{tp}"
            s = Strategy(
                name=name,
                entry_rules=[{"name": t1}, {"name": t2}],
                exit_rules=[],
                stop_loss_atr_mult=sl,
                take_profit_atr_mult=tp,
            )
            strategies.append(s)

    return strategies
