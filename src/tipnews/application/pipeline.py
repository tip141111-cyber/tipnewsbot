import asyncio
import hashlib
import logging
from dataclasses import replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tipnews.domain.models import DigestItem, Source, Topic
from tipnews.domain.selection import select_articles
from tipnews.ports import NewsReader, Summarizer, WeatherProvider
from tipnews.ports.storage import Store

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        store: Store,
        reader: NewsReader,
        summarizer: Summarizer,
        sources: list[Source],
        model_version: str,
        weather: WeatherProvider | None = None,
    ) -> None:
        self.store = store
        self.reader = reader
        self.summarizer = summarizer
        self.sources = sources
        self.version = hashlib.sha256(model_version.encode()).hexdigest()
        self.weather = weather

    async def with_weather(self, items: list[DigestItem], day: date) -> list[DigestItem]:
        result = [item for item in items if item.topic != Topic.WEATHER]
        if self.weather:
            forecast = await self.weather.today(day)
            if forecast:
                result.insert(0, forecast)
        return result

    async def collect(self) -> int:
        total = 0
        for source in self.sources:
            try:
                async with asyncio.timeout(45):
                    articles = await self.reader.fetch(source)
                total += await self.store.add_articles(articles)
                logger.info("source=%s entries=%d", source.id, len(articles))
            except Exception as exc:
                logger.warning("source_failed source=%s error=%s", source.id, type(exc).__name__)
        return total

    async def prepare(
        self,
        scheduled_at: datetime,
        *,
        deliver_at: datetime | None = None,
        refresh: bool = False,
        resume: bool = False,
        rebuild: bool = False,
    ) -> int:
        day = scheduled_at.date().isoformat()
        existing = await self.store.digest(day)
        if rebuild and existing is None:
            raise ValueError("Full rebuild requires an existing edition; no delivery is created")
        if existing is not None and not (refresh or resume or rebuild):
            return len(existing)
        reuse_day = day if existing is not None else None
        previous = {item.article_id: item for item in existing or [] if item.topic != Topic.WEATHER}
        weekly = {source.id: source for source in self.sources if source.latest_only}
        candidates = await self.store.candidates(
            scheduled_at - timedelta(hours=24),
            reuse_day=reuse_day,
            until=scheduled_at,
        )
        candidates = [article for article in candidates if article.source_id not in weekly]
        for source in weekly.values():
            latest = await self.store.candidates(
                scheduled_at - timedelta(hours=source.lookback_hours),
                reuse_day=reuse_day,
                until=scheduled_at,
                source_id=source.id,
                latest_only=True,
            )
            candidates.extend(replace(article, priority=source.priority) for article in latest)
        articles = select_articles(candidates)
        if rebuild and not articles:
            raise ValueError("No articles available for rebuild; previous edition retained")
        items = []
        for article in articles:
            summary = None if rebuild else await self.store.cached_summary(article.id, self.version)
            if summary is None:
                try:
                    summary_article = article
                    if article.source_id in weekly:
                        summary_article = replace(article, text=article.text[:1800])
                    async with asyncio.timeout(360):
                        summary = await self.summarizer.summarize(summary_article)
                    await self.store.save_summary(article.id, summary, self.version)
                except Exception as exc:
                    logger.warning(
                        "summary_failed article=%s error=%s", article.id, type(exc).__name__
                    )
                    if rebuild:
                        logger.error(
                            "digest_rebuild_aborted day=%s previous_edition_retained=true", day
                        )
                        raise RuntimeError(
                            "Full rebuild failed; previous edition retained"
                        ) from None
                    if article.id in previous:
                        items.append(previous[article.id])
                        continue
                    if article.source_id in weekly:
                        summary = (
                            f"Анонс выпуска: {article.title}. Подробности — по ссылке на источник."
                        )
                    else:
                        continue
            if article.source_id in weekly:
                published = article.published_at.astimezone(ZoneInfo("Europe/Moscow"))
                summary = f"Выпуск от {published:%d.%m.%Y}. {summary}"
            items.append(
                DigestItem(
                    article.id,
                    article.topic,
                    article.title,
                    summary,
                    article.url,
                    article.source_name,
                )
            )
        if existing is not None and not rebuild:
            # Replace matching articles; never discard a valid old summary on model failure.
            previous.update({item.article_id: item for item in items})
            items = list(previous.values())[:10]
        if items:
            items = await self.with_weather(items, scheduled_at.date())
            if existing is not None and items != existing:
                await self.store.refresh_digest(day, items)
            elif existing is None:
                delivery_time = deliver_at or scheduled_at
                await self.store.publish(day, items, int(delivery_time.timestamp()))
            logger.info("digest_published day=%s items=%d", day, len(items))
        else:
            logger.warning("digest_not_ready day=%s candidates=%d", day, len(articles))
        return len(items)

    async def refresh_weather(self, day: date) -> bool:
        existing = await self.store.digest(day.isoformat())
        if existing is None or self.weather is None:
            return False
        news = [item for item in existing if item.topic != Topic.WEATHER]
        items = await self.with_weather(news, day)
        await self.store.refresh_digest(day.isoformat(), items)
        logger.info("weather_refreshed day=%s", day.isoformat())
        return True
