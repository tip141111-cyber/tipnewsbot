from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Topic(StrEnum):
    IT = "it"
    SECURITY = "security"
    ECONOMY = "economy"
    WORLD = "world"
    RYAZAN = "ryazan"
    MARKETS = "markets"
    WEATHER = "weather"


TOPIC_NAMES = {
    Topic.IT: "IT / DevOps",
    Topic.SECURITY: "Безопасность",
    Topic.ECONOMY: "Экономика",
    Topic.WORLD: "Политика",
    Topic.RYAZAN: "Рязань",
    Topic.MARKETS: "Рынки",
    Topic.WEATHER: "Погода · Рязань",
}


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    topic: Topic
    hosts: tuple[str, ...]
    priority: int = 0
    kind: str = "rss"
    lookback_hours: int = 24
    latest_only: bool = False


@dataclass(frozen=True)
class Article:
    id: str
    source_id: str
    source_name: str
    topic: Topic
    title: str
    url: str
    text: str
    published_at: datetime
    priority: int = 0


@dataclass(frozen=True)
class DigestItem:
    article_id: str
    topic: Topic
    title: str
    summary: str
    url: str
    source_name: str


@dataclass(frozen=True)
class Delivery:
    id: int
    chat_id: int
    text: str
    attempts: int
