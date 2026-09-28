from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings
from app.services import Services


def start_scheduler(services: Services) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(services.refresh_quotes, "interval",
        minutes=max(5, settings.quote_refresh_minutes), id="refresh_quotes",
        coalesce=True, max_instances=1, misfire_grace_time=300)
    scheduler.add_job(services.refresh_macro, "cron",
        hour=min(23, max(0, settings.daily_refresh_hour_utc)), minute=15,
        id="refresh_macro", coalesce=True, max_instances=1, misfire_grace_time=3600)
    scheduler.start()
    return scheduler
