import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.types import BotCommand
from filelock import FileLock

from tipnews.adapters.llm import SYSTEM_PROMPT, OllamaSummarizer
from tipnews.adapters.persistence.database import create_engine
from tipnews.adapters.persistence.repository import SqlStore
from tipnews.adapters.sources import RssReader, load_sources
from tipnews.adapters.telegram import TelegramSender, build_router
from tipnews.adapters.weather import OpenMeteoWeather
from tipnews.application.pipeline import Pipeline
from tipnews.config import Settings
from tipnews.jobs.runner import delivery_loop, generation_loop


@asynccontextmanager
async def components(settings: Settings) -> AsyncIterator[tuple[SqlStore, Pipeline]]:
    engine = create_engine(settings.database_url)
    try:
        async with (
            httpx.AsyncClient(
                timeout=20, trust_env=False, headers={"User-Agent": "tipnews/0.1 RSS reader"}
            ) as feed_client,
            httpx.AsyncClient(timeout=180, trust_env=False) as model_client,
        ):
            store = SqlStore(engine)
            pipeline = Pipeline(
                store,
                RssReader(feed_client, settings.feed_max_bytes),
                OllamaSummarizer(model_client, settings.ollama_url, settings.ollama_model),
                load_sources(settings.sources_file),
                settings.ollama_model + SYSTEM_PROMPT,
                OpenMeteoWeather(feed_client) if settings.weather_enabled else None,
            )
            yield store, pipeline
    finally:
        await engine.dispose()


async def run_bot(settings: Settings) -> None:
    token = settings.token_file.read_text(encoding="utf-8").strip()
    settings.heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
    with FileLock(str(settings.heartbeat_file.with_suffix(".lock")), timeout=0):
        async with components(settings) as (store, pipeline):
            async with Bot(
                token,
                default=DefaultBotProperties(
                    parse_mode="HTML",
                    link_preview_is_disabled=True,
                ),
            ) as bot:
                identity = await bot.get_me()
                logging.getLogger(__name__).info("bot_ready username=%s", identity.username)
                await bot.set_my_commands(
                    [
                        BotCommand(command="start", description="Подписаться на новости"),
                        BotCommand(command="digest", description="Сегодняшняя сводка"),
                        BotCommand(command="weather", description="Погода в Рязани на сегодня"),
                        BotCommand(command="topics", description="Выбрать рубрики"),
                        BotCommand(command="sources", description="Источники новостей"),
                        BotCommand(command="stop", description="Приостановить подписку"),
                        BotCommand(command="id", description="Показать мой Telegram ID"),
                        BotCommand(command="stats", description="Статистика подписчиков"),
                    ]
                )
                dispatcher = Dispatcher()
                dispatcher.include_router(
                    build_router(store, settings, pipeline.sources, weather=pipeline.weather),
                )
                tasks = [
                    asyncio.create_task(generation_loop(settings, store, pipeline)),
                    asyncio.create_task(delivery_loop(settings, store, TelegramSender(bot))),
                    asyncio.create_task(dispatcher.start_polling(bot, close_bot_session=False)),
                ]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
