import hashlib
import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from urllib.parse import urlsplit

from tipnews.domain.models import Article, Source


class TelegramPage(HTMLParser):
    """Read public message text and original timestamps without Telegram credentials."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.posts: list[tuple[str, list[str], str]] = []
        self.post = ""
        self.parts: list[str] = []
        self.stamp = ""
        self.text_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("data-post"):
            self.finish_post()
            self.post = values["data-post"] or ""
        classes = (values.get("class") or "").split()
        if tag == "div":
            if "tgme_widget_message_text" in classes:
                self.text_depth = 1
            elif self.text_depth:
                self.text_depth += 1
        if tag == "time" and values.get("datetime"):
            self.stamp = values["datetime"] or ""
        if tag == "br" and self.text_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.text_depth:
            self.text_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.text_depth:
            self.parts.append(data)

    def finish_post(self) -> None:
        if self.post:
            self.posts.append((self.post, self.parts, self.stamp))
        self.post, self.parts, self.stamp, self.text_depth = "", [], "", 0


def parse_telegram(content: bytes, source: Source) -> list[Article]:
    parser = TelegramPage()
    parser.feed(content.decode("utf-8"))
    parser.finish_post()
    channel = urlsplit(source.url).path.rstrip("/").split("/")[-1]
    now = datetime.now(UTC)
    articles = []
    for post, parts, stamp in parser.posts[-100:]:
        if not re.fullmatch(re.escape(channel) + r"/\d+", post):
            continue
        try:
            published = datetime.fromisoformat(stamp)
        except ValueError:
            continue
        if published.tzinfo is None:
            continue
        if not now - timedelta(hours=48) <= published <= now + timedelta(minutes=10):
            continue
        text = re.sub(r"\s+", " ", "".join(parts)).strip()[:6000]
        if len(text) < 60:
            continue
        url = f"https://t.me/{post}"
        articles.append(
            Article(
                id=hashlib.sha256(url.encode()).hexdigest(),
                source_id=source.id,
                source_name=source.name,
                topic=source.topic,
                title=text[:300],
                url=url,
                text=text,
                published_at=published,
                priority=source.priority,
            )
        )
    return articles
