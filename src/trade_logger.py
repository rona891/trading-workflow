"""Persists executed trades and open position to trade_log.json."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

TRADE_LOG = Path(__file__).parent.parent / "trade_log.json"
ARG_TZ = timezone(timedelta(hours=-3))


def _now_arg():
    return datetime.now(ARG_TZ)


def _load() -> dict:
    if TRADE_LOG.exists():
        with open(TRADE_LOG, encoding="utf-8") as f:
            return json.load(f)
    return {"trades": [], "open_position": None, "initial_balance": 10000.0}


def _save(data: dict) -> None:
    with open(TRADE_LOG, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def log_entry(asset: str, direction: str, entry_price: float,
              sl: float, tp: float, quantity: float,
              order_id: int = 0, oco_id: int = 0) -> None:
    data = _load()
    now = _now_arg()
    data["open_position"] = {
        "date":        now.strftime("%Y-%m-%d"),
        "time":        now.strftime("%H:%M:%S"),
        "asset":       asset,
        "binance_symbol": asset.replace("/", ""),
        "direction":   direction,
        "entry_price": entry_price,
        "sl":          sl,
        "tp":          tp,
        "quantity":    quantity,
        "order_id":    order_id,
        "oco_id":      oco_id,
    }
    _save(data)


def log_close(result: str, exit_price: float) -> None:
    data = _load()
    pos = data.get("open_position")
    if not pos:
        return
    entry = pos["entry_price"]
    qty = pos["quantity"]
    if pos["direction"] == "long":
        pnl_usdt = (exit_price - entry) * qty
    else:
        pnl_usdt = (entry - exit_price) * qty
    pnl_pct = pnl_usdt / (entry * qty) * 100

    now = _now_arg()
    trade = {
        **pos,
        "result":      result,
        "exit_price":  exit_price,
        "pnl_usdt":    round(pnl_usdt, 4),
        "pnl_pct":     round(pnl_pct, 3),
        "close_time":  now.strftime("%H:%M:%S"),
    }
    data["trades"].append(trade)
    data["open_position"] = None
    _save(data)


def get_all() -> dict:
    return _load()
