import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv

load_dotenv()

_GMAIL = os.getenv("GMAIL", "")
_APP_PW = os.getenv("GMAIL_APP_PASSWORD", "")


def send_email(subject: str, body: str, html: bool = False) -> bool:
    if not _GMAIL or not _APP_PW:
        print("[notifier] Gmail credentials not configured — skipping")
        return False
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[TradingBot] {subject}"
    msg["From"] = _GMAIL
    msg["To"] = _GMAIL
    mime_type = "html" if html else "plain"
    msg.attach(MIMEText(body, mime_type, "utf-8"))

    # Try SSL (465) first, then STARTTLS (587)
    for method, connect in [
        ("SSL-465", lambda: smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=15)),
        ("STARTTLS-587", lambda: _starttls_smtp()),
    ]:
        try:
            with connect() as smtp:
                smtp.login(_GMAIL, _APP_PW)
                smtp.send_message(msg)
            print(f"[notifier] Email sent via {method}: {subject}")
            return True
        except Exception as e:
            last_error = e

    print(
        f"[notifier] Email failed — verifica la Contraseña de Aplicación de Gmail.\n"
        f"  Pasos: myaccount.google.com → Seguridad → Verificación en 2 pasos → "
        f"Contraseñas de aplicaciones\n  Error: {last_error}"
    )
    return False


def _starttls_smtp():
    s = smtplib.SMTP("smtp.gmail.com", 587, timeout=15)
    s.ehlo()
    s.starttls()
    return s


def notify_workflow_start(asset: str, timeframe: str, strategy: dict) -> None:
    body = (
        f"Workflow diario iniciado.\n\n"
        f"Activo seleccionado: {asset}\n"
        f"Timeframe: {timeframe}\n"
        f"Estrategia: {strategy.get('strategy_name', 'N/A')}\n"
        f"Win rate: {strategy.get('win_rate', 0):.1%}\n"
        f"Profit factor: {strategy.get('profit_factor', 0):.2f}\n"
        f"Sharpe: {strategy.get('sharpe', 0):.2f}\n"
        f"Drawdown máx.: {strategy.get('max_drawdown', 0):.1%}\n"
        f"Score: {strategy.get('score', 0):.3f}\n\n"
        f"Monitoreo activo L-V 03:00-15:00 ARG."
    )
    send_email("Workflow iniciado", body)


def notify_entry(asset: str, direction: str, price: float, sl: float, tp: float, qty: float) -> None:
    side = "COMPRA (LONG)" if direction == "long" else "VENTA (SHORT)"
    body = (
        f"ENTRADA EJECUTADA\n\n"
        f"Activo: {asset}\n"
        f"Dirección: {side}\n"
        f"Precio entrada: {price:.4f}\n"
        f"Stop Loss: {sl:.4f}\n"
        f"Take Profit: {tp:.4f}\n"
        f"Cantidad: {qty:.6f}\n"
        f"R/R: {abs(tp - price) / abs(price - sl):.2f}:1"
    )
    send_email(f"ENTRADA {asset} {side}", body)


def notify_close(asset: str, direction: str, result: str, pnl_pct: float) -> None:
    emoji = "✅" if result == "TP" else "❌"
    body = (
        f"{emoji} POSICIÓN CERRADA\n\n"
        f"Activo: {asset}\n"
        f"Resultado: {result}\n"
        f"P&L: {pnl_pct:+.2f}%\n"
    )
    send_email(f"{result} {asset} {pnl_pct:+.2f}%", body)


def notify_eod(asset: str, summary: str) -> None:
    send_email(f"Fin de jornada — {asset}", summary)


def notify_error(context: str, error: str) -> None:
    send_email(f"ERROR en {context}", f"Error:\n{error}")
