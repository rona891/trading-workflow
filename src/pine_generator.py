"""Converts a top-ranked strategy into Pine Script v5 code."""

import anthropic
import pandas as pd


PINE_TEMPLATE = """//@version=5
strategy("{name}", overlay=true, initial_capital={capital},
         default_qty_type=strategy.percent_of_equity, default_qty_value=100,
         commission_type=strategy.commission.percent, commission_value=0.1)

// ─── Inputs ──────────────────────────────────────────────────────────────────
rsi_len     = input.int(14, "RSI Length")
rsi_ob      = input.int(70,  "RSI Overbought")
rsi_os      = input.int(30,  "RSI Oversold")
ema_fast    = input.int(9,   "EMA Fast")
ema_slow    = input.int(20,  "EMA Slow")
ema_long    = input.int(50,  "EMA Long")
macd_fast   = input.int(12,  "MACD Fast")
macd_slow   = input.int(26,  "MACD Slow")
macd_sig    = input.int(9,   "MACD Signal")
bb_len      = input.int(20,  "BB Length")
bb_mult     = input.float(2.0,"BB Multiplier")
stoch_k     = input.int(14,  "Stoch K")
stoch_d     = input.int(3,   "Stoch D")
st_len      = input.int(10,  "Supertrend Length")
st_mult     = input.float(3.0,"Supertrend Multiplier")
sl_mult     = input.float({sl_mult}, "Stop Loss ATR Multiplier")
tp_mult     = input.float({tp_mult}, "Take Profit ATR Multiplier")

// ─── Indicators ──────────────────────────────────────────────────────────────
rsi         = ta.rsi(close, rsi_len)
[macd_line, signal_line, _] = ta.macd(close, macd_fast, macd_slow, macd_sig)
ema_f       = ta.ema(close, ema_fast)
ema_s       = ta.ema(close, ema_slow)
ema_l       = ta.ema(close, ema_long)
[bb_upper, bb_mid, bb_lower] = ta.bb(close, bb_len, bb_mult)
atr         = ta.atr(14)
stoch_k_val = ta.stoch(high, low, close, stoch_k)
stoch_d_val = ta.sma(stoch_k_val, stoch_d)
vwap_val    = ta.vwap(hlc3)
[st_line, st_dir] = ta.supertrend(st_len, st_mult)

// ─── Entry Conditions ────────────────────────────────────────────────────────
{entry_conditions}

// ─── Exit via SL/TP (ATR-based) ──────────────────────────────────────────────
var float entry_price = na
var float sl_price    = na
var float tp_price    = na

if {long_entry}
    entry_price := close
    sl_price    := close - atr * sl_mult
    tp_price    := close + atr * tp_mult
    strategy.entry("Long", strategy.long)

if strategy.position_size > 0
    strategy.exit("Exit Long", "Long", stop=sl_price, limit=tp_price)

// ─── Plots ───────────────────────────────────────────────────────────────────
plot(ema_f,  "EMA Fast",  color=color.new(color.blue, 0),  linewidth=1)
plot(ema_s,  "EMA Slow",  color=color.new(color.orange, 0), linewidth=1)
plot(vwap_val, "VWAP",   color=color.new(color.purple, 0), linewidth=1)
plot(bb_upper, "BB Upper", color=color.new(color.gray, 50))
plot(bb_lower, "BB Lower", color=color.new(color.gray, 50))

plotshape({long_entry}, title="Entry", location=location.belowbar,
          color=color.new(color.green, 0), style=shape.triangleup, size=size.small)
"""


def _build_entry_conditions(strategy_name: str, direction: str) -> tuple[str, str]:
    """Returns (conditions_block, long_entry_expr) for the template."""
    name_lower = strategy_name.lower()
    conditions = []
    logic_parts = []

    if "rsi_oversold" in name_lower or "rsi7_oversold" in name_lower:
        conditions.append("rsi_cross_up = ta.crossover(rsi, rsi_os)")
        logic_parts.append("rsi_cross_up")

    if "ema_cross_9_20" in name_lower:
        conditions.append("ema_cross_9_20 = ta.crossover(ema_f, ema_s)")
        logic_parts.append("ema_cross_9_20")

    if "ema_cross_20_50" in name_lower:
        conditions.append("ema_cross_20_50 = ta.crossover(ema_s, ema_l)")
        logic_parts.append("ema_cross_20_50")

    if "macd_cross" in name_lower:
        conditions.append("macd_cross_up = ta.crossover(macd_line, signal_line)")
        logic_parts.append("macd_cross_up")

    if "bb_bounce" in name_lower:
        conditions.append("bb_bounce_long = close < bb_lower")
        logic_parts.append("bb_bounce_long")

    if "stoch_cross" in name_lower:
        conditions.append("stoch_cross_up = ta.crossover(stoch_k_val, stoch_d_val) and stoch_k_val < 20")
        logic_parts.append("stoch_cross_up")

    if "supertrend_flip" in name_lower:
        conditions.append("st_flip_up = st_dir == 1 and st_dir[1] == -1")
        logic_parts.append("st_flip_up")

    if "vwap_filter" in name_lower:
        conditions.append("above_vwap = close > vwap_val")
        logic_parts.append("above_vwap")

    if "adx_filter" in name_lower:
        adx_line = "adx_strong = ta.adx(high, low, close, 14) > 25"
        conditions.append(adx_line)
        logic_parts.append("adx_strong")

    if not logic_parts:
        conditions.append("default_entry = ta.crossover(ema_f, ema_s) and rsi < 60")
        logic_parts.append("default_entry")

    entry_var = "long_entry" if direction == "long" else "short_entry"
    combined  = " and ".join(logic_parts)
    conditions.append(f"{entry_var} = {combined}")

    return "\n".join(conditions), entry_var


def generate_pine_script(strategy_row: pd.Series, capital: float = 200) -> str:
    """Generates Pine Script v5 code from a ranked strategy row."""
    name      = strategy_row["strategy"]
    direction = strategy_row.get("direction", "long")
    sl_mult   = strategy_row.get("stop_loss_atr_mult",  1.5)
    tp_mult   = strategy_row.get("take_profit_atr_mult", 2.5)

    if hasattr(sl_mult, "item"):
        sl_mult = sl_mult.item()
    if hasattr(tp_mult, "item"):
        tp_mult = tp_mult.item()

    entry_conditions, entry_var = _build_entry_conditions(name, direction)

    return PINE_TEMPLATE.format(
        name=name,
        capital=int(capital),
        sl_mult=sl_mult,
        tp_mult=tp_mult,
        entry_conditions=entry_conditions,
        long_entry=entry_var,
    )


def generate_pine_with_claude(strategy_row: pd.Series, asset: str,
                               timeframe: str, stats: dict, cfg: dict) -> str:
    """Uses Claude to generate a more refined Pine Script explanation and code."""
    model = cfg.get("anthropic_model", "claude-sonnet-4-6")
    client = anthropic.Anthropic()

    base_code = generate_pine_script(strategy_row, cfg["backtest"]["initial_capital"])

    prompt = f"""You are a Pine Script v5 expert. Here is an auto-generated strategy script:

Asset: {asset} | Timeframe: {timeframe}
Strategy: {strategy_row['strategy']} ({strategy_row.get('direction','long')})
Backtest stats: Win rate={stats.get('win_rate',0)*100:.1f}%,
Profit factor={stats.get('profit_factor',0):.2f},
Max drawdown={stats.get('max_drawdown',0)*100:.1f}%

Base script:
```pine
{base_code}
```

Review and improve this Pine Script. Keep all logic intact but:
1. Add a comment header with the strategy stats
2. Add a background color when in a trade (green tint for long)
3. Add a label showing entry reason on the chart
4. Ensure it compiles correctly in TradingView Pine Script v5

Return ONLY the improved Pine Script code, no explanation."""

    message = client.messages.create(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()
