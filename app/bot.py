import logging

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
            await message.answer("DoubleM Financial listo. Usa /help para ver los comandos.")

    @dp.message(Command("help"))
    async def help_cmd(message: Message) -> None:
        if await authorized(message):
            await message.answer("/portfolio · /add SYMBOL QUANTITY [COSTE] · /remove SYMBOL\n/analyze SYMBOL · /watchlist · /opportunities\n/risk · /macro · /refresh · /status")

    @dp.message(Command("portfolio"))
    async def portfolio(message: Message) -> None:
        if not await authorized(message):
            return
        lines, total, coverage = portfolio_snapshot()
        if not lines:
            await message.answer("Cartera vacía. Ejemplo: /add SPY 2 500")
            return
        parts = ["Cartera (valoración indicativa)"]
        for line in lines:
            if line.price is None:
                parts.append(f"{line.symbol}: {line.quantity:g} unidades · sin cotización")
            else:
                value = f" = {line.market_value:,.2f} EUR" if line.market_value is not None else " · valor EUR no disponible"
                pnl = f" · P/L {line.pnl:,.2f} EUR" if line.pnl is not None else ""
                parts.append(f"{line.symbol}: {line.quantity:g} × {line.price:,.4f} {line.currency}{value}{pnl}")
        parts += [f"Valor conocido: {total:,.2f} EUR",
                  f"Cobertura de cotizaciones: {coverage:.0%}",
                  f"FX ECB USD/EUR: {db.get_metric('fx_usd_per_eur').value if db.get_metric('fx_usd_per_eur') else 'no disponible'} (USD por EUR).",
                  "Valoración en EUR; P/L convertido al tipo actual, no al tipo histórico de compra. No incluye efectivo ni comisiones."]
        await message.answer("\n".join(parts))

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
        if await authorized(message):
            await message.answer("Lista observada: " + ", ".join(settings.symbols))

    @dp.message(Command("opportunities"))
    async def opportunities(message: Message) -> None:
        if await authorized(message):
            await message.answer("La detección de oportunidades requiere definir universo y criterios. Esta versión no genera recomendaciones ni señales de compraventa.")

    @dp.message(Command("risk"))
    async def risk(message: Message) -> None:
        if await authorized(message):
            await message.answer("SP500-VRM: probabilidad no calibrada. No hay aún un modelo entrenado y validado walk-forward. No se muestran probabilidades ficticias ni se modifica la exposición automáticamente.")

    @dp.message(Command("macro"))
    async def macro(message: Message) -> None:
        if not await authorized(message):
            return
        parts = ["Variables macro almacenadas"]
        for key in ("fed_funds", "ust10y", "usd_broad"):
            metric, asof = db.get_metric(f"fred_{key}"), db.get_metric(f"fred_{key}_as_of")
            parts.append(f"{key}: {metric.value if metric else 'sin dato'} (fecha: {asof.value if asof else '—'})")
        await message.answer("\n".join(parts))

    @dp.message(Command("refresh"))
    async def refresh(message: Message) -> None:
        if not await authorized(message):
            return
        market, macro = await services.refresh_quotes(), await services.refresh_macro()
        await message.answer(f"Actualización terminada.\nMercado: {market}\nMacro: {macro}")

    @dp.message(Command("status"))
    async def status(message: Message) -> None:
        if not await authorized(message):
            return
        quote_time, macro_time = db.get_metric("last_quote_refresh"), db.get_metric("last_macro_refresh")
        await message.answer(f"Bot y base de datos activos.\nMercado: {quote_time.value if quote_time else 'pendiente'}\nMacro: {macro_time.value if macro_time else 'pendiente'}\nClaves: FRED={'sí' if settings.fred_api_key else 'no'}, Twelve Data={'sí' if settings.twelve_data_api_key else 'no'}, Finnhub={'sí' if settings.finnhub_api_key else 'no'}")

    return bot, dp
