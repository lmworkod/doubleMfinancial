"""Daily portfolio digest formatting for the authorized Telegram owner."""
from datetime import UTC, datetime

from app import db
from app.portfolio import portfolio_snapshot


def build_daily_digest(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    lines: list[str] = [f"📊 DoubleM Financial · Resumen diario ({now.astimezone().strftime('%d/%m/%Y')})"]
    items, total, coverage = portfolio_snapshot()
    if not items:
        lines.extend(["", "Inventario: no hay posiciones registradas."])
    else:
        lines.extend(["", f"💼 Valor conocido: {total:,.2f} EUR",
                      f"Cobertura de valoración: {coverage:.0%}", "", "📦 Inventario"])
        for item in items:
            if item.price is None:
                lines.append(f"• {item.symbol}: {item.quantity:g} uds. · sin cotización")
                continue
            value = f"{item.market_value:,.2f} EUR" if item.market_value is not None else "valor EUR no disponible"
            pnl = f" · P/L desde coste: {item.pnl:+,.2f} EUR" if item.pnl is not None else ""
            lines.append(f"• {item.symbol}: {item.quantity:g} × {item.price:,.4f} {item.currency} · {value}{pnl}")
        lines.extend(["", "Variación diaria: no calculable de forma fiable; la base de datos solo conserva la última cotización."])
    lines.extend(["", "🌐 Datos macro"])
    for key, label in (("fed_funds", "Fed Funds"), ("ust10y", "Treasury 10Y"), ("usd_broad", "USD broad")):
        metric = db.get_metric(f"fred_{key}")
        asof = db.get_metric(f"fred_{key}_as_of")
        lines.append(f"• {label}: {metric.value if metric else 'sin dato'} (observación: {asof.value if asof else '—'})")
    fx = db.get_metric("fx_usd_per_eur")
    fx_asof = db.get_metric("fx_usd_per_eur_as_of")
    lines.append(f"• USD/EUR de referencia: {fx.value if fx else 'sin dato'} (observación: {fx_asof.value if fx_asof else '—'})")
    market_refresh, macro_refresh = db.get_metric("last_quote_refresh"), db.get_metric("last_macro_refresh")
    lines.extend(["", "🕒 Últimas consultas",
                  f"• Mercado: {market_refresh.value if market_refresh else 'pendiente'}",
                  f"• Macro: {macro_refresh.value if macro_refresh else 'pendiente'}",
                  "", "Los cierres diarios pueden corresponder al último día hábil. Las cotizaciones fallidas conservan el último valor válido; comprueba su fecha antes de interpretar la valoración. El P/L usa el tipo FX actual, no el histórico. No incluye efectivo ni comisiones. El modelo SP500-VRM sigue sin probabilidades calibradas (no calibradas ni validadas)."])
    return "\n".join(lines)
