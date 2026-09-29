"""Scheduled portfolio signal monitoring."""
from html import escape

from app import db
from app.opportunities import _signal, evaluate_history


async def scan_portfolio_signal_changes(services) -> list[str]:
    """Detect changes into directional technical states; never execute trades."""
    alerts = []
    for holding in db.get_holdings():
        symbol = holding.symbol.upper()
        rows, _error = await services.daily_history(symbol, outputsize=220)
        item = evaluate_history(symbol, rows or [])
        state = _signal(item)[1] if item is not None else "unavailable"
        key = f"opportunity_signal_{symbol}"
        previous = db.get_metric(key)
        previous_state = previous.value if previous else None
        db.set_metric(key, state)
        if state not in {"buy", "sell"} or state == previous_state:
            continue
        if state == "buy":
            headline = "🟢 <b>SEÑAL TÉCNICA ALCISTA · REVISAR POSIBLE AUMENTO</b>"
        else:
            headline = "🔴 <b>SEÑAL TÉCNICA BAJISTA · REVISAR POSIBLE REDUCCIÓN</b>"
        alerts.append(
            f"{headline}\n<b>{escape(symbol)}</b> · {escape(item.name)}\n"
            f"Cierre: {item.price:,.2f} {item.currency} · observado: {item.observed_at:%Y-%m-%d}\n"
            f"Momentum 21/63 sesiones: {item.momentum_21d:+.1%} / "
            f"{item.momentum_63d:+.1%} · índice técnico {item.score:.0f}/100.\n"
            "Confianza predictiva: <b>no calibrada</b>. Alerta de revisión, no una orden. "
            "Considera costes, exposición y tolerancia al riesgo."
        )
    return alerts
