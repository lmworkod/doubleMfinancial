from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.digest import build_daily_digest
from app.services import Services


def start_scheduler(services: Services, bot: Bot) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Europe/Madrid")
    scheduler.add_job(services.refresh_quotes, "interval",
        minutes=max(5, settings.quote_refresh_minutes), id="refresh_quotes",
        coalesce=True, max_instances=1, misfire_grace_time=300)
    scheduler.add_job(services.refresh_macro, "cron",
        hour=min(23, max(0, settings.daily_refresh_hour_utc)), minute=15,
        timezone="UTC", id="refresh_macro", coalesce=True, max_instances=1,
        misfire_grace_time=3600)

    async def send_daily_digest() -> None:
        # Refresh immediately before reporting, then send only to configured owners.
        await services.refresh_quotes()
        await services.refresh_macro()
        digest = build_daily_digest()
        for user_id in sorted(settings.allowed_user_ids):
            await bot.send_message(user_id, digest, parse_mode="HTML")

    scheduler.add_job(send_daily_digest, "cron", day_of_week="mon-fri", hour=23,
        minute=0, timezone="Europe/Madrid", id="daily_portfolio_digest",
        coalesce=True, max_instances=1, misfire_grace_time=1800)
    async def monitor_portfolio() -> None:
        from app.monitor import scan_portfolio_signal_changes

        try:
            alerts = await scan_portfolio_signal_changes(services)
            for alert in alerts:
                for user_id in sorted(settings.allowed_user_ids):
                    await bot.send_message(user_id, alert, parse_mode="HTML")
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Scheduled portfolio monitoring failed")

    scheduler.add_job(monitor_portfolio, "interval", hours=8,
        id="portfolio_signal_monitor", coalesce=True, max_instances=1,
        misfire_grace_time=1800)
    scheduler.start()
    return scheduler
