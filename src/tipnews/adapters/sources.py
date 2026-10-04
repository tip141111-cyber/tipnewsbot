import calendar
import hashlib
import re
import tomllib
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from tipnews.adapters.telegram_feed import parse_telegram
from tipnews.domain.models import Article, Source, Topic


class PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def plain_text(value: str) -> str:
    parser = PlainText()
    parser.feed(value)
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username:
        raise ValueError("Invalid article URL")
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(query), ""))


def load_sources(path: Path) -> list[Source]:
    with path.open("rb") as handle:
        document = tomllib.load(handle)
    sources = []
    seen: set[str] = set()
    for item in document.get("sources", []):
        if not item.get("enabled", True):
            continue
        source = Source(
            id=item["id"],
            name=item["name"],
            url=item["url"],
            topic=Topic(item["topic"]),
            hosts=tuple(item["hosts"]),
            priority=int(item.get("priority", 0)),
            kind=item.get("kind", "rss"),
            lookback_hours=int(item.get("lookback_hours", 24)),
            latest_only=bool(item.get("latest_only", False)),
        )
        if source.kind not in {"rss", "telegram"}:
            raise ValueError("Unknown source kind")
        check_feed_url(source.url, source)
        if source.id in seen:
            raise ValueError("Duplicate source ID")
        seen.add(source.id)
        sources.append(source)
    return sources


def check_feed_url(url: str, source: Source) -> None:
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname not in source.hosts
        or parts.username
        or parts.password
        or parts.port not in {None, 443}
    ):
        raise ValueError("Feed URL outside configured HTTPS allowlist")


class RssReader:
    def __init__(self, client: httpx.AsyncClient, max_bytes: int) -> None:
        self.client = client
        self.max_bytes = max_bytes

    async def fetch(self, source: Source) -> list[Article]:
        url = source.url
        for _ in range(4):
            check_feed_url(url, source)
            async with self.client.stream("GET", url, follow_redirects=False) as response:
                if response.is_redirect:
                    url = urljoin(url, response.headers["location"])
                    continue
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > self.max_bytes:
                        raise ValueError("Feed exceeds size limit")
                return self.parse(bytes(content), source)
        raise ValueError("Too many feed redirects")

    @staticmethod
    def parse(content: bytes, source: Source) -> list[Article]:
        if source.kind == "telegram":
            return parse_telegram(content, source)
        try:
            ElementTree.fromstring(content, forbid_dtd=True)
        except DefusedXmlException as exc:
            raise ValueError("DTD and entities are not accepted") from exc
        feed = feedparser.parse(content)
        if not feed.get("version"):
            raise ValueError("Not a recognized feed")
        now = datetime.now(UTC)
        articles = []
        for entry in feed.entries[:100]:
            stamp = entry.get("published_parsed") or entry.get("updated_parsed")
            if not stamp:
                continue
            published = datetime.fromtimestamp(calendar.timegm(stamp), UTC)
            if (
                not now - timedelta(hours=max(48, source.lookback_hours))
                <= published
                <= now + timedelta(minutes=10)
            ):
                continue
            try:
                url = canonical_url(str(entry.get("link", "")))
            except ValueError:
                continue
            title = plain_text(str(entry.get("title", "")))[:300]
            text = plain_text(str(entry.get("summary", "")))[:6000]
            if source.latest_only and entry.get("content"):
                text = plain_text(" ".join(
                    str(part.get("value", "")) for part in entry["content"]
                ))[:6000]
            if len(text) < 60 or not title:
                continue
            articles.append(
                Article(
                    id=hashlib.sha256(url.encode()).hexdigest(),
                    source_id=source.id,
                    source_name=source.name,
                    topic=source.topic,
                    title=title,
                    url=url,
                    text=text,
                    published_at=published,
                    priority=source.priority,
                )
            )
        return articles
