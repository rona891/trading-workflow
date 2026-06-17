---
title: Trading Workflow
date: 2026-06-16
tags: [trading, proyecto, activo]
status: active
---

# PROYECTO: Trading Strategy Workflow

> Estado: **COMPLETO Y ACTIVO**  
> Última actualización: 2026-06-16

---

## Qué hace este sistema

Cada día de semana a las 03:00 ARG, automáticamente:

1. **Descarga datos de mercado** (BTC/USDT, ETH/USDT, SOL/USDT, SPY, QQQ, NVDA)
2. **Selecciona el mejor activo** del día (con Claude AI o modo local)
3. **Genera y backteatea 154 combinaciones** de indicadores técnicos
4. **Filtra solo señales** dentro del horario 03:00–15:00 ARG (= 06:00–18:00 UTC)
5. **Rankea estrategias** LONG por score compuesto
6. **Genera Pine Script v5** listo para TradingView
7. **Ejecuta trades automáticamente** en Binance testnet (paper trading)
8. **Notifica por Gmail** (entrada, cierre, fin de jornada, errores)

---

## Estructura de archivos

```
trading-workflow/
├── run_workflow.py          ← workflow principal (análisis + Pine Script)
├── live_monitor.py          ← monitor en vivo (señales + ejecución)
├── setup_scheduler.py       ← configura Windows Task Scheduler
├── start_trading_day.bat    ← disparo manual
├── config.json              ← parámetros del sistema
├── today_strategy.json      ← estrategia del día (generada por workflow)
├── .env                     ← credenciales (NO compartir)
├── src/
│   ├── data_fetcher.py      ← descarga OHLCV (ccxt + yfinance)
│   ├── asset_selector.py    ← selección con Claude API
│   ├── indicator_library.py ← indicadores (pandas-ta)
│   ├── strategy_generator.py ← 154 combinaciones de estrategias
│   ├── backtester.py        ← vectorbt, solo LONG, horario filtrado
│   ├── ranker.py            ← score compuesto
│   ├── pine_generator.py    ← Pine Script v5
│   ├── notifier.py          ← Gmail SMTP
│   └── broker_executor.py   ← Binance testnet (compra + OCO)
├── data/                    ← cache OHLCV
├── reports/                 ← reportes diarios .md
├── pine_scripts/            ← Pine Scripts generados
└── logs/                    ← logs del scheduler
```

---

## Horario

| Hora ARG | Hora UTC | Acción |
|----------|----------|--------|
| 03:00    | 06:00    | `run_workflow.py` inicia (análisis + selección) |
| 03:05    | 06:05    | `live_monitor.py` inicia (polling cada 5 min) |
| 03:00–15:00 | 06:00–18:00 | Señales activas |
| 15:00    | 18:00    | Monitor se detiene, notifica resumen |
| Solo L–V |          | Sistema no opera sábado/domingo |

---

## Indicadores disponibles (154 combinaciones)

Señales de entrada: RSI oversold/overbought, EMA cross (9/20, 20/50), MACD cross, BB bounce, Stoch cross, Supertrend flip

Filtros: VWAP filter, ADX filter

SL/TP basados en ATR (multiplicadores: SL 1.0–2.0x, TP 2.0–3.0x)

---

## Criterios de selección de estrategia

```
Score = win_rate*0.35 + profit_factor_norm*0.30 + sharpe_norm*0.20 + (1-drawdown)*0.15
```

Filtros mínimos:
- ≥8 operaciones en 90 días
- Win rate ≥ 45%
- Max drawdown ≤ 20%
- Solo LONG (spot Binance)

---

## Credenciales

Ver `.env` (no compartir):
- `ANTHROPIC_API_KEY` — Claude API
- `BINANCE_TESTNET_API_KEY` / `BINANCE_TESTNET_SECRET` — Binance testnet
- `GMAIL` / `GMAIL_APP_PASSWORD` — notificaciones

---

## Cómo correr manualmente

```bash
# Workflow completo (análisis del día)
python run_workflow.py

# Workflow sin Claude API (más rápido, selección local)
python run_workflow.py --no-claude

# Forzar activo específico
python run_workflow.py --asset BTC/USDT --timeframe 15m

# Monitor en vivo (después del workflow)
python live_monitor.py

# Monitor sin ejecutar órdenes
python live_monitor.py --dry-run

# Configurar scheduler (solo primera vez, ya hecho)
python setup_scheduler.py
```

---

## Estado actual

- ✅ Workflow diario completo (análisis + ranking + Pine Script)
- ✅ Binance testnet conectado (10,000 USDT simulados)
- ✅ Windows Task Scheduler: TradingWorkflow + TradingMonitor (06:00 y 06:05 UTC L–V)
- ✅ live_monitor.py: detección de señales + ejecución de órdenes OCO
- ⚠️ Gmail: requiere regenerar App Password (ver abajo)
- Solo LONG implementado (suficiente para spot Binance)

---

## Solución Gmail (PENDIENTE — acción manual requerida)

El email falla porque la Contraseña de Aplicación no es válida.

**Pasos para arreglarlo (5 minutos):**
1. Ir a `myaccount.google.com` con la cuenta `ronan0891@gmail.com`
2. Seguridad → **Verificación en 2 pasos** → asegúrate que esté **activada**
3. Buscar "**Contraseñas de aplicaciones**" (aparece solo si el paso 2 está activo)
4. Crear nueva contraseña → Seleccionar "Otro" → nombre: "TradingBot"
5. Copiar los 16 caracteres **sin espacios**
6. Abrir `.env` y reemplazar la línea: `GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx`
7. Testear: `python -c "import sys; sys.path.insert(0,'src'); from notifier import send_email; send_email('Test', 'Funciona!')"`

---

## Próximos pasos opcionales

- Conectar a cuenta Binance real (cambiar `TESTNET=false` en `.env`)
- Agregar Telegram como notificación alternativa
- Agregar soporte FUTURES (permite short selling)
- Expandir lista de activos en `config.json`
