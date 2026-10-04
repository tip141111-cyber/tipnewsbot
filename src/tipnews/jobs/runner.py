import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from tipnews.application.delivery import deliver_one
from tipnews.application.pipeline import Pipeline
from tipnews.config import Settings
from tipnews.ports import Sender
from tipnews.ports.storage import Store

logger = logging.getLogger(__name__)


async def generation_loop(settings: Settings, store: Store, pipeline: Pipeline) -> None:
    while True:
        now = datetime.now(ZoneInfo(settings.timezone))
        stamp = int(now.timestamp())
        try:
            if await store.job_due("collect", stamp, settings.collect_interval_seconds):
                await pipeline.collect()
            scheduled = datetime.combine(now.date(), settings.digest_time, now.tzinfo)
            if scheduled - timedelta(minutes=30) <= now <= scheduled + timedelta(hours=4):
                if await store.job_due("prepare", stamp, 900):
                    await pipeline.prepare(scheduled)
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
