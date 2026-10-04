from tipnews.adapters.persistence.repository import SqlStore
from tipnews.application.delivery import deliver_one
from tipnews.domain.models import DigestItem, Topic
from tipnews.ports import DeliveryRetry, DeliveryUncertain

ITEM = DigestItem(
    "a", Topic.IT, "Title", "Полезная короткая сводка новостей.", "https://example.org/a", "Source"
)


class FakeSender:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[int] = []

    async def send(self, chat_id: int, text: str) -> None:
        if self.error:
            raise self.error
        self.sent.append(chat_id)


async def test_publish_and_delivery_are_idempotent(store: SqlStore) -> None:
    await store.subscribe(42, {Topic.IT})
    await store.publish("2026-10-04", [ITEM], 100)
    await store.publish("2026-10-04", [ITEM], 100)
    sender = FakeSender()
    assert not await deliver_one(store, sender, 99)
    assert await deliver_one(store, sender, 100)
    assert not await deliver_one(store, sender, 101)
    assert sender.sent == [42]


async def test_restart_does_not_blindly_resend(store: SqlStore) -> None:
    await store.subscribe(42, {Topic.IT})
    await store.publish("2026-10-04", [ITEM], 0)
    assert await store.claim_delivery(1)
    await store.recover_deliveries("2026-10-04")
    assert await store.claim_delivery(2) is None


async def test_pause_cancels_queued_delivery(store: SqlStore) -> None:
    await store.subscribe(42, {Topic.IT})
    await store.publish("2026-10-04", [ITEM], 0)
    await store.set_active(42, False)
    assert await store.claim_delivery(1) is None


async def test_retry_after_and_uncertain_outcome(store: SqlStore) -> None:
    await store.subscribe(42, {Topic.IT})
    await store.publish("2026-10-04", [ITEM], 0)
    await deliver_one(store, FakeSender(DeliveryRetry(120)), 100)
    assert await store.claim_delivery(219) is None
    await deliver_one(store, FakeSender(DeliveryUncertain()), 220)
    assert await store.claim_delivery(999) is None


async def test_topic_change_removes_pending_content(store: SqlStore) -> None:
    await store.subscribe(42, {Topic.IT})
    await store.publish("2026-10-04", [ITEM], 0)
    await store.toggle_topic(42, Topic.IT)
    assert await store.claim_delivery(1) is None


async def test_yesterdays_unsent_digest_expires(store: SqlStore) -> None:
    await store.subscribe(42, {Topic.IT})
    await store.publish("2026-10-03", [ITEM], 0)
    await store.recover_deliveries("2026-10-04")
    assert await store.claim_delivery(1) is None


async def test_refresh_updates_pending_but_never_resends_sent(store: SqlStore) -> None:
    await store.subscribe(42, {Topic.IT})
    await store.subscribe(43, {Topic.IT})
    await store.publish("2026-10-04", [ITEM], 0)
    sender = FakeSender()
    await deliver_one(store, sender, 1)
    changed = DigestItem(
        "a", Topic.IT, "Title", "Обновлённая сводка только на русском.", ITEM.url, ITEM.source_name
    )
    await store.refresh_digest("2026-10-04", [changed])
    remaining = await store.claim_delivery(2)
    assert remaining is not None and "Обновлённая" in remaining.text
    assert remaining.chat_id != sender.sent[0]
    assert await store.claim_delivery(3) is None
