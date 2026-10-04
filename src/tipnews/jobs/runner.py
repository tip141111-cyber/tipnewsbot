import asyncio
import logging
from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

from tipnews.application.delivery import deliver_one
from tipnews.application.pipeline import Pipeline
from tipnews.config import Settings
from tipnews.ports import Sender
from tipnews.ports.storage import Store

logger = logging.getLogger(__name__)


def local_at(day: date, value: time, timezone: tzinfo | None) -> datetime:
    return datetime.combine(day, value, timezone)


def next_delivery(now: datetime, settings: Settings) -> datetime:
    delivery = local_at(now.date(), settings.digest_time, now.tzinfo)
    return delivery if now <= delivery else delivery + timedelta(days=1)


async def generation_loop(settings: Settings, store: Store, pipeline: Pipeline) -> None:
    first_cycle = True
    while True:
        now = datetime.now(ZoneInfo(settings.timezone))
        stamp = int(now.timestamp())
        try:
            if await store.job_due("collect", stamp, settings.collect_interval_seconds):
                await pipeline.collect()

            if first_cycle:
                await pipeline.prepare(now, deliver_at=next_delivery(now, settings))
                first_cycle = False

            midnight = local_at(now.date(), time.min, now.tzinfo)
            if midnight <= now < midnight + timedelta(hours=1):
                if await store.job_due("prepare", stamp, 900):
                    await pipeline.prepare(
                        midnight,
                        deliver_at=local_at(now.date(), settings.digest_time, now.tzinfo),
                    )

            weather_time = local_at(now.date(), settings.weather_refresh_time, now.tzinfo)
            if now >= weather_time:
                if await store.job_due("weather", stamp, 86400):
                    await pipeline.refresh_weather(now.date())
            if await store.job_due("cleanup", stamp, 86400):
                cutoff = now - timedelta(days=settings.retention_days)
                await store.cleanup(int(cutoff.timestamp()), cutoff.date().isoformat())
        except Exception as exc:
            logger.error("generation_cycle_failed error=%s", type(exc).__name__)
        await asyncio.sleep(30)


async def delivery_loop(settings: Settings, store: Store, sender: Sender) -> None:
    last_day = ""
    while True:
        now = datetime.now(ZoneInfo(settings.timezone))
        try:
            if last_day != now.date().isoformat():
                await store.recover_deliveries(now.date().isoformat())
                last_day = now.date().isoformat()
            delivered = await deliver_one(store, sender, int(now.timestamp()))
            settings.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
            settings.heartbeat_file.touch()
        except Exception as exc:
            logger.error("delivery_cycle_failed error=%s", type(exc).__name__)
            delivered = False
        await asyncio.sleep(0.1 if delivered else 2)
