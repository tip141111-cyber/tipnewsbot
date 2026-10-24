import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from tipnews.adapters.llm import SYSTEM_PROMPT
from tipnews.config import Settings
from tipnews.domain.language import is_russian_summary
from tipnews.domain.models import Article
from tipnews.domain.summaries import validate_summary
from tipnews.ports.storage import Store

logger = logging.getLogger(__name__)
GEMINI_PROMPT = SYSTEM_PROMPT + (
    " Пиши естественно и конкретно: сначала главное событие, затем важная деталь."
    " Старайся уложиться в 320 символов. Не используй канцелярит и рекламные формулировки."
)


class GeminiUnavailable(RuntimeError):
    """No usable response after bounded attempts; never include keys or response bodies."""


class GeminiSummarizer:
    def __init__(self, client: httpx.AsyncClient, settings: Settings, store: Store) -> None:
        self.client = client
        self.settings = settings
        self.store = store
        self.url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent"
        )
        self.generation: dict[str, Any] = {
            "temperature": 0,
            "maxOutputTokens": settings.gemini_max_output_tokens,
        }
        if settings.gemini_model.startswith("gemini-2.5-flash"):
            self.generation["thinkingConfig"] = {"thinkingBudget": 0}
        # Record all content-affecting choices, never credentials, in the cache version.
        self.version = json.dumps(
            {
                "provider": "gemini",
                "model": settings.gemini_model,
                "prompt": GEMINI_PROMPT,
                "generation": self.generation,
                "input": "title300-text6000-v1",
                "validation": "russian-numbers-length-v2",
            },
            sort_keys=True,
        )

    def _key(self) -> str:
        path = self.settings.gemini_api_key_file
        key = (
            path.read_text(encoding="utf-8").strip()
            if path is not None
            else self.settings.gemini_api_key.get_secret_value().strip()
        )
        if not key:
            raise GeminiUnavailable("Gemini API key is not configured")
        return key

    async def _request(self, material: str, *, translate: bool = False) -> str:
        key = self._key()
        prompt = GEMINI_PROMPT
        if translate:
            prompt += " Предыдущий ответ был не на русском. Напиши только по-русски."
        payload = {
            "systemInstruction": {"parts": [{"text": prompt}]},
            "contents": [{"role": "user", "parts": [{"text": material}]}],
            "generationConfig": self.generation,
        }
        for attempt in range(3):
            day = datetime.now(UTC).date().isoformat()
            if not await self.store.reserve_inference(
                day, self.settings.gemini_daily_request_limit
            ):
                raise GeminiUnavailable("Gemini daily request limit reached")
            try:
                response = await self.client.post(
                    self.url,
                    headers={"x-goog-api-key": key},
                    json=payload,
                    timeout=self.settings.gemini_timeout_seconds,
                    follow_redirects=False,
                )
            except httpx.TransportError:
                if attempt == 2:
                    raise GeminiUnavailable("Gemini transport unavailable") from None
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code == 429 or response.status_code in {500, 502, 503, 504}:
                delay = float(2**attempt)
                try:
                    delay = max(delay, float(response.headers.get("retry-after", "0")))
                except ValueError:
                    # A date-valued Retry-After is left for the next scheduled attempt.
                    raise GeminiUnavailable("Gemini requested a later retry") from None
                if attempt == 2 or not 0 <= delay <= 30:
                    raise GeminiUnavailable(
                        f"Gemini temporarily unavailable ({response.status_code})"
                    )
                await asyncio.sleep(delay)
                continue
            if response.status_code != 200:
                raise GeminiUnavailable(f"Gemini request rejected ({response.status_code})")
            try:
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError
                usage = data.get("usageMetadata") or {}
                input_tokens = int(usage.get("promptTokenCount", 0))
                output_tokens = int(usage.get("candidatesTokenCount", 0)) + int(
                    usage.get("thoughtsTokenCount", 0)
                )
                if input_tokens < 0 or output_tokens < 0:
                    raise ValueError
                await self.store.record_inference(day, input_tokens, output_tokens)
                logger.info(
                    "gemini_usage input_tokens=%d output_tokens=%d", input_tokens, output_tokens
                )
                if data.get("promptFeedback", {}).get("blockReason"):
                    raise ValueError
                candidate = data["candidates"][0]
                if candidate.get("finishReason") != "STOP":
                    raise ValueError
                parts = candidate["content"]["parts"]
                if not isinstance(parts, list):
                    raise ValueError
                result = "".join(
                    part["text"] for part in parts if "text" in part and not part.get("thought")
                )
            except (ValueError, TypeError, KeyError, IndexError, AttributeError):
                raise ValueError("Gemini response is blocked, incomplete or invalid") from None
            return validate_summary(result, material)
        raise GeminiUnavailable("Gemini attempts exhausted")

    async def summarize(self, article: Article) -> str:
        # Full bounded feed material avoids Ollama's multi-stage lossy compression.
        material = f"{article.title[:300]}\n{article.text[:6000]}"
        result = await self._request(material)
        if not is_russian_summary(result):
            result = await self._request(material, translate=True)
        if not is_russian_summary(result):
            raise ValueError("Summary is not Russian after translation retry")
        return result
