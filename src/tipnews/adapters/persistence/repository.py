import asyncio
import json
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from tipnews.adapters.persistence.models import (
    ArticleRow,
    DeliveryRow,
    DigestRow,
    JobRow,
    SubscriberRow,
)
from tipnews.application.rendering import render_digest
from tipnews.domain.models import Article, Delivery, DigestItem, Topic


def decode_items(raw: str) -> list[DigestItem]:
    return [DigestItem(**{**item, "topic": Topic(item["topic"])}) for item in json.loads(raw)]


class SqlStore:
    """Single-instance SQLite store. Every method owns its session/transaction."""

    def __init__(self, engine: AsyncEngine) -> None:
        self.sessions = async_sessionmaker(engine, expire_on_commit=False)
        self.write_lock = asyncio.Lock()

    async def add_articles(self, articles: list[Article]) -> int:
        unique = {article.id: article for article in articles}
        async with self.write_lock, self.sessions.begin() as session:
            existing = set(
                await session.scalars(
                    select(ArticleRow.id).where(
                        ArticleRow.id.in_(unique),
                    )
                )
            )
            for key, article in unique.items():
                if key not in existing:
                    session.add(
                        ArticleRow(
                            **{
                                **asdict(article),
                                "published_at": int(article.published_at.timestamp()),
                            }
                        )
                    )
            return len(unique) - len(existing)

    async def candidates(
        self,
        since: datetime,
        reuse_day: str | None = None,
        *,
        until: datetime | None = None,
        source_id: str | None = None,
        latest_only: bool = False,
    ) -> list[Article]:
        async with self.sessions() as session:
            query = select(DigestRow.items)
            if reuse_day is not None:
                query = query.where(DigestRow.day != reuse_day)
            previous = await session.scalars(query)
            used = {item.article_id for raw in previous for item in decode_items(raw)}
            article_query = (
                select(ArticleRow)
                .where(
                    ArticleRow.published_at >= int(since.timestamp()),
                )
                .order_by(ArticleRow.published_at.desc())
                .limit(1 if latest_only else 500)
            )
            if until is not None:
                article_query = article_query.where(
                    ArticleRow.published_at <= int(until.timestamp())
                )
            if source_id is not None:
                article_query = article_query.where(ArticleRow.source_id == source_id)
            rows = await session.scalars(article_query)
            return [
                Article(
                    id=r.id,
                    source_id=r.source_id,
                    source_name=r.source_name,
                    topic=Topic(r.topic),
                    title=r.title,
                    url=r.url,
                    text=r.text,
                    priority=r.priority,
                    published_at=datetime.fromtimestamp(r.published_at, UTC),
                )
                for r in rows
                if r.id not in used
            ]

    async def cached_summary(self, article_id: str, version: str) -> str | None:
        async with self.sessions() as session:
            return await session.scalar(
                select(ArticleRow.summary).where(
                    ArticleRow.id == article_id,
                    ArticleRow.summary_version == version,
                )
            )

    async def save_summary(self, article_id: str, summary: str, version: str) -> None:
        async with self.write_lock, self.sessions.begin() as session:
            await session.execute(
                update(ArticleRow)
                .where(ArticleRow.id == article_id)
                .values(
                    summary=summary,
                    summary_version=version,
                )
            )

    async def digest(self, day: str) -> list[DigestItem] | None:
        async with self.sessions() as session:
            row = await session.get(DigestRow, day)
            return decode_items(row.items) if row else None

    async def publish(self, day: str, items: list[DigestItem], deliver_at: int) -> None:
        async with self.write_lock, self.sessions.begin() as session:
            if await session.get(DigestRow, day):
                return
            session.add(DigestRow(day=day, items=json.dumps([asdict(i) for i in items])))
            await session.flush()
            subscribers = await session.scalars(
                select(SubscriberRow).where(
                    SubscriberRow.active.is_(True),
                )
            )
            for subscriber in subscribers:
                topics = {Topic(t) for t in json.loads(subscriber.topics)}
                text = render_digest(day, items, topics)
                if text:
                    session.add(
                        DeliveryRow(
                            day=day, chat_id=subscriber.chat_id, text=text, next_attempt=deliver_at
                        )
                    )

    async def subscribe(self, chat_id: int, topics: set[Topic]) -> None:
        async with self.write_lock, self.sessions.begin() as session:
            row = await session.get(SubscriberRow, chat_id)
            if row:
                row.active = True
            else:
                session.add(SubscriberRow(chat_id=chat_id, topics=json.dumps(sorted(topics))))

    async def refresh_digest(self, day: str, items: list[DigestItem]) -> None:
        """Update the cached edition and pending messages, never resend an old delivery."""
        async with self.write_lock, self.sessions.begin() as session:
            edition = await session.get(DigestRow, day)
            if edition is None:
                raise ValueError("Digest does not exist")
            edition.items = json.dumps([asdict(item) for item in items])
            pending = await session.scalars(
                select(DeliveryRow).where(
                    DeliveryRow.day == day,
                    DeliveryRow.state == "pending",
                )
            )
            for delivery in pending:
                subscriber = await session.get(SubscriberRow, delivery.chat_id)
                topics = {Topic(t) for t in json.loads(subscriber.topics)} if subscriber else set()
                text = render_digest(day, items, topics)
                if text and subscriber and subscriber.active:
                    delivery.text = text
                else:
                    delivery.state = "cancelled"

    async def preferences(self, chat_id: int) -> set[Topic]:
        async with self.sessions() as session:
            row = await session.get(SubscriberRow, chat_id)
            return {Topic(t) for t in json.loads(row.topics)} if row else set()

    async def subscriber_stats(self) -> tuple[int, int, dict[Topic, int]]:
        async with self.sessions() as session:
            rows = list(await session.scalars(select(SubscriberRow)))
        topics: dict[Topic, int] = {}
        for row in rows:
            for value in json.loads(row.topics):
                topic = Topic(value)
                topics[topic] = topics.get(topic, 0) + (1 if row.active else 0)
        return len(rows), sum(1 for row in rows if row.active), topics

    async def set_active(self, chat_id: int, active: bool) -> None:
        async with self.write_lock, self.sessions.begin() as session:
            await session.execute(
                update(SubscriberRow)
                .where(
                    SubscriberRow.chat_id == chat_id,
                )
                .values(active=active)
            )
            if not active:
                await session.execute(
                    update(DeliveryRow)
                    .where(
                        DeliveryRow.chat_id == chat_id,
                        DeliveryRow.state == "pending",
                    )
                    .values(state="cancelled")
                )

    async def toggle_topic(self, chat_id: int, topic: Topic) -> None:
        async with self.write_lock, self.sessions.begin() as session:
            row = await session.get(SubscriberRow, chat_id)
            if row:
                topics = set(json.loads(row.topics))
                topics.symmetric_difference_update({topic.value})
                row.topics = json.dumps(sorted(topics))
                # A preference change applies to not-yet-sent queued messages too.
                pending = await session.scalars(
                    select(DeliveryRow).where(
                        DeliveryRow.chat_id == chat_id,
                        DeliveryRow.state == "pending",
                    )
                )
                for delivery in pending:
                    digest = await session.get(DigestRow, delivery.day)
                    if digest:
                        text = render_digest(
                            delivery.day, decode_items(digest.items), {Topic(t) for t in topics}
                        )
                        if text:
                            delivery.text = text
                        else:
                            delivery.state = "cancelled"

    async def claim_delivery(self, now: int) -> Delivery | None:
        async with self.write_lock, self.sessions.begin() as session:
            row = await session.scalar(
                select(DeliveryRow)
                .join(SubscriberRow)
                .where(
                    DeliveryRow.state == "pending",
                    DeliveryRow.next_attempt <= now,
                    SubscriberRow.active.is_(True),
                )
                .order_by(DeliveryRow.id)
                .limit(1)
            )
            if not row:
                return None
            row.state = "sending"
            row.attempts += 1
            return Delivery(row.id, row.chat_id, row.text, row.attempts)

    async def finish_delivery(self, delivery_id: int, state: str, next_attempt: int = 0) -> None:
        async with self.write_lock, self.sessions.begin() as session:
            await session.execute(
                update(DeliveryRow)
                .where(DeliveryRow.id == delivery_id)
                .values(
                    state=state,
                    next_attempt=next_attempt,
                )
            )

    async def recover_deliveries(self, today: str) -> None:
        async with self.write_lock, self.sessions.begin() as session:
            await session.execute(
                update(DeliveryRow)
                .where(
                    DeliveryRow.state == "sending",
                )
                .values(state="uncertain")
            )
            await session.execute(
                update(DeliveryRow)
                .where(
                    DeliveryRow.state == "pending",
                    DeliveryRow.day < today,
                )
                .values(state="expired")
            )

    async def job_due(self, name: str, now: int, interval: int) -> bool:
        async with self.write_lock, self.sessions.begin() as session:
            row = await session.get(JobRow, name)
            if row and now - row.last_attempt < interval:
                return False
            if row:
                row.last_attempt = now
            else:
                session.add(JobRow(name=name, last_attempt=now))
            return True

    async def cleanup(self, before: int, before_day: str) -> None:
        async with self.write_lock, self.sessions.begin() as session:
            await session.execute(delete(DeliveryRow).where(DeliveryRow.day < before_day))
            await session.execute(delete(DigestRow).where(DigestRow.day < before_day))
            await session.execute(delete(ArticleRow).where(ArticleRow.published_at < before))
