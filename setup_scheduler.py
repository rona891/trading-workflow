"""
Configures Windows Task Scheduler for the trading workflow.
Creates two tasks:
  1. TradingWorkflow  — runs run_workflow.py at 06:00 UTC Mon-Fri (= 03:00 ARG)
  2. TradingMonitor   — runs live_monitor.py at 06:05 UTC Mon-Fri (5 min after workflow)

Usage: python setup_scheduler.py [--remove]
Requires admin rights (run PowerShell as Administrator).
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
PYTHON = sys.executable
WORKFLOW = str(ROOT / "run_workflow.py")
MONITOR = str(ROOT / "live_monitor.py")
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)


def run_ps(cmd: str) -> tuple[int, str]:
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    return result.returncode, output


def create_task(name: str, script: str, hour: int, minute: int, args: str = "") -> None:
    log_file = LOG_DIR / f"{name}.log"
    action = f'"{PYTHON}" "{script}" {args}'
    # Wrap in cmd to capture stdout to log
    action_cmd = f'cmd /c "{action} >> \\"{log_file}\\" 2>&1"'

    ps = f"""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At {hour:02d}:{minute:02d}
$action  = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c "{PYTHON}" "{script}" {args} >> "{log_file}" 2>&1'
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 14)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -RunLevel Highest
Register-ScheduledTask -TaskName "{name}" -Trigger $trigger -Action $action -Settings $settings -Principal $principal -Force
"""
    code, out = run_ps(ps)
    if code == 0:
        print(f"  [OK] Tarea creada: {name} ({hour:02d}:{minute:02d} UTC L-V)")
    else:
        print(f"  [ERROR] {name}: {out}")


def remove_task(name: str) -> None:
    code, out = run_ps(f'Unregister-ScheduledTask -TaskName "{name}" -Confirm:$false')
    if code == 0:
        print(f"  [OK] Tarea eliminada: {name}")
    else:
        print(f"  [SKIP] {name}: {out.strip()}")


def setup():
    print("=== CONFIGURANDO WINDOWS TASK SCHEDULER ===")
    print("IMPORTANTE: Requiere ejecutar como Administrador\n")

    # 06:00 UTC = 03:00 ARG — workflow principal
    create_task("TradingWorkflow", WORKFLOW, hour=6, minute=0, args="--no-claude")
    # 06:05 UTC — monitor (arranca 5 min después para que el workflow termine)
    create_task("TradingMonitor", MONITOR, hour=6, minute=5)

    print("\nTareas programadas:")
    print("  TradingWorkflow  -> 06:00 UTC L-V (= 03:00 ARG)")
    print("  TradingMonitor   -> 06:05 UTC L-V (= 03:05 ARG)")
    print(f"\nLogs en: {LOG_DIR}")
    print("\nPara ver las tareas: Abre 'Programador de tareas' (taskschd.msc)")
    print("Para eliminarlas:    python setup_scheduler.py --remove")


def remove():
    print("=== ELIMINANDO TAREAS DEL SCHEDULER ===")
    remove_task("TradingWorkflow")
    remove_task("TradingMonitor")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--remove", action="store_true", help="Eliminar tareas")
    args = parser.parse_args()
    if args.remove:
        remove()
    else:
        setup()


if __name__ == "__main__":
    main()
