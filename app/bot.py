import logging
from datetime import UTC, datetime
from html import escape

from aiogram import Bot, Dispatcher
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app import db
from app.config import settings
from app.fx import quote_currency
from app.portfolio import portfolio_snapshot
from app.services import Services

logger = logging.getLogger(__name__)


def build_bot(services: Services) -> tuple[Bot, Dispatcher]:
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    bot, dp = Bot(settings.telegram_bot_token), Dispatcher()

    async def authorized(message: Message) -> bool:
        allowed = settings.allowed_user_ids
        if not allowed:
            await message.answer("Acceso privado no configurado: establece TELEGRAM_ALLOWED_USER_IDS.")
            return False
        if message.from_user is None or message.from_user.id not in allowed:
            logger.warning("Unauthorized Telegram command denied")
            return False
        return True

    @dp.message(CommandStart())
    async def start(message: Message) -> None:
        if await authorized(message):
            await message.answer("📊 <b>DOUBLEM FINANCIAL</b>\n\n🟢 Bot operativo. Usa /help para consultar los comandos.", parse_mode="HTML")

    @dp.message(Command("help"))
    async def help_cmd(message: Message) -> None:
        if await authorized(message):
            await message.answer("<b>📊 CARTERA</b>\n/portfolio — Valoración y P/L\n/add SYMBOL CANTIDAD [COSTE] — Añadir posición\n/remove SYMBOL — Eliminar posición\n\n<b>🔎 ANÁLISIS</b>\n/analyze SYMBOL — Cotización\n/watchlist [add|remove SYMBOL] — Universo observado\n/opportunities — Oportunidades\n/risk — Calidad de datos\n/macro — Indicadores macro\n\n<b>⚙️ SISTEMA</b>\n/refresh — Actualizar datos\n/status — Estado del bot", parse_mode="HTML")

    @dp.message(Command("portfolio"))
    async def portfolio(message: Message) -> None:
        if not await authorized(message):
            return
        lines, total, coverage = portfolio_snapshot()
        if not lines:
            await message.answer("Cartera vacía. Ejemplo: /add SPY 2 500")
            return
        valued = [line for line in lines if line.market_value is not None]
        parts = ["💼 <b>CARTERA · PANEL DE SEGUIMIENTO</b>", ""]
        for line in lines:
            if line.price is None:
                parts.append(f"<b>{escape(line.symbol)}</b>: {line.quantity:g} unidades · cotización no disponible")
                continue
            value = (f"{line.market_value:,.2f} EUR" if line.market_value is not None
                     else "valor EUR no disponible")
            weight = (f" · peso {line.market_value / total:.1%}"
                      if line.market_value is not None and total > 0 else "")
            pnl = ""
            if line.pnl is not None:
                pnl_pct = (line.price / line.average_cost - 1
                           if line.average_cost is not None and line.average_cost > 0 else None)
                pnl = f" · P/L {line.pnl:+,.2f} EUR" + (f" ({pnl_pct:+.2%})" if pnl_pct is not None else "")
            parts.append(f"<b>{escape(line.symbol)}</b> · {line.quantity:g} × {line.price:,.4f} {escape(line.currency)}\n"
                         f"  Valor: {value}{weight}{pnl}")
        largest = max((line.market_value / total for line in valued), default=0.0) if total > 0 else None
        parts.extend(["", f"💰 <b>Valor conocido:</b> {total:,.2f} EUR",
                      f"📡 <b>Cobertura de cotizaciones:</b> {coverage:.0%} ({len(valued)}/{len(lines)} posiciones)"])
        if largest is not None:
            parts.append(f"🎯 <b>Mayor peso individual:</b> {largest:.1%}")
        fx = db.get_metric("fx_usd_per_eur")
        parts.append(f"💱 USD por EUR: {escape(str(fx.value if fx else 'no disponible'))}")
        parts.append("Valoración indicativa en EUR. P/L convertido al tipo de cambio actual; no incluye efectivo, comisiones ni impuestos. La cobertura incompleta puede distorsionar pesos y concentración.")
        await message.answer("\n".join(parts), parse_mode="HTML")

    @dp.message(Command("add"))
    async def add(message: Message) -> None:
        if not await authorized(message):
            return
        args = (message.text or "").split()
        if len(args) not in (3, 4):
            await message.answer("Uso: /add SYMBOL QUANTITY [COSTE_MEDIO]")
            return
        try:
            symbol, quantity = args[1].upper(), float(args[2])
            cost = float(args[3]) if len(args) == 4 else None
            valid_symbol = symbol.isascii() and symbol.replace(".", "").replace("-", "").isalnum()
            if not valid_symbol or quantity <= 0 or (cost is not None and cost < 0):
                raise ValueError
        except ValueError:
            await message.answer("Símbolo, cantidad o coste no válidos.")
            return
        db.set_holding(symbol, quantity, cost)
        await message.answer(f"Posición registrada: {symbol}, {quantity:g} unidades.")

    @dp.message(Command("remove"))
    async def remove(message: Message) -> None:
        if not await authorized(message):
            return
        args = (message.text or "").split()
        if len(args) != 2:
            await message.answer("Uso: /remove SYMBOL")
            return
        await message.answer("Posición eliminada." if db.delete_holding(args[1]) else "No existe esa posición.")

    @dp.message(Command("analyze"))
    async def analyze(message: Message) -> None:
        if not await authorized(message):
            return
        args = (message.text or "").split()
        if len(args) != 2 or len(args[1]) > 20:
            await message.answer("Uso: /analyze SYMBOL")
            return
        symbol = args[1].upper()
        quote = db.quote_for(symbol)
        if quote is None:
            await message.answer(f"Sin cotización almacenada para {symbol}; actualizando…")
            await services.refresh_quotes()
            quote = db.quote_for(symbol)
        if quote is None:
            await message.answer("No se pudo obtener el precio. Comprueba proveedores y cuotas.")
        else:
            await message.answer(f"{symbol}: {quote.price:,.4f} {quote_currency(symbol, settings.default_currency)}\nFuente: {quote.source}\nObservado: {quote.observed_at.isoformat()}")

    @dp.message(Command("watchlist"))
    async def watchlist(message: Message) -> None:
        if not await authorized(message):
            return
        args = (message.text or "").split()
        if len(args) == 1:
            symbols = db.get_watchlist_symbols()
            await message.answer("👀 <b>WATCHLIST</b>\\n" + (", ".join(symbols) if symbols else "Vacía"),
                                 parse_mode="HTML")
            return
        if len(args) != 3 or args[1].lower() not in {"add", "remove"}:
            await message.answer("Uso: /watchlist [add|remove SYMBOL]")
            return
        symbol = args[2].upper()
        valid_symbol = (len(symbol) <= 24 and symbol.isascii()
                        and symbol.replace(".", "").replace("-", "").isalnum())
        if not valid_symbol:
            await message.answer("Ticker no válido. Usa letras, números, puntos o guiones.")
            return
        if args[1].lower() == "add":
            added = db.add_watchlist_symbol(symbol)
            await message.answer(
                f"✅ {symbol} añadido a la watchlist." if added
                else f"ℹ️ {symbol} ya estaba en la watchlist.")
        else:
            removed = db.remove_watchlist_symbol(symbol)
            await message.answer(
                f"🗑️ {symbol} eliminado de la watchlist." if removed
                else f"ℹ️ {symbol} no estaba añadido; los símbolos configurados por defecto no se pueden eliminar.")

    @dp.message(Command("opportunities"))
    async def opportunities(message: Message) -> None:
        if not await authorized(message):
            return
        from app.opportunities import build_opportunities_report

        await message.answer("🔎 <b>ESCANEANDO OPORTUNIDADES</b> · horizonte 1–3 meses\\nRecopilando cierres diarios y evaluando la cobertura…", parse_mode="HTML")
        try:
            report = await build_opportunities_report(services)
        except Exception:
            logger.exception("Opportunity scan failed")
            await message.answer("No se ha podido completar el análisis. Revisa los logs del servicio.")
            return
        for part in report:
            await message.answer(part, parse_mode="HTML")

    @dp.message(Command("risk"))
    async def risk(message: Message) -> None:
        if not await authorized(message):
            return
        from app.risk import RiskObservation, portfolio_risk_report

        holdings = db.get_holdings()
        if not holdings:
            await message.answer(
                "Diagnóstico de riesgo\n\nNo hay posiciones registradas. "
                "SP500-VRM continúa sin probabilidades calibradas."
            )
            return
        observations = []
        for holding in holdings:
            quote = db.quote_for(holding.symbol)
            observations.append(RiskObservation(
                symbol=holding.symbol,
                price=quote.price if quote else None,
                currency=quote_currency(holding.symbol, settings.default_currency),
                observed_at=quote.observed_at if quote else None,
                source=quote.source if quote else None,
                average_cost=holding.average_cost,
            ))
        history_by_symbol = {}
        for holding in holdings:
            try:
                rows, _ = await services.daily_history(holding.symbol, outputsize=8)
                history_by_symbol[holding.symbol] = rows
            except Exception:
                logger.exception("Could not refresh risk history for %s", holding.symbol)
                history_by_symbol[holding.symbol] = []
        report = portfolio_risk_report(observations)
        labels = {"critical": "CRÍTICO · CALIDAD DE DATOS", "warning": "REVISAR · CALIDAD DE DATOS",
                  "info": "SIN INCIDENCIAS OBSERVABLES"}
        parts = ["🛡️ <b>DIAGNÓSTICO DE RIESGO</b> · CARTERA", ""]
        for item in report:
            parts.append(f"• <b>{escape(item.symbol)}</b>: {labels[item.level]}")
            if item.price_age_hours is not None:
                parts.append(f"  Antigüedad de cotización: {item.price_age_hours:.1f} h")
            if item.pnl_pct is not None:
                parts.append(f"  P/L vs. coste medio registrado: {item.pnl_pct:+.2%}")
            history = history_by_symbol.get(item.symbol, [])
            parts.append(f"  Histórico diario: {len(history)} sesiones disponibles")
            if len(history) >= 8:
                change = history[-1][1] / history[-8][1] - 1
                parts.append(f"  Variación en 7 intervalos: {change:+.2%}")
            else:
                parts.append("  Variación en 7 intervalos: insuficiente histórico")
            for finding in item.findings:
                parts.append(f"  - {escape(finding.label)}: {escape(finding.detail)}")
        parts.extend([
            "",
            "SP500-VRM: probabilidades no calibradas; no se estima una probabilidad de caída.",
            ("Este informe evalúa la disponibilidad de datos y el P/L registrado, no predice pérdidas "
             "ni constituye una señal de compra o venta."),
        ])
        await message.answer("\n".join(parts), parse_mode="HTML")

    @dp.message(Command("macro"))
    async def macro(message: Message) -> None:
        if not await authorized(message):
            return
        parts = ["🌐 <b>INDICADORES MACRO</b>", ""]
        for key in ("fed_funds", "ust10y", "usd_broad"):
            metric, asof = db.get_metric(f"fred_{key}"), db.get_metric(f"fred_{key}_as_of")
            parts.append(f"• <b>{key.replace('_', ' ').upper()}</b> · {escape(str(metric.value if metric else 'sin dato'))} · Observado: {escape(str(asof.value if asof else '—'))}")
        await message.answer("\n".join(parts), parse_mode="HTML")

    @dp.message(Command("refresh"))
    async def refresh(message: Message) -> None:
        if not await authorized(message):
            return
        market, macro = await services.refresh_quotes(), await services.refresh_macro()

        def age_label(raw: str) -> str:
            try:
                observed = datetime.fromisoformat(raw)
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=UTC)
                seconds = max(0, int((datetime.now(UTC) - observed.astimezone(UTC)).total_seconds()))
                if seconds < 3600:
                    age = f"{max(1, seconds // 60)} min"
                elif seconds < 86400:
                    age = f"{seconds // 3600} h {seconds % 3600 // 60} min"
                else:
                    age = f"{seconds // 86400} d {seconds % 86400 // 3600} h"
                return f" · antigüedad: {age} · observado: {observed.strftime('%Y-%m-%d %H:%M UTC')}"
            except (ValueError, TypeError):
                return " · antigüedad: desconocida"

        def summarize(results: dict[str, str], *, macro_data: bool = False) -> tuple[int, list[str]]:
            ok = 0
            lines = []
            for symbol, status in results.items():
                if status == "ok" or status.startswith("ok:"):
                    ok += 1
                    fields = status.split(":", 2)
                    source = fields[1].replace("_", " ").title() if len(fields) > 1 else ""
                    detail = f" ({source})" if source else ""
                    age = age_label(fields[2]) if len(fields) > 2 else ""
                    lines.append(f"🟢 <b>{escape(symbol)}</b> · actualizado{escape(detail)}{escape(age)}")
                    continue
                stale = status.startswith("stale:")
                if stale:
                    fields = status.split(":", 2)
                    age = age_label(fields[2]) if len(fields) > 2 else ""
                    lines.append(f"🟠 <b>{escape(symbol)}</b> · dato anterior conservado{escape(age)}")
                    continue
                reason_code = status.partition(":")[2].lower()
                if "429" in reason_code or "rate_limit" in reason_code or "quota" in reason_code:
                    reason = "límite de consultas del proveedor"
                elif "403" in reason_code or "forbidden" in reason_code or "not_entitled" in reason_code:
                    reason = "el proveedor no permite este acceso"
                elif "404" in reason_code or "not_found" in reason_code or "symbol_unavailable" in reason_code:
                    reason = "símbolo no disponible en el proveedor"
                elif "budget" in reason_code:
                    reason = "presupuesto diario de consultas agotado"
                elif "unauthorized" in reason_code:
                    reason = "credenciales del proveedor no válidas"
                elif "timeout" in reason_code or "network" in reason_code or "server_error" in reason_code:
                    reason = "fallo temporal del proveedor"
                elif "no_eligible_provider" in reason_code or "not_configured" in reason_code:
                    reason = "no hay proveedor habilitado"
                else:
                    reason = "dato no disponible"
                suffix = " · se conserva el último dato" if stale else ""
                lines.append(f"🔴 <b>{escape(symbol)}</b> · {'sin actualizar' if not stale else 'dato anterior conservado'} ({reason}){suffix}")
            return ok, lines

        market_ok, market_lines = summarize(market)
        macro_ok, macro_lines = summarize(macro, macro_data=True)
        market_failed = len(market) - market_ok
        macro_failed = len(macro) - macro_ok
        if market_failed == 0 and macro_failed == 0:
            heading = "Actualización completada correctamente."
        elif market_ok + macro_ok:
            heading = "Actualización completada con incidencias."
        else:
            heading = "No se han podido actualizar los datos."
        parts = [f"<b>{'🟢' if market_failed == 0 and macro_failed == 0 else '🟠' if market_ok + macro_ok else '🔴'} {heading}</b>", "", f"📈 <b>MERCADO</b> · {market_ok}/{len(market)} actualizados"]
        parts.extend(market_lines)
        parts += ["", f"🌐 <b>MACROECONOMÍA</b> · {macro_ok}/{len(macro)} actualizados"]
        parts.extend(macro_lines)
        parts += ["", "La antigüedad se calcula desde la observación del proveedor, no desde la última consulta. Los cierres diarios pueden corresponder al último día hábil.", "Los datos anteriores se conservan cuando no hay una cotización nueva."]
        await message.answer("\n".join(parts), parse_mode="HTML")

    @dp.message(Command("status"))
    async def status(message: Message) -> None:
        if not await authorized(message):
            return
        quote_time, macro_time = db.get_metric("last_quote_refresh"), db.get_metric("last_macro_refresh")
        await message.answer(f"🟢 <b>ESTADO DEL SISTEMA</b>\n\n📈 <b>Mercado</b> · {escape(str(quote_time.value if quote_time else 'pendiente'))}\n🌐 <b>Macro</b> · {escape(str(macro_time.value if macro_time else 'pendiente'))}\n\n<b>Proveedores configurados</b>\nFRED {'🟢' if settings.fred_api_key else '⚪'} · Twelve Data {'🟢' if settings.twelve_data_api_key else '⚪'} · Finnhub {'🟢' if settings.finnhub_api_key else '⚪'}", parse_mode="HTML")

    return bot, dp
