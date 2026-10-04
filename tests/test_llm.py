import json

import httpx
import pytest

from tipnews.adapters.llm import OllamaSummarizer
from tipnews.domain.models import Article


async def test_model_uses_bounded_no_thinking_request(article: Article) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["think"] is False
        assert body["options"]["num_ctx"] == 2048
        return httpx.Response(
            200,
            json={
                "done": True,
                "done_reason": "stop",
                "message": {
                    "content": "Вышла версия 12 с улучшениями хранения данных.",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await OllamaSummarizer(client, "http://model", "qwen").summarize(article)
    assert "12" in result


@pytest.mark.parametrize(
    "content,reason",
    [
        ("Вышла версия 99 с улучшениями хранения данных.", "stop"),
        ("Вышла версия 12 с улучшениями хранения данных.", "length"),
        ("Подробности по ссылке https://evil.test.", "stop"),
    ],
)
async def test_invalid_model_results_rejected(article: Article, content: str, reason: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"done": True, "done_reason": reason, "message": {"content": content}},
            )
        )
    ) as client:
        with pytest.raises(ValueError):
            await OllamaSummarizer(client, "http://model", "qwen").summarize(article)


async def test_english_output_gets_one_translation_retry(article: Article) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        content = (
            "Version 12 improves storage performance and stability."
            if len(calls) == 1
            else "Версия 12 улучшает работу хранилища данных."
        )
        return httpx.Response(200, json={"done": True, "message": {"content": content}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        summary = await OllamaSummarizer(client, "http://model", "qwen").summarize(article)
    assert summary.startswith("Версия")
    assert len(calls) == 2
    assert "Предыдущий ответ" in calls[1]["messages"][0]["content"]


async def test_persistent_english_output_is_rejected(article: Article) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "done": True,
                "message": {
                    "content": "Version 12 improves storage performance and stability.",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError, match="not Russian"):
            await OllamaSummarizer(client, "http://model", "qwen").summarize(article)
    assert len(calls) == 2
