from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

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


class NewModel(Model):
    async def summarize(self, article: Article) -> str:
        self.calls += 1
        return "Новая версия 12 ускоряет работу хранилища."


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
    second = NewModel()
    assert await Pipeline(store, Reader(), second, [], "v2").prepare(now, refresh=True) == 1
    assert second.calls == 1
    items = await store.digest(now.date().isoformat())
    assert items is not None and items[0].summary.startswith("Новая версия")


async def test_refresh_failure_preserves_valid_old_summary(
    store: SqlStore, article: Article
) -> None:
    await store.add_articles([article])
    now = datetime.now(UTC)
    await Pipeline(store, Reader(), Model(), [], "v1").prepare(now)
    before = await store.digest(now.date().isoformat())
    await Pipeline(store, Reader(), Model(fail=True), [], "v2").prepare(now, refresh=True)
    assert await store.digest(now.date().isoformat()) == before


async def test_partial_edition_resumes_without_repeating_success(
    store: SqlStore, article: Article
) -> None:
    other = replace(article, id="a2", title="Separate storage announcement", topic=Topic.SECURITY)
    await store.add_articles([article, other])

    class Flaky(Model):
        async def summarize(self, candidate: Article) -> str:
            if candidate.id == "a2":
                raise TimeoutError
            return await super().summarize(candidate)

    now = datetime.now(UTC) + timedelta(seconds=1)
    assert await Pipeline(store, Reader(), Flaky(), [], "v1").prepare(now) == 1
    recovered = Model()
    assert await Pipeline(store, Reader(), recovered, [], "v1").prepare(now, resume=True) == 2
    assert recovered.calls == 1


async def test_pipeline_refresh_updates_only_unsent_delivery(
    store: SqlStore, article: Article
) -> None:
    await store.add_articles([article])
    await store.subscribe(42, {Topic.IT})
    await store.subscribe(43, {Topic.IT})
    now = datetime.now(UTC)
    await Pipeline(store, Reader(), Model(), [], "v1").prepare(now)
    sent = await store.claim_delivery(int(now.timestamp()))
    assert sent is not None
    await store.finish_delivery(sent.id, "sent")
    await Pipeline(store, Reader(), NewModel(), [], "v2").prepare(now, refresh=True)
    pending = await store.claim_delivery(int(now.timestamp()))
    assert pending is not None and pending.chat_id != sent.chat_id
    assert "Новая версия" in pending.text
    assert await store.claim_delivery(int(now.timestamp())) is None


async def test_rebuild_removes_old_items_and_bypasses_matching_cache(
    store: SqlStore, article: Article
) -> None:
    now = datetime.now(UTC)
    old = DigestItem(
        "old", Topic.IT, "Old", "Старый пересказ от предыдущей модели.", article.url, "Test"
    )
    await store.subscribe(42, {Topic.IT})
    await store.subscribe(43, {Topic.IT})
    await store.publish(now.date().isoformat(), [old], 0)
    sent = await store.claim_delivery(int(now.timestamp()))
    assert sent is not None
    await store.finish_delivery(sent.id, "sent")
    await store.add_articles([article])
    model = NewModel()
    pipeline = Pipeline(store, Reader(), model, [], "gemini")
    await store.save_summary(article.id, "Старый кэш с совпадающей версией.", pipeline.version)
    assert await pipeline.prepare(now, rebuild=True) == 1
    assert model.calls == 1
    edition = await store.digest(now.date().isoformat())
    assert edition is not None and [item.article_id for item in edition] == [article.id]
    assert edition[0].summary.startswith("Новая версия")
    pending = await store.claim_delivery(int(now.timestamp()))
    assert pending is not None and pending.chat_id != sent.chat_id
    assert "Новая версия" in pending.text and "Старый" not in pending.text
    assert await store.claim_delivery(int(now.timestamp())) is None


async def test_rebuild_failure_never_publishes_partial_or_weekly_fallback(
    store: SqlStore, article: Article
) -> None:
    now = datetime.now(UTC)
    old = DigestItem(
        "old", Topic.IT, "Old", "Старый пересказ от предыдущей модели.", article.url, "Test"
    )
    await store.subscribe(42, {Topic.IT})
    await store.publish(now.date().isoformat(), [old], 0)
    other = replace(
        article,
        id="weekly",
        source_id="weekly",
        topic=Topic.WORLD,
        title="Weekly programme with separate subject",
    )
    await store.add_articles([article, other])
    weekly = Source(
        "weekly", "Weekly", "https://example.org", Topic.WORLD, ("example.org",), latest_only=True
    )

    class PartialModel(NewModel):
        async def summarize(self, candidate: Article) -> str:
            if candidate.id == "weekly":
                raise TimeoutError
            return await super().summarize(candidate)

    with pytest.raises(RuntimeError, match="previous edition retained"):
        await Pipeline(store, Reader(), PartialModel(), [weekly], "gemini").prepare(
            now, rebuild=True
        )
    assert await store.digest(now.date().isoformat()) == [old]
    pending = await store.claim_delivery(int(now.timestamp()))
    assert pending is not None and "Старый пересказ" in pending.text


async def test_rebuild_cannot_create_new_delivery_or_erase_empty_selection(store: SqlStore) -> None:
    now = datetime.now(UTC)
    pipeline = Pipeline(store, Reader(), Model(), [], "gemini")
    with pytest.raises(ValueError, match="existing edition"):
        await pipeline.prepare(now, rebuild=True)
    old = DigestItem(
        "old",
        Topic.IT,
        "Old",
        "Старый пересказ от предыдущей модели.",
        "https://example.org",
        "Test",
    )
    await store.publish(now.date().isoformat(), [old], 0)
    with pytest.raises(ValueError, match="No articles"):
        await pipeline.prepare(now, rebuild=True)
    assert await store.digest(now.date().isoformat()) == [old]
