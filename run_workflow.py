"""Main entry point for the daily trading strategy workflow."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "src"))

LOG_PATH = ROOT / "logs" / "workflow_last.log"


class _Tee:
    """Writes to multiple streams simultaneously (console + log file)."""
    def __init__(self, *files):
        self.files = files
    def write(self, data):
        for f in self.files:
            try: f.write(data)
            except Exception: pass
    def flush(self):
        for f in self.files:
            try: f.flush()
            except Exception: pass


def _setup_log():
    LOG_PATH.parent.mkdir(exist_ok=True)
    fh = open(LOG_PATH, "w", encoding="utf-8")
    sys.stdout = _Tee(sys.__stdout__, fh)
    sys.stderr = _Tee(sys.__stderr__, fh)

from asset_selector import select_best_asset, select_best_asset_local
from backtester import backtest_all
from data_fetcher import fetch_all, get_ohlcv
from notifier import notify_workflow_start
from pine_generator import generate_pine_script, generate_pine_with_claude
from ranker import format_ranking_text, get_top_n
from strategy_generator import generate_strategies


def load_config() -> dict:
    with open(ROOT / "config.json") as f:
        return json.load(f)


def save_last_run(status: str, strategy_name: str = "", error: str = "") -> None:
    payload = {
        "timestamp": datetime.now().isoformat(),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "status": status,
        "strategy_name": strategy_name,
        "error": error,
    }
    (ROOT / "last_run.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def save_history(asset: str, timeframe: str, top_row, reason: str,
                 n_tested: int, n_passed: int) -> None:
    hist_dir = ROOT / "history"
    hist_dir.mkdir(exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    path = hist_dir / f"{date_str}.json"
    record = {
        "date": date_str,
        "asset": asset,
        "timeframe": timeframe,
        "reason": reason,
        "n_tested": n_tested,
        "n_passed": n_passed,
        "top_strategy": {
            "strategy_name": str(top_row.get("strategy", "")),
            "direction":     str(top_row.get("direction", "long")),
            "win_rate":      float(top_row.get("win_rate", 0)),
            "profit_factor": float(top_row.get("profit_factor", 0)),
            "sharpe":        float(top_row.get("sharpe", 0)),
            "max_drawdown":  float(top_row.get("max_drawdown", 0)),
            "n_trades":      int(top_row.get("n_trades", 0)),
            "score":         float(top_row.get("score", 0)),
        },
    }
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")


def save_today_strategy(asset: str, timeframe: str, top_row, reason: str) -> Path:
    """Saves today's best strategy for live_monitor to consume."""
    import re
    name = str(top_row.get("strategy", ""))
    match_sl = re.search(r"SL([\d.]+)", name)
    match_tp = re.search(r"TP([\d.]+)", name)
    payload = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "asset": asset,
        "binance_symbol": asset.replace("/", ""),
        "timeframe": timeframe,
        "strategy_name": name,
        "direction": str(top_row.get("direction", "long")),
        "sl_atr_mult": float(match_sl.group(1)) if match_sl else 2.0,
        "tp_atr_mult": float(match_tp.group(1)) if match_tp else 2.5,
        "win_rate": float(top_row.get("win_rate", 0)),
        "profit_factor": float(top_row.get("profit_factor", 0)),
        "sharpe": float(top_row.get("sharpe", 0)),
        "max_drawdown": float(top_row.get("max_drawdown", 0)),
        "score": float(top_row.get("score", 0)),
        "reason": reason,
    }
    path = ROOT / "today_strategy.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_report(report: str, date_str: str) -> Path:
    path = ROOT / "reports" / f"{date_str}.md"
    path.write_text(report, encoding="utf-8")
    return path


def save_pine(code: str, asset: str, date_str: str) -> Path:
    safe = asset.replace("/", "-")
    path = ROOT / "pine_scripts" / f"{date_str}-{safe}.pine"
    path.write_text(code, encoding="utf-8")
    return path


def copy_to_vault(report: str, date_str: str) -> Path:
    vault_daily = ROOT.parent.parent / "daily"
    vault_daily.mkdir(exist_ok=True)
    dest = vault_daily / f"{date_str}.md"
    dest.write_text(report, encoding="utf-8")
    return dest


def build_report(date_str: str, asset: str, timeframe: str, reason: str,
                 ranking_text: str, top_strategy: dict, pine_path: Path) -> str:
    return f"""---
title: Trading Report {date_str}
date: {date_str}
tags: [trading, daily]
status: active
---

# Trading Report — {date_str}

## Activo seleccionado
**{asset}** | Timeframe: **{timeframe}**
Razón: {reason}

## {ranking_text}

## Mejor estrategia — detalles
- Nombre: `{top_strategy.get('strategy', 'N/A')}`
- Dirección: {top_strategy.get('direction', 'long').upper()}
- Win rate: {top_strategy.get('win_rate', 0)*100:.1f}%
- Profit factor: {top_strategy.get('profit_factor', 0):.2f}
- Sharpe: {top_strategy.get('sharpe', 0):.2f}
- Retorno total (backtest): {top_strategy.get('total_return', 0)*100:.2f}%
- Max drawdown: {top_strategy.get('max_drawdown', 0)*100:.1f}%
- Operaciones en período: {top_strategy.get('n_trades', 0)}

## Pine Script
Archivo: `{pine_path.name}`
Pegalo en TradingView → Pine Script Editor → Add to chart

---
*Generado automáticamente por trading-workflow*
"""


def run(args):
    cfg = load_config()
    date_str = datetime.now().strftime("%Y-%m-%d")

    print("\n=== TRADING WORKFLOW ===")
    print(f"Fecha: {date_str}")

    # Phase 1: Fetch data
    print("\n[1/5] Descargando datos de mercado...")
    if args.asset:
        tfs = [args.timeframe] if args.timeframe else cfg["timeframes"]
        data = {args.asset: {}}
        for tf in tfs:
            try:
                data[args.asset][tf] = get_ohlcv(args.asset, tf, args.force_refresh)
                print(f"  [OK] {args.asset} {tf}")
            except Exception as e:
                print(f"  [SKIP] {args.asset} {tf}: {e}")
    else:
        data = fetch_all(cfg["assets"], cfg["timeframes"], args.force_refresh)

    if not any(data.values()):
        save_last_run("error", error="No se pudieron obtener datos de mercado")
        print("ERROR: No se pudieron obtener datos.")
        return 1

    # Phase 2: Select best asset
    print("\n[2/5] Seleccionando mejor activo...")
    try:
        if args.no_claude or args.asset:
            asset, timeframe, reason = select_best_asset_local(data)
            if args.asset:
                asset = args.asset
                timeframe = args.timeframe or timeframe
                reason = "forzado por argumento"
        else:
            asset, timeframe, reason = select_best_asset(data, cfg)
    except Exception as e:
        print(f"  Fallback a selección local: {e}")
        asset, timeframe, reason = select_best_asset_local(data)

    print(f"  Elegido: {asset} {timeframe}")
    print(f"  Razón: {reason}")

    df = data.get(asset, {}).get(timeframe)
    if df is None or df.empty:
        print(f"ERROR: No hay datos para {asset} {timeframe}")
        return 1

    # Phase 3: Generate strategies
    print("\n[3/5] Generando combinaciones de estrategias...")
    strategies = generate_strategies()
    print(f"  {len(strategies)} estrategias a probar")

    if args.dry_run:
        print("  [DRY RUN] Probando todas las estrategias (sin guardar en vault)")

    # Phase 4: Backtest
    print("\n[4/5] Ejecutando backtesting...")
    results = backtest_all(df, strategies, cfg)
    print(f"  {len(results)} estrategias pasaron los filtros")

    if not results:
        save_last_run("error", error="Ninguna estrategia pasó los filtros mínimos")
        print("  Ninguna estrategia pasó los filtros mínimos.")
        print("  Sugerencia: revisar config.json (min_win_rate, min_trades)")
        return 1

    # Phase 5: Rank and generate Pine Script
    print("\n[5/5] Rankeando y generando Pine Script...")
    top = get_top_n(results, cfg)
    ranking_text = format_ranking_text(top)
    print(ranking_text)

    top_row = top.iloc[0]
    if args.dry_run or args.no_claude:
        pine_code = generate_pine_script(top_row, cfg["backtest"]["initial_capital"])
    else:
        try:
            pine_code = generate_pine_with_claude(
                top_row, asset, timeframe, top_row.to_dict(), cfg
            )
        except Exception as e:
            print(f"  Claude API falló, usando template base: {e}")
            pine_code = generate_pine_script(top_row, cfg["backtest"]["initial_capital"])

    pine_path = save_pine(pine_code, asset, date_str)
    print(f"\nPine Script guardado: {pine_path}")

    # Save today_strategy.json for live monitor
    strategy_path = save_today_strategy(asset, timeframe, top_row.to_dict(), reason)
    save_history(asset, timeframe, top_row.to_dict(), reason,
                 n_tested=len(strategies), n_passed=len(results))
    print(f"Estrategia del día guardada: {strategy_path}")

    # Send startup notification
    if not args.dry_run:
        notify_workflow_start(asset, timeframe, top_row.to_dict())

    # Build report
    report = build_report(
        date_str, asset, timeframe, reason,
        ranking_text, top_row.to_dict(), pine_path
    )
    report_path = save_report(report, date_str)
    print(f"Reporte guardado: {report_path}")

    if args.dry_run:
        print("\n[DRY RUN] Completado. No se guardó nada en el vault.")
        return 0

    # Confirmation
    print("\n" + "="*50)
    print("¿Guardar reporte en el vault de Obsidian? [s/N]: ", end="", flush=True)
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer in ("s", "si", "sí", "y", "yes"):
        vault_path = copy_to_vault(report, date_str)
        print(f"Reporte copiado al vault: {vault_path}")
    else:
        print("No se copió al vault.")

    save_last_run("ok", strategy_name=str(top_row.get("strategy", "")))
    print("\n=== WORKFLOW COMPLETADO ===")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Daily Trading Strategy Workflow")
    parser.add_argument("--asset",         help="Forzar activo específico (ej: BTC/USDT)")
    parser.add_argument("--timeframe",     help="Forzar timeframe (ej: 15m)")
    parser.add_argument("--dry-run",       action="store_true", help="Prueba sin guardar ni confirmar")
    parser.add_argument("--force-refresh", action="store_true", help="Re-descarga datos ignorando cache")
    parser.add_argument("--no-claude",     action="store_true", help="No usar Claude API (selección local)")
    args = parser.parse_args()
    _setup_log()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
