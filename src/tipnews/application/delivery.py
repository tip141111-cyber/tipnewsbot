import logging

from tipnews.ports import DeliveryBlocked, DeliveryRetry, DeliveryUncertain, Sender
from tipnews.ports.storage import Store

logger = logging.getLogger(__name__)


async def deliver_one(store: Store, sender: Sender, now: int) -> bool:
    delivery = await store.claim_delivery(now)
    if delivery is None:
        return False
    try:
        await sender.send(delivery.chat_id, delivery.text)
    except DeliveryBlocked:
        await store.set_active(delivery.chat_id, False)
        await store.finish_delivery(delivery.id, "blocked")
    except DeliveryRetry as exc:
        state = "pending" if delivery.attempts < 5 else "failed"
        await store.finish_delivery(delivery.id, state, now + max(1, exc.delay))
    except DeliveryUncertain:
        await store.finish_delivery(delivery.id, "uncertain")
        logger.warning("delivery_uncertain id=%d", delivery.id)
    except Exception as exc:
        await store.finish_delivery(delivery.id, "failed")
        logger.warning("delivery_failed id=%d error=%s", delivery.id, type(exc).__name__)
    else:
        await store.finish_delivery(delivery.id, "sent")
    return True
