"""
TradingBot Dashboard — Streamlit local app.
Run: streamlit run dashboard.py
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "src"))

ARG_TZ = timezone(timedelta(hours=-3))
INITIAL_BALANCE = 10_000.0
PID_MONITOR = ROOT / "bot_monitor.pid"
PID_WORKFLOW = ROOT / "bot_workflow.pid"

st.set_page_config(
    page_title="TradingBot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ──────────────────────────────────────────────────────────────────────

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #0e1117; }
.card {
    background: #1a1f2e;
    border-radius: 12px;
    padding: 18px 22px;
    border: 1px solid #2d3347;
    margin-bottom: 12px;
}
.card-title { font-size: 0.75rem; color: #8b92a5; text-transform: uppercase; letter-spacing: 1px; }
.card-value { font-size: 1.9rem; font-weight: 700; margin: 4px 0 0; }
.green { color: #00d084; }
.red   { color: #ff4b4b; }
.gray  { color: #8b92a5; }
.badge-green { background:#00d08422; color:#00d084; border-radius:6px; padding:2px 10px; font-size:.8rem; }
.badge-red   { background:#ff4b4b22; color:#ff4b4b; border-radius:6px; padding:2px 10px; font-size:.8rem; }
.badge-gray  { background:#8b92a522; color:#8b92a5; border-radius:6px; padding:2px 10px; font-size:.8rem; }
</style>
""", unsafe_allow_html=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def arg_now():
    return datetime.now(ARG_TZ)


def load_json(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def is_pid_alive(pid: int) -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, timeout=3
        )
        return str(pid) in result.stdout
    except Exception:
        return False


def get_process_status(pid_file: Path):
    if not pid_file.exists():
        return False, 0
    try:
        pid = int(pid_file.read_text().strip())
        alive = is_pid_alive(pid)
        if not alive:
            pid_file.unlink(missing_ok=True)
        return alive, pid
    except Exception:
        return False, 0


@st.cache_data(ttl=30, show_spinner="Consultando balance en Binance testnet...")
def get_binance_balance():
    try:
        from broker_executor import get_account_balance, get_current_price
        usdt = get_account_balance("USDT")
        btc  = get_account_balance("BTC")
        eth  = get_account_balance("ETH")
        btc_price = get_current_price("BTCUSDT")
        eth_price = get_current_price("ETHUSDT")
        portfolio = usdt + btc * btc_price + eth * eth_price
        return {"usdt": usdt, "btc": btc, "eth": eth,
                "btc_price": btc_price, "eth_price": eth_price,
                "portfolio": portfolio, "ok": True}
    except Exception as e:
        return {"usdt": 0, "btc": 0, "eth": 0,
                "btc_price": 0, "eth_price": 0,
                "portfolio": 0, "ok": False, "error": str(e)}


def load_trade_log() -> dict:
    return load_json(ROOT / "trade_log.json", {"trades": [], "open_position": None})


def load_history() -> list:
    d = ROOT / "history"
    if not d.exists():
        return []
    records = []
    for f in sorted(d.glob("*.json"), reverse=True):
        data = load_json(f)
        if data:
            records.append(data)
    return records


def load_config() -> dict:
    return load_json(ROOT / "config.json", {})


def save_config(cfg: dict) -> None:
    with open(ROOT / "config.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


_SIGNAL_NAMES = {
    "rsi_oversold":    "RSI sobrevendido",
    "rsi_overbought":  "RSI sobrecomprado",
    "rsi7_oversold":   "RSI(7) sobrevendido",
    "ema_cross_9_20":  "Cruce EMA 9/20",
    "ema_cross_20_50": "Cruce EMA 20/50",
    "macd_cross":      "Cruce MACD",
    "bb_bounce":       "Rebote Bollinger",
    "stoch_cross":     "Cruce Estocástico",
    "supertrend_flip": "Cambio Supertrend",
    "vwap_filter":     "Filtro VWAP",
    "adx_filter":      "Filtro ADX",
}


def friendly_strategy_name(raw_name: str) -> str:
    import re
    clean = re.sub(r"_SL[\d.]+_TP[\d.]+$", "", raw_name)
    parts = clean.split("+")
    return " + ".join(_SIGNAL_NAMES.get(p, p.replace("_", " ").title()) for p in parts)


# ── data ─────────────────────────────────────────────────────────────────────

monitor_alive, monitor_pid = get_process_status(PID_MONITOR)
workflow_alive, workflow_pid = get_process_status(PID_WORKFLOW)
binance = get_binance_balance()
trade_data = load_trade_log()
trades = trade_data.get("trades", [])
open_pos = trade_data.get("open_position")
today_str = arg_now().strftime("%Y-%m-%d")

# P&L from trade log (accurate — ignores testnet seed BTC/ETH)
pnl_total = sum(t.get("pnl_usdt", 0) for t in trades)
trades_today = [t for t in trades if t.get("date") == today_str]
pnl_today = sum(t.get("pnl_usdt", 0) for t in trades_today)

today_strat = load_json(ROOT / "today_strategy.json")
if today_strat and today_strat.get("date") != today_str:
    today_strat = None  # stale

# ── header ───────────────────────────────────────────────────────────────────

col_title, col_status, col_clock, col_btn = st.columns([4, 2, 2, 1])

with col_title:
    st.markdown("## 📈 TradingBot Dashboard")

with col_status:
    if monitor_alive:
        st.markdown('<span class="badge-green">● Monitor activo</span>', unsafe_allow_html=True)
    elif workflow_alive:
        st.markdown('<span class="badge-gray">● Workflow corriendo</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge-red">● Bot detenido</span>', unsafe_allow_html=True)

with col_clock:
    st.caption(f"🕐 {arg_now().strftime('%d/%m/%Y %H:%M:%S')} ARG")
    if not binance["ok"]:
        st.caption("⚠️ Sin conexión a Binance")

with col_btn:
    if st.button("↺", help="Actualizar"):
        st.cache_data.clear()
        st.rerun()

st.divider()

# ── top KPIs ─────────────────────────────────────────────────────────────────

k1, k2, k3, k4, k5 = st.columns(5)

with k1:
    st.metric("Balance USDT", f"${binance['usdt']:,.2f}")
with k2:
    pct = pnl_total / INITIAL_BALANCE * 100 if pnl_total else 0
    st.metric("P&L Total", f"${pnl_total:+,.2f}", delta=f"{pct:+.2f}%")
with k3:
    st.metric("P&L Hoy", f"${pnl_today:+,.2f}")
with k4:
    wins = sum(1 for t in trades if t.get("result") == "TP")
    wr_real = f"{wins/len(trades):.0%}" if trades else "—"
    st.metric("Win rate real", wr_real, delta=f"{len(trades)} trades")
with k5:
    if today_strat:
        fn = friendly_strategy_name(today_strat["strategy_name"])
        fn_short = fn[:28] + "…" if len(fn) > 28 else fn
    else:
        fn_short = "—"
    st.metric("Estrategia hoy", fn_short)

st.divider()

# ── tabs ─────────────────────────────────────────────────────────────────────

tab_cuenta, tab_estrat, tab_trades_tab, tab_ctrl = st.tabs([
    "📊  Cuenta", "🎯  Estrategia", "💹  Trades", "⚙️  Control"
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB: CUENTA
# ══════════════════════════════════════════════════════════════════════════════
with tab_cuenta:

    # Open position card
    if open_pos:
        entry = open_pos["entry_price"]
        try:
            from broker_executor import get_current_price
            curr = get_current_price(open_pos["binance_symbol"])
            float_pnl = (curr - entry) * open_pos["quantity"]
            float_pct = (curr - entry) / entry * 100
        except Exception:
            curr, float_pnl, float_pct = entry, 0.0, 0.0

        pnl_color = "green" if float_pnl >= 0 else "red"
        st.markdown(f"""
        <div class="card">
          <div class="card-title">🔵 Posición abierta — {open_pos['asset']} {open_pos['direction'].upper()}</div>
          <br>
          <b>Entrada:</b> ${entry:,.4f} &nbsp;|&nbsp;
          <b>Precio actual:</b> ${curr:,.4f} &nbsp;|&nbsp;
          <b>Cantidad:</b> {open_pos['quantity']:.6f}<br><br>
          <b>Stop Loss:</b> <span class="red">${open_pos['sl']:,.4f}</span> &nbsp;|&nbsp;
          <b>Take Profit:</b> <span class="green">${open_pos['tp']:,.4f}</span> &nbsp;|&nbsp;
          <b>P&L flotante:</b> <span class="{pnl_color}">${float_pnl:+.2f} ({float_pct:+.2f}%)</span>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.info("Sin posiciones abiertas")

    # Account breakdown (USDT only — ignores testnet seed BTC/ETH)
    if binance["ok"] and open_pos:
        st.subheader("En posición")
        c1, c2, c3 = st.columns(3)
        c1.metric("USDT libre", f"${binance['usdt']:,.2f}")
        c2.metric("USDT en trade", f"~${INITIAL_BALANCE - binance['usdt']:,.2f}")
        c3.metric("BTC en hold", f"{binance['btc']:.6f}")

    # Equity curve
    st.subheader("Equity Curve")
    if trades:
        df_eq = pd.DataFrame(trades)
        df_eq["cum_pnl"] = df_eq["pnl_usdt"].cumsum()
        df_eq["balance"] = INITIAL_BALANCE + df_eq["cum_pnl"]
        df_eq["color"] = df_eq["pnl_usdt"].apply(lambda x: "#00d084" if x >= 0 else "#ff4b4b")
        labels = [f"{t.get('date','')} {t.get('close_time','')}" for t in trades]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=list(range(1, len(df_eq)+1)),
            y=df_eq["balance"],
            mode="lines+markers",
            line=dict(color="#00d084", width=2),
            marker=dict(color=df_eq["color"].tolist(), size=9, line=dict(width=1, color="#0e1117")),
            hovertemplate="Trade %{x}<br>Balance: $%{y:,.2f}<extra></extra>",
            customdata=labels,
        ))
        fig.add_hline(y=INITIAL_BALANCE, line_dash="dot", line_color="#8b92a5",
                      annotation_text="Capital inicial", annotation_position="bottom right")
        fig.update_layout(
            template="plotly_dark", height=320, paper_bgcolor="#1a1f2e", plot_bgcolor="#1a1f2e",
            margin=dict(l=0, r=10, t=10, b=0),
            yaxis_title="Balance (USDT)", xaxis_title="Nro. de trade",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("El gráfico aparecerá después del primer trade ejecutado.")

    # Daily P&L bar chart
    if trades:
        df_all = pd.DataFrame(trades)
        daily = df_all.groupby("date")["pnl_usdt"].sum().reset_index()
        fig2 = go.Figure(go.Bar(
            x=daily["date"], y=daily["pnl_usdt"],
            marker_color=["#00d084" if v >= 0 else "#ff4b4b" for v in daily["pnl_usdt"]],
        ))
        fig2.update_layout(
            title="P&L por día", template="plotly_dark", height=220,
            paper_bgcolor="#1a1f2e", plot_bgcolor="#1a1f2e",
            margin=dict(l=0, r=0, t=30, b=0), showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)


# ══════════════════════════════════════════════════════════════════════════════
# TAB: ESTRATEGIA — helpers
# ══════════════════════════════════════════════════════════════════════════════

_SIGNAL_EXPLAIN = {
    "rsi_oversold":    "el RSI cae por debajo de 30 (el activo está muy castigado y puede rebotar hacia arriba)",
    "rsi7_oversold":   "el RSI de 7 períodos cae por debajo de 30 (versión más sensible del RSI)",
    "ema_cross_9_20":  "la media móvil rápida (EMA 9) cruza hacia arriba la media lenta (EMA 20), señalando que la tendencia corta se volvió alcista",
    "ema_cross_20_50": "la EMA 20 cruza hacia arriba la EMA 50, señalando una tendencia alcista más consolidada",
    "macd_cross":      "la línea MACD cruza hacia arriba su línea de señal, indicando momentum alcista",
    "bb_bounce":       "el precio toca la banda inferior de Bollinger y rebota, sugiriendo que llegó a un extremo de volatilidad",
    "stoch_cross":     "las dos líneas del Estocástico se cruzan en zona de sobreventa (por debajo de 20)",
    "supertrend_flip": "el indicador Supertrend cambia de rojo a verde, confirmando que la tendencia giró al alza",
    "vwap_filter":     "el precio está por encima del VWAP (precio promedio del día ponderado por volumen), confirmando sesgo alcista",
    "adx_filter":      "el ADX está por encima de 25, lo que confirma que hay una tendencia fuerte (no solo ruido lateral)",
}


@st.dialog("🔍 Cómo funciona la estrategia de hoy", width="large")
def show_strategy_explanation(strat: dict):
    import re
    name = strat.get("strategy_name", "")
    clean = re.sub(r"_SL[\d.]+_TP[\d.]+$", "", name)
    signals = clean.split("+")
    sl = strat.get("sl_atr_mult", 2.0)
    tp = strat.get("tp_atr_mult", 2.5)
    wr = strat.get("win_rate", 0)
    pf = strat.get("profit_factor", 0)

    friendly = friendly_strategy_name(name)
    st.markdown(f"### {friendly}")
    st.caption(f"Activo: {strat.get('asset','')} · Timeframe: {strat.get('timeframe','')} · Solo LONG (compra)")
    st.divider()

    st.markdown("#### ¿Cuándo entra el bot?")
    st.markdown(
        "El bot revisa el mercado cada 5 minutos. Para abrir una posición, "
        "**todas** las siguientes condiciones deben cumplirse al mismo tiempo:"
    )
    for sig in signals:
        explain = _SIGNAL_EXPLAIN.get(sig, sig.replace("_", " "))
        label = _SIGNAL_NAMES.get(sig, sig)
        st.markdown(f"- **{label}:** {explain}.")

    st.divider()
    st.markdown("#### ¿Cómo sale?")
    st.markdown(
        f"Cuando entra, coloca dos órdenes automáticas en Binance (OCO):\n\n"
        f"- **Stop Loss a {sl}x ATR por debajo** del precio de entrada — si el mercado baja demasiado, cierra la posición y limita la pérdida.\n"
        f"- **Take Profit a {tp}x ATR por encima** del precio de entrada — si el mercado sube lo suficiente, cierra la posición y toma la ganancia.\n\n"
        f"La que se active primero cancela la otra automáticamente. No hace falta estar mirando."
    )

    st.divider()
    st.markdown("#### ¿Qué dicen los números del backtest?")
    st.markdown(
        f"En los últimos 90 días, esta combinación de señales funcionó así:\n\n"
        f"- De cada 10 trades, aproximadamente **{wr*10:.0f} terminaron en ganancia**.\n"
        f"- Por cada 1 USD perdido, se ganaron **{pf:.1f} USD** en promedio.\n"
        f"- El drawdown máximo fue de **{strat.get('max_drawdown', 0):.1%}** "
        f"(la peor racha bajista del balance).\n\n"
        f"*Estos números son de datos históricos — el rendimiento futuro puede variar.*"
    )


@st.dialog("📖 Glosario de términos", width="large")
def show_glossary():
    st.markdown("""
### Métricas de rendimiento

**P&L (Profit & Loss)**
Ganancia o pérdida en dinero. Si el bot compra BTC a 65.000 USD y lo vende a 66.000 USD, el P&L es +1.000 USD.
- Verde con + = ganancia
- Rojo con – = pérdida

---

**Win Rate**
Porcentaje de trades que terminaron en ganancia sobre el total.
- **60%** significa que de cada 10 operaciones, 6 ganaron y 4 perdieron.
- Por encima del 50% ya es positivo, pero no es lo único que importa (ver Profit Factor).

---

**Profit Factor**
Cuánto ganás por cada dólar que perdés.
- **2.0** = por cada 1 USD perdido, ganaste 2 USD. Muy bueno.
- **1.0** = empate exacto (ni ganás ni perdés).
- Por debajo de **1.0** = estrategia perdedora.

---

**Sharpe Ratio**
Qué tan consistente es la ganancia en relación al riesgo que tomás.
- Mayor a **1.0** = aceptable
- Mayor a **2.0** = bueno
- Mayor a **3.0** = excelente
- Un Sharpe alto significa que la curva de ganancias es suave, sin grandes altibajos.

---

**Max Drawdown**
La mayor caída desde un pico hasta el valle siguiente, expresada en porcentaje.
- Si el balance llegó a 10.500 USD y luego bajó a 10.000 USD, el drawdown fue de 4.7%.
- Cuanto menor, mejor. El sistema descarta estrategias con drawdown mayor al 20%.

---

**Score**
Puntuación combinada que el sistema calcula para rankear las estrategias. Mezcla los cuatro indicadores anteriores con estos pesos:

Win Rate 35% + Profit Factor 30% + Sharpe 20% + (inverso del Drawdown) 15%

El bot elige siempre la estrategia con el Score más alto del día.

---

### Órdenes y ejecución

**SL — Stop Loss**
Precio al que el bot cierra la posición automáticamente si el mercado va en contra, para limitar la pérdida.
- Ejemplo: comprás a 65.000 USD con SL en 64.000 USD → si baja a 64.000, se vende y perdés 1.000 USD.

**TP — Take Profit**
Precio al que el bot cierra la posición automáticamente cuando ganó lo suficiente.
- Ejemplo: comprás a 65.000 USD con TP en 67.000 USD → si sube a 67.000, se vende y ganás 2.000 USD.

**OCO (One Cancels the Other)**
Orden doble que combina SL y TP al mismo tiempo. Cuando una se activa, la otra se cancela sola. Es lo que usa el bot para no tener que estar mirando.

**Long**
Comprar un activo esperando que suba. El bot actualmente solo opera en Long (compra y luego vende).

**ATR (Average True Range)**
Medida de cuánto se mueve un activo en promedio por vela. Sirve para calcular el SL y TP de forma dinámica: si el mercado se mueve mucho, el SL se pone más lejos para evitar que el ruido normal lo active.

---

### Indicadores técnicos

**EMA (Exponential Moving Average)**
Promedio del precio que le da más peso a los datos recientes. Sirve para identificar tendencias.
- EMA cross 9/20 = cuando la EMA de 9 períodos cruza hacia arriba la de 20, es señal de compra.

**MACD**
Diferencia entre dos EMAs. Cuando la línea MACD cruza hacia arriba su señal, indica momento alcista.

**RSI (Relative Strength Index)**
Oscilador entre 0 y 100 que mide si el activo está sobrecomprado o sobrevendido.
- Por debajo de **30** = sobrevendido (posible rebote hacia arriba).
- Por encima de **70** = sobrecomprado (posible caída).

**Bollinger Bands**
Bandas de volatilidad alrededor del precio. Cuando el precio toca la banda inferior, puede ser señal de rebote.

**VWAP (Volume Weighted Average Price)**
Precio promedio ponderado por volumen del día. Si el precio está por encima del VWAP, el mercado tiene sesgo alcista.

**ADX (Average Directional Index)**
Mide la fuerza de la tendencia (no su dirección). Por encima de **25** indica que hay una tendencia clara.

**Supertrend**
Indicador que sigue la tendencia y cambia de color cuando el precio cruza. Verde = tendencia alcista, rojo = bajista.

**Stochastic**
Oscilador parecido al RSI. El cruce de sus dos líneas indica posibles cambios de dirección.

---

### Backtesting

**Backtest**
Probar una estrategia con datos históricos del pasado para ver cómo hubiera funcionado. El sistema hace esto cada mañana con los últimos 90 días de datos.

**Timeframe**
El tamaño de cada vela en el gráfico.
- **15m** = cada vela representa 15 minutos de actividad.
- **1h** = cada vela es 1 hora.

**Señal**
Momento exacto en que los indicadores se alinean y el bot decide entrar al mercado.
""")


with tab_estrat:

    col_hdr, col_glos = st.columns([5, 1])
    with col_hdr:
        pass
    with col_glos:
        if st.button("📖 Glosario", use_container_width=True):
            show_glossary()

    if today_strat:
        friendly_name = friendly_strategy_name(today_strat["strategy_name"])
        col_title_s, col_explain_btn = st.columns([4, 1])
        with col_title_s:
            st.subheader(f"Estrategia de hoy — {friendly_name}")
            st.caption(f"{today_strat['asset']} · {today_strat['timeframe']} · {today_strat['direction'].upper()}")
        with col_explain_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("🔍 ¿Cómo funciona?", use_container_width=True):
                show_strategy_explanation(today_strat)

        col_a, col_b, col_c, col_d, col_e = st.columns(5)
        col_a.metric("Win Rate",      f"{today_strat['win_rate']:.1%}")
        col_b.metric("Profit Factor", f"{today_strat['profit_factor']:.2f}")
        col_c.metric("Sharpe",        f"{today_strat['sharpe']:.2f}")
        col_d.metric("Max Drawdown",  f"{today_strat['max_drawdown']:.1%}")
        col_e.metric("Score",         f"{today_strat['score']:.3f}")

        # Pine Script viewer
        pine_dir = ROOT / "pine_scripts"
        pine_files = sorted(pine_dir.glob("*.pine"), reverse=True) if pine_dir.exists() else []
        today_pine = [f for f in pine_files if today_str in f.name]
        if today_pine:
            with st.expander("📄 Ver Pine Script de hoy"):
                st.code(today_pine[0].read_text(encoding="utf-8"), language="javascript")
    else:
        st.warning("No hay estrategia para hoy. El workflow arranca automáticamente a las **03:00 ARG**.")

    # Historical strategies table
    history = load_history()
    if history:
        st.subheader("Historial de estrategias elegidas")
        rows = []
        for h in history:
            ts = h.get("top_strategy", {})
            rows.append({
                "Fecha":     h.get("date", ""),
                "Activo":    h.get("asset", ""),
                "TF":        h.get("timeframe", ""),
                "Estrategia": friendly_strategy_name(ts.get("strategy_name", "")),
                "Win Rate":  f"{ts.get('win_rate', 0):.1%}",
                "PF":        f"{ts.get('profit_factor', 0):.2f}",
                "Sharpe":    f"{ts.get('sharpe', 0):.2f}",
                "DD":        f"{ts.get('max_drawdown', 0):.1%}",
                "Score":     f"{ts.get('score', 0):.3f}",
                "Testeadas": h.get("n_tested", 0),
                "Pasaron":   h.get("n_passed", 0),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        # Win rate chart history
        if len(history) >= 2:
            dates_h = [h.get("date") for h in history[::-1]]
            wrs_h   = [h.get("top_strategy", {}).get("win_rate", 0)*100 for h in history[::-1]]
            pfs_h   = [h.get("top_strategy", {}).get("profit_factor", 0) for h in history[::-1]]

            fig3 = go.Figure()
            fig3.add_trace(go.Bar(x=dates_h, y=wrs_h, name="Win Rate %",
                                  marker_color="#4e8ef7", yaxis="y"))
            fig3.add_trace(go.Scatter(x=dates_h, y=pfs_h, name="Profit Factor",
                                      line=dict(color="#f7c84e", width=2), yaxis="y2"))
            fig3.update_layout(
                template="plotly_dark", height=260,
                paper_bgcolor="#1a1f2e", plot_bgcolor="#1a1f2e",
                margin=dict(l=0, r=0, t=20, b=0),
                yaxis=dict(title="Win Rate %"),
                yaxis2=dict(title="Profit Factor", overlaying="y", side="right"),
                legend=dict(orientation="h", y=1.1),
            )
            st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("El historial se va construyendo a medida que el workflow corre cada día.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB: TRADES
# ══════════════════════════════════════════════════════════════════════════════
with tab_trades_tab:

    if trades:
        df_t = pd.DataFrame(trades)
        wins_n  = (df_t["result"] == "TP").sum()
        losses_n = (df_t["result"] == "SL").sum()
        best_trade  = df_t["pnl_usdt"].max()
        worst_trade = df_t["pnl_usdt"].min()

        s1, s2, s3, s4 = st.columns(4)
        s1.metric("TP (ganancias)", int(wins_n))
        s2.metric("SL (pérdidas)", int(losses_n))
        s3.metric("Mejor trade", f"${best_trade:+.2f}")
        s4.metric("Peor trade", f"${worst_trade:+.2f}")

        st.divider()

        # Table
        cols_map = {
            "date": "Fecha", "asset": "Activo", "direction": "Dir",
            "entry_price": "Entrada", "exit_price": "Salida",
            "result": "Resultado", "pnl_usdt": "P&L USDT", "pnl_pct": "P&L %",
        }
        df_show = df_t[[c for c in cols_map if c in df_t.columns]].rename(columns=cols_map).copy()
        if "P&L USDT" in df_show.columns:
            df_show["P&L USDT"] = df_show["P&L USDT"].map(lambda x: f"${x:+.2f}")
        if "P&L %" in df_show.columns:
            df_show["P&L %"] = df_show["P&L %"].map(lambda x: f"{x:+.2f}%")

        st.dataframe(df_show.iloc[::-1].reset_index(drop=True),
                     use_container_width=True, hide_index=True)
    else:
        st.info("Aún no hay trades ejecutados. El primer trade aparecerá aquí cuando el monitor detecte una señal.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB: CONTROL
# ══════════════════════════════════════════════════════════════════════════════
with tab_ctrl:

    col_bots, col_cfg = st.columns(2)

    with col_bots:
        st.subheader("Control del bot")

        # Monitor
        st.markdown("**Monitor en vivo**")
        if monitor_alive:
            st.success(f"🟢 Corriendo (PID {monitor_pid})")
            c1, c2 = st.columns(2)
            if c1.button("🔴 Detener", key="stop_monitor"):
                subprocess.run(["taskkill", "/F", "/PID", str(monitor_pid)],
                               capture_output=True)
                PID_MONITOR.unlink(missing_ok=True)
                st.cache_data.clear()
                st.rerun()
            if c2.button("🔍 Ignorar horario (test)", key="mon_test"):
                proc = subprocess.Popen(
                    [sys.executable, str(ROOT / "live_monitor.py"),
                     "--dry-run", "--ignore-hours"],
                    cwd=str(ROOT),
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
                PID_MONITOR.write_text(str(proc.pid))
                time.sleep(1)
                st.cache_data.clear()
                st.rerun()
        else:
            st.error("🔴 Detenido")
            c1, c2 = st.columns(2)
            if c1.button("🟢 Iniciar monitor", key="start_monitor"):
                proc = subprocess.Popen(
                    [sys.executable, str(ROOT / "live_monitor.py")],
                    cwd=str(ROOT),
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
                PID_MONITOR.write_text(str(proc.pid))
                time.sleep(1)
                st.cache_data.clear()
                st.rerun()
            if c2.button("🧪 Test (dry-run)", key="start_monitor_test"):
                proc = subprocess.Popen(
                    [sys.executable, str(ROOT / "live_monitor.py"),
                     "--dry-run", "--ignore-hours"],
                    cwd=str(ROOT),
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
                PID_MONITOR.write_text(str(proc.pid))
                time.sleep(1)
                st.cache_data.clear()
                st.rerun()

        st.divider()

        # Workflow
        st.markdown("**Análisis del día (Workflow)**")
        if workflow_alive:
            st.warning(f"🟡 Corriendo (PID {workflow_pid})")
        else:
            if st.button("▶️ Ejecutar análisis ahora", key="run_workflow"):
                proc = subprocess.Popen(
                    [sys.executable, str(ROOT / "run_workflow.py"), "--no-claude"],
                    cwd=str(ROOT),
                    creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
                PID_WORKFLOW.write_text(str(proc.pid))
                st.info("Workflow iniciado — se abre una ventana de terminal.")

        st.divider()

        # Emergency close
        if open_pos:
            st.markdown("**Emergencia**")
            st.warning(f"Posición abierta: {open_pos['asset']} {open_pos['direction'].upper()}")
            if st.button("🚨 Cancelar órdenes OCO", type="primary", key="cancel_orders"):
                try:
                    from broker_executor import cancel_all_open_orders
                    cancel_all_open_orders(open_pos["binance_symbol"])
                    st.success("Órdenes OCO canceladas. La posición permanece abierta — cerrala manualmente en Binance.")
                except Exception as e:
                    st.error(f"Error: {e}")

    with col_cfg:
        st.subheader("Configuración")
        cfg = load_config()
        sched = cfg.get("schedule", {})

        assets_all = (cfg.get("assets", {}).get("crypto", []) +
                      cfg.get("assets", {}).get("stocks", []))
        timeframes = cfg.get("timeframes", ["5m", "15m", "1h", "4h"])

        force_asset = sched.get("force_asset") or "(automático)"
        force_tf    = sched.get("force_timeframe") or "(automático)"
        capital_val = int(sched.get("trade_usdt", 190))

        sel_asset = st.selectbox(
            "Activo forzado mañana",
            ["(automático)"] + assets_all,
            index=(["(automático)"] + assets_all).index(force_asset)
                  if force_asset in ["(automático)"] + assets_all else 0,
        )
        sel_tf = st.selectbox(
            "Timeframe forzado",
            ["(automático)"] + timeframes,
            index=(["(automático)"] + timeframes).index(force_tf)
                  if force_tf in ["(automático)"] + timeframes else 0,
        )
        capital = st.number_input(
            "Capital por operación (USDT)",
            min_value=10, max_value=9_900,
            value=capital_val, step=10,
        )
        min_wr = st.slider(
            "Win rate mínimo (%)",
            min_value=30, max_value=70,
            value=int(cfg.get("backtest", {}).get("min_win_rate", 0.45) * 100),
        )

        if st.button("💾 Guardar configuración", type="primary"):
            cfg.setdefault("schedule", {})["trade_usdt"] = capital
            cfg["schedule"]["force_asset"] = None if sel_asset == "(automático)" else sel_asset
            cfg["schedule"]["force_timeframe"] = None if sel_tf == "(automático)" else sel_tf
            cfg.setdefault("backtest", {})["min_win_rate"] = min_wr / 100
            save_config(cfg)
            st.success("✅ Configuración guardada — aplica en el próximo análisis")

        st.divider()
        st.caption("Próxima ejecución automática: **mañana 03:00 ARG** (L-V)")
        st.caption(f"Scheduler: TradingWorkflow + TradingMonitor activos")


# ── auto refresh ─────────────────────────────────────────────────────────────

st.divider()
with st.container():
    col_ar, _ = st.columns([2, 5])
    with col_ar:
        auto = st.toggle("Auto-refresh cada 30 seg", value=False, key="ar")

if auto:
    time.sleep(30)
    st.cache_data.clear()
    st.rerun()
