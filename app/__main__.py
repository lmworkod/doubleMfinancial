import asyncio
import logging

from app.bot import build_bot
from app.config import settings
from app.db import init_db
from app.runtime import start_health_thread
from app.scheduler import start_scheduler
from app.services import Services


async def main() -> None:
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await init_db()
    start_health_thread()
    services = Services()
    bot, dispatcher = build_bot(services)
    scheduler = start_scheduler(services, bot)
    try:
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        scheduler.shutdown(wait=False)
        await market_close()


async def market_close() -> None:
    from app.providers import market_data
    await market_data.close()


if __name__ == "__main__":
    asyncio.run(main())
