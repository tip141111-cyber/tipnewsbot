import argparse
import asyncio
import json
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from alembic import command
from alembic.config import Config

from tipnews.adapters.sources import load_sources
from tipnews.application.rendering import render_digest
from tipnews.bootstrap import components, run_bot
from tipnews.config import Settings
from tipnews.domain.models import Topic
from tipnews.logging import configure_logging


async def collect(settings: Settings) -> None:
    async with components(settings) as (_, pipeline):
        count = await pipeline.collect()
        print(json.dumps({"inserted": count}))


async def prepare(settings: Settings, *, refresh: bool = False) -> None:
    async with components(settings) as (_, pipeline):
        await pipeline.collect()
        count = await pipeline.prepare(datetime.now(ZoneInfo(settings.timezone)), refresh=refresh)
        if not count:
            raise RuntimeError("No digest prepared; inspect source/model events")
        print(json.dumps({"digest_items": count}))


async def weather_today(settings: Settings) -> None:
    async with components(settings) as (_, pipeline):
        items = await pipeline.with_weather([], datetime.now(ZoneInfo("Europe/Moscow")).date())
        print(items[0].summary if items else "Прогноз временно недоступен.")


async def preview(settings: Settings) -> None:
    day = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
    async with components(settings) as (store, _):
        items = await store.digest(day)
        print(render_digest(day, items, set(Topic)) if items else "Выпуска пока нет.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="tipnews")
    parser.add_argument(
        "command",
        choices=["run", "migrate", "collect", "prepare", "preview", "weather", "check", "health"],
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Обновить текущий выпуск без повторной рассылки"
    )
    args = parser.parse_args()
    configure_logging()
    try:
        settings = Settings()
        if args.command == "check":
            print(
                json.dumps(
                    {
                        "sources": len(load_sources(settings.sources_file)),
                        "timezone": settings.timezone,
                        "status": "configuration_ok",
                    }
                )
            )
        elif args.command == "health":
            if time.time() - settings.heartbeat_file.stat().st_mtime > 90:
                raise RuntimeError("Heartbeat stale")
        elif args.command == "migrate":
            command.upgrade(Config("alembic.ini"), "head")
        elif args.command == "collect":
            asyncio.run(collect(settings))
        elif args.command == "prepare":
            asyncio.run(prepare(settings, refresh=args.refresh))
        elif args.command == "preview":
            asyncio.run(preview(settings))
        elif args.command == "weather":
            asyncio.run(weather_today(settings))
        else:
            asyncio.run(run_bot(settings))
    except KeyboardInterrupt:
        return
    except Exception as exc:
        # Never print config validation input, database URLs or exception request bodies.
        logging.getLogger(__name__).error("command_failed error=%s", type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
