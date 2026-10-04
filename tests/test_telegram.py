from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User

from tipnews.adapters.persistence.repository import SqlStore
from tipnews.adapters.telegram import build_router
from tipnews.config import Settings
from tipnews.domain.models import DigestItem, Source, Topic


class Weather:
    async def today(self, day: date) -> DigestItem:
        assert day == datetime.now(ZoneInfo("Europe/Moscow")).date()
        return DigestItem(
            "weather",
            Topic.WEATHER,
            "Weather",
            "Сегодня в Рязани ясно и тепло.",
            "https://open-meteo.com/",
            "Open-Meteo",
        )


class FakeSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[SendMessage] = []

    async def close(self) -> None:
        pass

    async def make_request(self, bot: Bot, method: Any, timeout: Any = None) -> Any:  # noqa: ASYNC109
        if isinstance(method, SendMessage):
            self.messages.append(method)
            return Message(
                message_id=1,
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        return True

    async def stream_content(self, *args: Any, **kwargs: Any) -> Any:
        yield b""


async def test_start_and_digest_through_dispatcher(store: SqlStore) -> None:
    session = FakeSession()
    bot = Bot(
        str(123456789) + ":" + "synthetic_" * 5,
        session=session,
        default=DefaultBotProperties(parse_mode="HTML"),
    )
    source = Source("test", "Source", "https://example.org/rss", Topic.IT, ("example.org",))
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(store, Settings(), [source], weather=Weather()))

    def update(command: str, user_id: int) -> Update:
        return Update(
            update_id=user_id,
            message=Message(
                message_id=user_id,
                date=datetime.now(UTC),
                chat=Chat(id=user_id, type="private"),
                from_user=User(id=user_id, is_bot=False, first_name="Test"),
                text=command,
            ),
        )

    await dispatcher.feed_update(bot, update("/start", 42))
    assert await store.preferences(42) == {Topic.IT}
    assert "tipnews" in session.messages[-1].text
    day = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    await store.publish(
        day,
        [
            DigestItem(
                "a",
                Topic.IT,
                "Title",
                "Реальная короткая сводка.",
                "https://example.org/a",
                "Source",
            )
        ],
        0,
    )
    await store.subscribe(43, {Topic.IT})
    await dispatcher.feed_update(bot, update("/digest", 43))
    assert "https://example.org/a" in session.messages[-1].text
    assert "Погода" in session.messages[-1].text
    await dispatcher.feed_update(bot, update("/weather", 44))
    assert "Сегодня в Рязани ясно и тепло." in session.messages[-1].text
    assert "https://open-meteo.com/" in session.messages[-1].text
    await bot.session.close()
