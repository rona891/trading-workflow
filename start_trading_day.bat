@echo off
REM Manual trigger: runs workflow + monitor sequentially
REM Double-click this file or run from cmd to start a trading day manually

cd /d "%~dp0"
set PYTHONPATH=%~dp0src

echo ========================================
echo  TRADING WORKFLOW - INICIO MANUAL
echo ========================================
echo Hora: %date% %time%
echo.

REM Step 1: Run main workflow (generates strategy + Pine Script)
echo [1/2] Ejecutando workflow principal...
python run_workflow.py
if errorlevel 1 (
    echo ERROR en el workflow principal.
    pause
    exit /b 1
)

echo.
echo [2/2] Iniciando monitor en vivo...
echo Presiona Ctrl+C para detener el monitor
echo.
python live_monitor.py

echo.
echo ========================================
echo  JORNADA FINALIZADA
echo ========================================
pause
