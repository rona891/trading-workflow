"""Backtests strategies using vectorbt. Returns performance metrics."""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import vectorbt as vbt

from indicator_library import add_all_indicators
from strategy_generator import Strategy, build_signals, generate_strategies


def _trading_hours_mask(index: pd.DatetimeIndex) -> pd.Series:
    """True for rows within 03:00-15:00 ARG (= 06:00-18:00 UTC), Mon-Fri only."""
    if index.tzinfo is None:
        utc_hour = index.hour
    else:
        utc_hour = index.tz_convert("UTC").hour
    in_hours = (utc_hour >= 6) & (utc_hour < 18)
    weekday = index.weekday  # 0=Mon … 6=Sun
    in_weekday = weekday < 5
    return pd.Series(in_hours & in_weekday, index=index)


def run_backtest(df: pd.DataFrame, strategy: Strategy, direction: str = "long",
                 initial_capital: float = 200.0) -> dict | None:
    """
    Runs a vectorbt backtest for one strategy.
    Returns metrics dict or None if insufficient trades.
    """
    df_ind = add_all_indicators(df)
    if df_ind.empty or len(df_ind) < 50:
        return None

    atr = df_ind.get("ATRr_14")
    if atr is None or atr.isna().all():
        return None

    entries = build_signals(df_ind, strategy, direction)
    # Only allow entries during trading hours (03:00-15:00 ARG) to match live execution
    time_mask = _trading_hours_mask(df_ind.index)
    entries = entries & time_mask
    if entries.sum() < 1:
        return None

    close = df_ind["close"]
    sl_pct = (atr / close * strategy.stop_loss_atr_mult).clip(upper=0.10)
    tp_pct = (atr / close * strategy.take_profit_atr_mult).clip(upper=0.20)

    # Compute freq explicitly — vectorbt + pandas>=2 don't support freq="infer"
    try:
        idx = close.index
        if len(idx) >= 2:
            delta = idx[1] - idx[0]
            freq = pd.tseries.frequencies.to_offset(delta)
        else:
            freq = "15min"
    except Exception:
        freq = "15min"

    try:
        pf = vbt.Portfolio.from_signals(
            close=close,
            entries=entries if direction == "long" else pd.Series(False, index=close.index),
            exits=pd.Series(False, index=close.index),
            short_entries=entries if direction == "short" else pd.Series(False, index=close.index),
            short_exits=pd.Series(False, index=close.index),
            sl_stop=sl_pct,
            tp_stop=tp_pct,
            init_cash=initial_capital,
            freq=freq,
            log=False,
        )
    except Exception:
        return None

    trades = pf.trades.records_readable
    n_trades = len(trades)
    if n_trades < 1:
        return None

    wins = (trades["PnL"] > 0).sum()
    win_rate = wins / n_trades

    gross_profit = trades.loc[trades["PnL"] > 0, "PnL"].sum()
    gross_loss   = abs(trades.loc[trades["PnL"] < 0, "PnL"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    total_return = pf.total_return()
    max_dd       = abs(pf.max_drawdown())

    try:
        sharpe = pf.sharpe_ratio()
        sharpe = float(sharpe) if not np.isnan(sharpe) else 0.0
    except Exception:
        sharpe = 0.0

    return {
        "strategy":      strategy.name,
        "direction":     direction,
        "n_trades":      n_trades,
        "win_rate":      round(float(win_rate), 4),
        "profit_factor": round(float(profit_factor), 3),
        "total_return":  round(float(total_return), 4),
        "max_drawdown":  round(float(max_dd), 4),
        "sharpe":        round(sharpe, 3),
    }


def backtest_all(df: pd.DataFrame, strategies: list[Strategy],
                 cfg: dict) -> list[dict]:
    """Runs all strategies and returns filtered results."""
    min_trades  = cfg["backtest"]["min_trades"]
    min_wr      = cfg["backtest"]["min_win_rate"]
    max_dd      = cfg["backtest"]["max_drawdown"]
    capital     = cfg["backtest"]["initial_capital"]

    # Only LONG — spot Binance doesn't support margin shorting
    results = []
    n_no_signal = 0
    n_low_trades = 0
    n_low_wr = 0
    n_high_dd = 0

    for strat in strategies:
        res = run_backtest(df, strat, "long", capital)
        if res is None:
            n_no_signal += 1
            continue
        if res["n_trades"] < min_trades:
            n_low_trades += 1
        elif res["win_rate"] < min_wr:
            n_low_wr += 1
        elif res["max_drawdown"] > max_dd:
            n_high_dd += 1
        else:
            results.append(res)

    total = len(strategies)
    print(f"  Diagnóstico de filtros ({total} estrategias):")
    print(f"    Sin señal / error:         {n_no_signal:>4}  ({n_no_signal/total:.0%})")
    print(f"    Trades insuficientes (<{min_trades}): {n_low_trades:>4}  ({n_low_trades/total:.0%})")
    print(f"    Win rate bajo (<{min_wr:.0%}):     {n_low_wr:>4}  ({n_low_wr/total:.0%})")
    print(f"    Drawdown alto (>{max_dd:.0%}):    {n_high_dd:>4}  ({n_high_dd/total:.0%})")
    print(f"    Pasaron todos los filtros:  {len(results):>4}")

    return results
