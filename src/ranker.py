"""Ranks backtest results using a weighted composite score."""

import pandas as pd


def compute_scores(results: list[dict], weights: dict) -> pd.DataFrame:
    """
    Adds a composite score to each result and returns sorted DataFrame.
    Score = win_rate*w1 + profit_factor_norm*w2 + sharpe_norm*w3 + (1-drawdown)*w4
    """
    if not results:
        return pd.DataFrame()

    df = pd.DataFrame(results)

    pf_max = df["profit_factor"].replace(float("inf"), df["profit_factor"].replace(float("inf"), 0).max() * 1.5)
    df["pf_norm"]     = (pf_max / pf_max.max()).clip(0, 1)
    df["sharpe_norm"] = (df["sharpe"] / df["sharpe"].max()).clip(0, 1) if df["sharpe"].max() > 0 else 0
    df["dd_score"]    = 1 - df["max_drawdown"]
    # Frecuencia: normalizada contra el máximo de trades del set (más señales = mejor)
    df["freq_norm"]   = (df["n_trades"] / df["n_trades"].max()).clip(0, 1) if df["n_trades"].max() > 0 else 0

    w = weights
    df["score"] = (
        df["win_rate"]    * w["weight_win_rate"] +
        df["pf_norm"]     * w["weight_profit_factor"] +
        df["sharpe_norm"] * w["weight_sharpe"] +
        df["dd_score"]    * w["weight_drawdown"] +
        df["freq_norm"]   * w.get("weight_frequency", 0.0)
    )

    return df.sort_values("score", ascending=False).reset_index(drop=True)


def get_top_n(results: list[dict], cfg: dict) -> pd.DataFrame:
    ranked = compute_scores(results, cfg["ranking"])
    top_n  = cfg["ranking"]["top_n"]
    return ranked.head(top_n)


def format_ranking_text(top: pd.DataFrame) -> str:
    """Returns a human-readable ranking string."""
    if top.empty:
        return "No strategies passed the filters."

    lines = ["## Ranking de estrategias\n"]
    for i, row in top.iterrows():
        lines.append(f"### #{i+1} — {row['strategy']} ({row['direction'].upper()})")
        lines.append(f"- Score: **{row['score']:.3f}**")
        lines.append(f"- Win rate: {row['win_rate']*100:.1f}%  |  Operaciones: {int(row['n_trades'])}")
        lines.append(f"- Profit factor: {row['profit_factor']:.2f}  |  Sharpe: {row['sharpe']:.2f}")
        lines.append(f"- Retorno total: {row['total_return']*100:.2f}%  |  Max drawdown: {row['max_drawdown']*100:.1f}%")
        lines.append("")

    return "\n".join(lines)
