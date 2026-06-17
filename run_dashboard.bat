@echo off
cd /d "%~dp0"
echo Iniciando TradingBot Dashboard...
start "" http://localhost:8501
streamlit run dashboard.py --server.headless true --server.port 8501 --browser.gatherUsageStats false
