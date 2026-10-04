from datetime import date
from typing import Protocol

from tipnews.domain.models import Article, DigestItem, Source


class WeatherProvider(Protocol):
    async def today(self, day: date) -> DigestItem | None: ...


class NewsReader(Protocol):
    async def fetch(self, source: Source) -> list[Article]: ...


class Summarizer(Protocol):
    async def summarize(self, article: Article) -> str: ...


class Sender(Protocol):
    async def send(self, chat_id: int, text: str) -> None: ...


class DeliveryBlocked(Exception):
    """The recipient blocked the bot or removed the chat."""


class DeliveryRetry(Exception):
    def __init__(self, delay: int = 60) -> None:
        self.delay = delay


class DeliveryUncertain(Exception):
    """The server may have accepted the message; do not blindly retry."""
