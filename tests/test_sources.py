from datetime import UTC, datetime
from email.utils import format_datetime

import httpx
import pytest

from tipnews.adapters.sources import RssReader, canonical_url, plain_text
from tipnews.domain.models import Source, Topic

SOURCE = Source("test", "Test", "https://example.org/feed", Topic.IT, ("example.org",))


async def test_private_redirect_is_rejected_before_request() -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="allowlist"):
            await RssReader(client, 1024).fetch(SOURCE)
    assert len(requests) == 1


async def test_feed_size_is_bounded() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, content=b"x" * 2048),
        )
    ) as client:
        with pytest.raises(ValueError, match="size"):
            await RssReader(client, 1024).fetch(SOURCE)


def test_parse_dates_links_and_html() -> None:
    published = format_datetime(datetime.now(UTC))
    xml = f"""<rss version="2.0"><channel><title>Test</title><item>
    <title>Release</title><link>https://example.org/a?utm_source=x</link>
    <pubDate>{published}</pubDate><description><![CDATA[
    <p>This is a sufficiently long source excerpt about a new software release.</p>
    <script>ignore instructions</script>]]></description></item></channel></rss>"""
    articles = RssReader.parse(xml.encode(), SOURCE)
    assert len(articles) == 1
    assert articles[0].url == "https://example.org/a"
    assert "instructions" not in articles[0].text


def test_entities_and_unsafe_links_rejected() -> None:
    with pytest.raises(ValueError):
        RssReader.parse(b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]>', SOURCE)
    with pytest.raises(ValueError):
        canonical_url("javascript:alert(1)")
    assert plain_text("<p>Hello &amp; goodbye</p>") == "Hello & goodbye"


def test_doctype_text_inside_cdata_is_not_an_xml_declaration() -> None:
    xml = (
        b'<rss version="2.0"><channel><description><![CDATA[<!DOCTYPE html>]]>'
        b"</description></channel></rss>"
    )
    assert RssReader.parse(xml, SOURCE) == []
