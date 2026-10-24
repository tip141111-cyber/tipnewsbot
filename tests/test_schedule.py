from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from tipnews.adapters.persistence.repository import SqlStore
from tipnews.application.pipeline import Pipeline
from tipnews.config import Settings
from tipnews.jobs.runner import generation_cycle, next_delivery


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=ZoneInfo("Europe/Moscow"))


async def test_late_start_delivers_today_and_uses_previous_calendar_day(store: SqlStore) -> None:
    pipeline = AsyncMock(spec=Pipeline)
    now = at(24, 12)
    config = Settings()
    await generation_cycle(config, store, pipeline, now, first_cycle=True)
    pipeline.prepare.assert_awaited_once_with(at(24, 0), deliver_at=now, resume=False)
    assert next_delivery(at(24, 6), config) == at(24, 7, 15)
    assert next_delivery(now, config) == now


async def test_retries_partial_edition_before_delivery_only(store: SqlStore) -> None:
    pipeline = AsyncMock(spec=Pipeline)
    config = Settings()
    await generation_cycle(config, store, pipeline, at(24, 1))
    pipeline.prepare.assert_awaited_with(at(24, 0), deliver_at=at(24, 7, 15), resume=True)
    await generation_cycle(config, store, pipeline, at(24, 1) + timedelta(seconds=30))
    assert pipeline.prepare.await_count == 1
    await generation_cycle(config, store, pipeline, at(24, 7, 30))
    pipeline.prepare.assert_awaited_with(at(24, 0), deliver_at=at(24, 7, 30), resume=False)


async def test_weather_uses_calendar_day_after_late_start(store: SqlStore) -> None:
    pipeline = AsyncMock(spec=Pipeline)
    await store.publish("2026-10-23", [], 0)
    await store.publish("2026-10-24", [], 0)
    await generation_cycle(Settings(), store, pipeline, at(23, 12))
    await generation_cycle(Settings(), store, pipeline, at(24, 7, 10))
    assert pipeline.refresh_weather.await_count == 2
    await generation_cycle(Settings(), store, pipeline, at(24, 7, 11))
    assert pipeline.refresh_weather.await_count == 2
