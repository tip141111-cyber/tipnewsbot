import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from tipnews.adapters.gemini import GeminiSummarizer, GeminiUnavailable
from tipnews.adapters.persistence.database import create_engine
from tipnews.adapters.persistence.models import Base, InferenceUsageRow
from tipnews.adapters.persistence.repository import SqlStore
from tipnews.config import Settings
from tipnews.domain.models import Article

RUSSIAN = "Вышла версия 12 с улучшениями хранения данных."


def reply(text: str = RUSSIAN, finish: str = "STOP") -> dict:
    return {
        "candidates": [{"finishReason": finish, "content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 20},
    }


def settings(**kwargs: object) -> Settings:
    return Settings(gemini_api_key=SecretStr("synthetic-key"), **kwargs)


async def test_gemini_request_and_persisted_usage(store: SqlStore, article: Article) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "generativelanguage.googleapis.com"
        assert not request.url.query
        assert request.headers["x-goog-api-key"] == "synthetic-key"
        body = json.loads(request.content)
        assert "по-русски" in body["systemInstruction"]["parts"][0]["text"]
        assert body["contents"][0]["parts"][0]["text"] == article.title + "\n" + article.text
        assert body["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}
        return httpx.Response(200, json=reply())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await GeminiSummarizer(client, settings(), store).summarize(article) == RUSSIAN
    async with store.sessions() as session:
        row = (await session.scalars(select(InferenceUsageRow))).one()
        assert (row.requests, row.input_tokens, row.output_tokens) == (1, 100, 20)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [],
        {"promptFeedback": {"blockReason": "SAFETY"}},
        {"candidates": []},
        reply(finish="MAX_TOKENS"),
        reply(finish="SAFETY"),
        reply("Вышла версия 99 с улучшениями хранения данных."),
        reply("Читайте подробную сводку на https://example.org."),
        reply("<b>Вышла версия 12 с улучшениями хранения данных.</b>"),
        reply("Слишком коротко"),
    ],
)
async def test_rejects_unsafe_or_incomplete_response(
    store: SqlStore, article: Article, payload: object
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ValueError):
            await GeminiSummarizer(client, settings(), store).summarize(article)


@pytest.mark.parametrize("translated", [True, False])
async def test_one_russian_retry(store: SqlStore, article: Article, translated: bool) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        text = (
            RUSSIAN
            if translated and len(calls) == 2
            else "Version 12 improves storage performance."
        )
        return httpx.Response(200, json=reply(text))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        summarizer = GeminiSummarizer(client, settings(), store)
        if translated:
            assert await summarizer.summarize(article) == RUSSIAN
        else:
            with pytest.raises(ValueError, match="not Russian"):
                await summarizer.summarize(article)
    assert len(calls) == 2
    assert "Предыдущий ответ" in calls[1]["systemInstruction"]["parts"][0]["text"]


@pytest.mark.parametrize("status", [429, 503, 0])
async def test_bounded_retries_and_recovery(
    store: SqlStore, article: Article, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("tipnews.adapters.gemini.asyncio.sleep", sleep)
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) < 3:
            if status == 0:
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            return httpx.Response(status, headers={"retry-after": "2"})
        return httpx.Response(200, json=reply())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        assert await GeminiSummarizer(client, settings(), store).summarize(article) == RUSSIAN
    assert len(calls) == 3 and sleep.await_count == 2


@pytest.mark.parametrize("status,expected", [(400, 1), (401, 1), (403, 1), (302, 1), (503, 3)])
async def test_failure_never_exposes_body_or_key(
    store: SqlStore,
    article: Article,
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    expected: int,
) -> None:
    monkeypatch.setattr("tipnews.adapters.gemini.asyncio.sleep", AsyncMock())
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            status, text="synthetic-key", headers={"location": "https://evil.test"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(GeminiUnavailable) as failure:
            await GeminiSummarizer(client, settings(), store).summarize(article)
        assert "synthetic-key" not in str(failure.value)
    assert len(calls) == expected


async def test_limit_survives_new_summarizer_and_counts_failed_attempts(
    store: SqlStore, article: Article
) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        config = settings(gemini_daily_request_limit=1)
        with pytest.raises(GeminiUnavailable, match="403"):
            await GeminiSummarizer(client, config, store).summarize(article)
        with pytest.raises(GeminiUnavailable, match="daily request limit"):
            await GeminiSummarizer(client, config, store).summarize(article)
    assert len(calls) == 1
    assert await store.reserve_inference("2099-01-01", 1)
    assert not await store.reserve_inference(datetime.now(UTC).date().isoformat(), 1)


async def test_secret_file_and_cache_version(
    store: SqlStore, article: Article, tmp_path: Path
) -> None:
    secret = tmp_path / "key"
    secret.write_text("file-key", encoding="utf-8")

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-goog-api-key"] == "file-key"
        return httpx.Response(200, json=reply())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        model = GeminiSummarizer(client, settings(gemini_api_key_file=secret), store)
        assert await model.summarize(article) == RUSSIAN
        assert "file-key" not in model.version and "synthetic-key" not in model.version
        changed = GeminiSummarizer(client, settings(gemini_max_output_tokens=1024), store)
        assert changed.version != model.version


async def test_missing_key_makes_no_request(store: SqlStore, article: Article) -> None:
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: pytest.fail())) as client:
        config = Settings(gemini_api_key=SecretStr(""), gemini_api_key_file=None)
        with pytest.raises(GeminiUnavailable, match="not configured"):
            await GeminiSummarizer(client, config, store).summarize(article)


async def test_budget_atomic_across_stores_and_survives_reopen(tmp_path: Path) -> None:
    url = "sqlite+aiosqlite:///" + (tmp_path / "budget.db").as_posix()
    engine = create_engine(url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    stores = [SqlStore(engine), SqlStore(engine)]
    results = await asyncio.gather(
        *(stores[index % 2].reserve_inference("2026-10-24", 3) for index in range(12))
    )
    assert sum(results) == 3
    await engine.dispose()
    reopened = create_engine(url)
    try:
        assert not await SqlStore(reopened).reserve_inference("2026-10-24", 3)
        assert await SqlStore(reopened).reserve_inference("2026-10-25", 3)
    finally:
        await reopened.dispose()
