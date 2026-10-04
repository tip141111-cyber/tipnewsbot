from datetime import UTC, date, datetime

from tipnews.adapters.persistence.repository import SqlStore
from tipnews.application.pipeline import Pipeline
from tipnews.domain.models import Article, DigestItem, Source, Topic


class Reader:
    async def fetch(self, source: Source) -> list[Article]:
        return []


class Model:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    async def summarize(self, article: Article) -> str:
        self.calls += 1
        if self.fail:
            raise TimeoutError
        return "Вышла версия 12 с улучшениями хранилища."


class Weather:
    async def today(self, day: date) -> DigestItem:
        return DigestItem(
            "weather",
            Topic.WEATHER,
            "Weather",
            "Сегодня в Рязани ясно и тепло.",
            "https://open-meteo.com/",
            "Open-Meteo",
        )


async def test_pipeline_caches_and_does_not_republish(store: SqlStore, article: Article) -> None:
    assert await store.add_articles([article, article]) == 1
    assert await store.add_articles([article]) == 0
    model = Model()
    pipeline = Pipeline(store, Reader(), model, [], "v1")
    scheduled = datetime.now(UTC)
    assert await pipeline.prepare(scheduled) == 1
    assert await pipeline.prepare(scheduled) == 1
    assert model.calls == 1


async def test_model_failure_does_not_publish_fake_digest(
    store: SqlStore, article: Article
) -> None:
    await store.add_articles([article])
    now = datetime.now(UTC)
    pipeline = Pipeline(store, Reader(), Model(fail=True), [], "v1", Weather())
    assert await pipeline.prepare(now) == 0
    assert await store.digest(now.date().isoformat()) is None


async def test_refresh_reuses_todays_articles_and_invalidates_old_summary_version(
    store: SqlStore,
    article: Article,
) -> None:
    await store.add_articles([article])
    now = datetime.now(UTC)
    first = Model()
    await Pipeline(store, Reader(), first, [], "v1").prepare(now)
    second = Model()
    assert await Pipeline(store, Reader(), second, [], "v2").prepare(now, refresh=True) == 1
    assert second.calls == 1
