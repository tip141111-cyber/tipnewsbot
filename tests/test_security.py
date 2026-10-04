import io
import logging

from tipnews.application.rendering import render_digest
from tipnews.domain.models import DigestItem, Topic
from tipnews.logging import RedactingFormatter


def test_token_is_redacted_in_exception_and_url() -> None:
    token = str(123456789) + ":" + "synthetic_" * 5
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(RedactingFormatter("%(message)s"))
    logger = logging.getLogger("test_redaction")
    logger.addHandler(handler)
    try:
        try:
            raise RuntimeError("https://api.telegram.org/bot" + token + "/getMe")
        except RuntimeError:
            logger.error("failure %s", token, exc_info=True)
        assert token not in output.getvalue()
    finally:
        logger.removeHandler(handler)


def test_model_html_cannot_override_source_link() -> None:
    item = DigestItem(
        "x",
        Topic.IT,
        "Title",
        '<a href="https://evil.test">Откройте новую подробную сводку новостей</a>',
        "https://source.test/article",
        "Source",
    )
    result = render_digest("2026-10-04", [item], {Topic.IT})
    assert result is not None
    assert "&lt;a href=" in result
    assert '<a href="https://source.test/article">Source</a>' in result


def test_digest_stays_below_telegram_limit() -> None:
    items = [
        DigestItem(
            str(i),
            Topic.IT,
            "Title",
            "Русская новость. " * 35,
            "https://source.test/" + str(i),
            "Source",
        )
        for i in range(10)
    ]
    result = render_digest("2026-10-04", items, {Topic.IT})
    assert result is not None and len(result) < 4096


def test_legacy_english_digest_is_not_shown() -> None:
    item = DigestItem(
        "a",
        Topic.WORLD,
        "Title",
        "The government announced a new policy today.",
        "https://source.test/article",
        "Source",
    )
    assert render_digest("2026-10-04", [item], {Topic.WORLD}) is None
