"""
Live signal monitor — runs Mon-Fri 03:00-15:00 Argentina time (UTC-3).
Loads today_strategy.json, polls every 5 min, executes on Binance testnet.

Usage: python live_monitor.py [--dry-run]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

import ccxt
import pandas as pd

from broker_executor import (
    cancel_all_open_orders,
    get_account_balance,
    get_current_price,
    get_open_orders,
    get_position_status,
    place_long_entry_with_oco,
)
from indicator_library import add_all_indicators
from notifier import notify_close, notify_entry, notify_eod, notify_error
from strategy_generator import build_signals, Strategy
from trade_logger import log_entry as tlog_entry, log_close as tlog_close

PID_FILE = ROOT / "bot_monitor.pid"

ARG_TZ = timezone(timedelta(hours=-3))
POLL_SECONDS = 5  # 5 seconds
TRADE_USDT = 190.0  # leave 10 USDT as buffer from 200 total
MIN_BAR_LOOKBACK = 100  # bars to fetch for indicator calculation


def arg_now() -> datetime:
    return datetime.now(ARG_TZ)


def is_trading_time() -> bool:
    now = arg_now()
    if now.weekday() >= 5:  # Sat=5, Sun=6
        return False
    return 3 <= now.hour < 15


def minutes_until_market_open() -> int:
    now = arg_now()
    if now.weekday() >= 5:
        days_ahead = 7 - now.weekday()
        open_time = (now + timedelta(days=days_ahead)).replace(hour=3, minute=0, second=0, microsecond=0)
    elif now.hour < 3:
        open_time = now.replace(hour=3, minute=0, second=0, microsecond=0)
    else:
        open_time = (now + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    delta = open_time - now
    return max(0, int(delta.total_seconds() / 60))


def load_strategy() -> dict:
    path = ROOT / "today_strategy.json"
    if not path.exists():
        raise FileNotFoundError(
            "today_strategy.json not found — run run_workflow.py first"
        )
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    today = arg_now().strftime("%Y-%m-%d")
    if data.get("date") != today:
        raise ValueError(
            f"today_strategy.json is from {data.get('date')}, not today ({today}). "
            "Run run_workflow.py first."
        )
    return data


def fetch_recent_ohlcv(asset: str, timeframe: str, limit: int = MIN_BAR_LOOKBACK) -> pd.DataFrame:
    exchange = ccxt.binance({"options": {"defaultType": "spot"}})
    raw = exchange.fetch_ohlcv(asset, timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df.set_index("timestamp", inplace=True)
    df.index = df.index.tz_localize(None)
    return df


def parse_strategy_signals(strategy_name: str) -> list[str]:
    """Extract signal names from strategy name like 'ema_cross_9_20+vwap_filter_SL2.0_TP2.5'."""
    import re
    # Remove SL/TP suffix
    clean = re.sub(r"_SL[\d.]+_TP[\d.]+$", "", strategy_name)
    # Split on +
    parts = clean.split("+")
    return parts


def check_entry_signal(df: pd.DataFrame, strat: dict) -> bool:
    """Returns True if the LAST bar has the entry signal."""
    from strategy_generator import SIGNAL_BUILDERS, FILTER_BUILDERS
    df_ind = add_all_indicators(df)
    if df_ind.empty or len(df_ind) < 10:
        return False

    direction = strat.get("direction", "long")
    signals = parse_strategy_signals(strat["strategy_name"])
    combined = pd.Series(True, index=df_ind.index)

    for sig_name in signals:
        builder = SIGNAL_BUILDERS.get(sig_name) or FILTER_BUILDERS.get(sig_name)
        if builder is None:
            print(f"  [warn] Unknown signal: {sig_name}")
            continue
        mask = builder(df_ind, direction)
        combined = combined & mask

    last_signal = bool(combined.iloc[-1])
    return last_signal


def calculate_sl_tp(df: pd.DataFrame, strat: dict, entry_price: float) -> tuple[float, float]:
    df_ind = add_all_indicators(df)
    atr = df_ind["ATRr_14"].iloc[-1]
    direction = strat["direction"]
    sl_mult = strat["sl_atr_mult"]
    tp_mult = strat["tp_atr_mult"]

    if direction == "long":
        sl = entry_price - atr * sl_mult
        tp = entry_price + atr * tp_mult
    else:
        sl = entry_price + atr * sl_mult
        tp = entry_price - atr * tp_mult

    return round(sl, 4), round(tp, 4)


def run(dry_run: bool = False, ignore_hours: bool = False):
    mode = "DRY RUN" if dry_run else "TESTNET"
    if ignore_hours:
        mode += " + IGNORE HOURS"
    PID_FILE.write_text(str(os.getpid()))
    print(f"\n=== LIVE MONITOR ({mode}) ===")
    print(f"Hora ARG: {arg_now().strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Load today's strategy
    try:
        strat = load_strategy()
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    asset = strat["asset"]
    symbol = strat["binance_symbol"]
    timeframe = strat["timeframe"]
    direction = strat["direction"]
    print(f"Estrategia: {strat['strategy_name']}")
    print(f"Activo: {asset} | TF: {timeframe} | Dir: {direction.upper()}")
    print(f"Win rate backtest: {strat['win_rate']:.1%} | PF: {strat['profit_factor']:.2f}")

    if not dry_run:
        bal = get_account_balance("USDT")
        print(f"Balance USDT testnet: {bal:.2f}")

    position = None  # dict with trade info when open

    # Wait until trading time if needed
    if not is_trading_time() and not ignore_hours:
        mins = minutes_until_market_open()
        print(f"\nMercado cerrado — próxima apertura en ~{mins} min")
        if mins > 60:
            print(f"Esperando hasta las 03:00 ARG del próximo día hábil...")
            while not is_trading_time():
                time.sleep(60)
            print("Mercado abierto. Iniciando monitoreo.")
    elif ignore_hours:
        print("[IGNORE HOURS] Saltando verificación de horario — modo test")

    poll_label = f"{POLL_SECONDS}s" if POLL_SECONDS < 60 else f"{POLL_SECONDS // 60} min"
    print(f"\nMonitoreo activo — polling cada {poll_label}")
    print("Presioná Ctrl+C para detener\n")

    eod_notified = False
    consecutive_fetch_errors = 0
    FETCH_ERROR_ALERT_THRESHOLD = 10  # ~50 seg de fallos consecutivos antes de emailear

    try:
        while True:
            now = arg_now()
            time_str = now.strftime("%H:%M:%S")

            # End of day
            if now.hour >= 15 and not eod_notified and not ignore_hours:
                eod_summary = f"Jornada finalizada a las {time_str} ARG.\n"
                if position:
                    eod_summary += (
                        f"Posición abierta en {asset} @ {position['entry_price']:.4f}\n"
                        f"SL: {position['sl']:.4f} | TP: {position['tp']:.4f}\n"
                        "La orden OCO sigue activa en Binance — cerrará automáticamente."
                    )
                else:
                    eod_summary += "Sin posiciones abiertas hoy."
                print(f"\n[{time_str}] FIN DE JORNADA")
                print(eod_summary)
                notify_eod(asset, eod_summary)
                eod_notified = True
                break

            if not is_trading_time() and not ignore_hours:
                print(f"[{time_str}] Fuera de horario — saliendo")
                break

            print(f"[{time_str}] Chequeando señales para {asset}...", end=" ")

            # If we have a position, check if it closed
            if position and not dry_run:
                status = get_position_status(symbol, position["oco_order_list_id"])
                if status in ("tp_hit", "sl_hit"):
                    result = "TP" if status == "tp_hit" else "SL"
                    entry = position["entry_price"]
                    exit_price = position["tp"] if status == "tp_hit" else position["sl"]
                    pnl_pct = (exit_price - entry) / entry * 100
                    if direction == "short":
                        pnl_pct = -pnl_pct
                    exit_p = position["tp"] if status == "tp_hit" else position["sl"]
                    tlog_close(result, exit_p)
                    print(f"Posición cerrada por {result} ({pnl_pct:+.2f}%)")
                    notify_close(asset, direction, result, pnl_pct)
                    position = None
                else:
                    curr = get_current_price(symbol)
                    print(f"Posición abierta | precio actual: {curr:.4f}")
                    time.sleep(POLL_SECONDS)
                    continue

            # Check entry signal
            if position is None:
                try:
                    df = fetch_recent_ohlcv(asset, timeframe)
                    signal = check_entry_signal(df, strat)
                    consecutive_fetch_errors = 0  # reset on success
                except Exception as e:
                    consecutive_fetch_errors += 1
                    print(f"Error al obtener datos: {e}")
                    if consecutive_fetch_errors >= FETCH_ERROR_ALERT_THRESHOLD:
                        notify_error("live_monitor fetch", f"[{consecutive_fetch_errors} fallos consecutivos] {e}")
                        consecutive_fetch_errors = 0  # reset para no spamear
                    time.sleep(POLL_SECONDS)
                    continue

                if signal:
                    print("SEÑAL DETECTADA!")
                    curr_price = float(df["close"].iloc[-1])
                    sl, tp = calculate_sl_tp(df, strat, curr_price)
                    print(f"  Precio: {curr_price:.4f} | SL: {sl:.4f} | TP: {tp:.4f}")

                    if dry_run:
                        print("  [DRY RUN] No se ejecuta la orden")
                        notify_entry(asset, direction, curr_price, sl, tp, TRADE_USDT / curr_price)
                    else:
                        try:
                            if direction == "long":
                                order = place_long_entry_with_oco(symbol, TRADE_USDT, sl, tp)
                                position = order
                                tlog_entry(
                                    asset, direction,
                                    order["entry_price"], order["sl"], order["tp"],
                                    order["quantity"], order["buy_order_id"],
                                    order["oco_order_list_id"]
                                )
                                notify_entry(
                                    asset, direction,
                                    order["entry_price"], order["sl"], order["tp"], order["quantity"]
                                )
                                print(f"  Orden ejecutada: qty={order['quantity']} | OCO ID={order['oco_order_list_id']}")
                            else:
                                print("  [SKIP] Short no implementado todavía en testnet")
                        except Exception as e:
                            print(f"  Error al ejecutar orden: {e}")
                            notify_error("live_monitor order", str(e))
                else:
                    print("sin señal")

            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        print("\n[CTRL+C] Monitor detenido manualmente")
        if position and not dry_run:
            print("Cancelando órdenes abiertas...")
            cancel_all_open_orders(symbol)
    finally:
        PID_FILE.unlink(missing_ok=True)

    print("\n=== MONITOR FINALIZADO ===")


def main():
    parser = argparse.ArgumentParser(description="Live Trading Monitor")
    parser.add_argument("--dry-run",       action="store_true", help="No ejecuta órdenes reales")
    parser.add_argument("--ignore-hours",  action="store_true", help="Ignora verificación de horario (solo para test)")
    args = parser.parse_args()
    run(dry_run=args.dry_run, ignore_hours=args.ignore_hours)


if __name__ == "__main__":
    main()
