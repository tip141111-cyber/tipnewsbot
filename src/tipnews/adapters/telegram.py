import time
from collections import OrderedDict
from datetime import datetime
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramNetworkError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from tipnews.application.rendering import render_digest
from tipnews.config import Settings
from tipnews.domain.models import TOPIC_NAMES, Source, Topic
from tipnews.ports import DeliveryBlocked, DeliveryRetry, DeliveryUncertain, WeatherProvider
from tipnews.ports.storage import Store


class TelegramSender:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(chat_id, text)
        except TelegramForbiddenError as exc:
            raise DeliveryBlocked from exc
        except TelegramRetryAfter as exc:
            raise DeliveryRetry(exc.retry_after) from exc
        except TelegramNetworkError as exc:
            raise DeliveryUncertain from exc


def build_router(
    store: Store,
    settings: Settings,
    sources: list[Source],
    *,
    weather: WeatherProvider | None = None,
) -> Router:
    router = Router(name="tipnews")
    router.message.filter(F.chat.type == "private")
    available = {source.topic for source in sources}
    recent: OrderedDict[int, float] = OrderedDict()

    async def throttle(handler: Any, event: Any, data: dict[str, Any]) -> Any:
        user = event.from_user
        if user:
            now = time.monotonic()
            if now - recent.get(user.id, -10) < 1:
                if isinstance(event, CallbackQuery):
                    await event.answer()
                return None
            recent[user.id] = now
            recent.move_to_end(user.id)
            if len(recent) > 4096:
                recent.popitem(last=False)
        return await handler(event, data)

    router.message.outer_middleware.register(throttle)
    router.callback_query.outer_middleware.register(throttle)

    async def keyboard(chat_id: int) -> InlineKeyboardMarkup:
        selected = await store.preferences(chat_id)
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{'[x]' if topic in selected else '[ ]'} {TOPIC_NAMES[topic]}",
                        callback_data=f"topic:{topic}",
                    )
                ]
                for topic in Topic
                if topic in available
            ]
        )

    @router.message(CommandStart())
    async def start(message: Message) -> None:
        await store.subscribe(message.chat.id, available)
        await message.answer(
            f"Вы подписаны на tipnews. Сводка ежедневно в "
            f"{settings.digest_time:%H:%M} ({escape(settings.timezone)}).\n"
            "/topics — рубрики\n/digest — сегодняшний выпуск\n"
            "/weather — погода в Рязани\n"
            "/sources — источники\n/stop — приостановить подписку",
            reply_markup=await keyboard(message.chat.id),
        )

    @router.message(Command("stop"))
    async def stop(message: Message) -> None:
        await store.set_active(message.chat.id, False)
        await message.answer("Подписка приостановлена. /start — возобновить.")

    @router.message(Command("id"))
    async def user_id(message: Message) -> None:
        if message.from_user:
            await message.answer(f"Ваш Telegram ID: <code>{message.from_user.id}</code>")

    @router.message(Command("stats"))
    async def stats(message: Message) -> None:
        if not message.from_user or not settings.is_admin(message.from_user.id):
            return
        total, active, topics = await store.subscriber_stats()
        paused = total - active
        rows = [f"Пользователей: {total}", f"Активных подписок: {active}", f"На паузе: {paused}"]
        rows.append(
            "\n".join(
                f"{TOPIC_NAMES[topic]}: {count}"
                for topic, count in sorted(topics.items(), key=lambda item: TOPIC_NAMES[item[0]])
            )
        )
        await message.answer("<b>Статистика tipnews</b>\n" + "\n".join(rows))

    @router.message(Command("topics"))
    async def topics(message: Message) -> None:
        await message.answer("Рубрики", reply_markup=await keyboard(message.chat.id))

    @router.callback_query(F.data.startswith("topic:"))
    async def toggle(callback: CallbackQuery) -> None:
        if not isinstance(callback.message, Message) or callback.message.chat.type != "private":
            await callback.answer()
            return
        try:
            topic = Topic((callback.data or "").split(":", 1)[1])
        except (ValueError, IndexError):
            await callback.answer()
            return
        if topic in available:
            await store.toggle_topic(callback.message.chat.id, topic)
            await callback.message.edit_reply_markup(
                reply_markup=await keyboard(callback.message.chat.id),
            )
        await callback.answer()

    @router.message(Command("digest"))
    async def digest(message: Message) -> None:
        day = datetime.now(ZoneInfo(settings.timezone)).date().isoformat()
        items = await store.digest(day)
        if weather:
            items = [item for item in items or [] if item.topic != Topic.WEATHER]
            forecast = await weather.today(datetime.fromisoformat(day).date())
            if forecast:
                items.insert(0, forecast)
        preferences = await store.preferences(message.chat.id)
        text = render_digest(day, items, preferences) if items else None
        await message.answer(text or "Выпуска по выбранным рубрикам пока нет. /topics")

    @router.message(Command("weather"))
    async def weather_today(message: Message) -> None:
        day = datetime.now(ZoneInfo("Europe/Moscow")).date()
        forecast = await weather.today(day) if weather else None
        if forecast:
            await message.answer(
                f"<b>Погода · Рязань</b>\n{escape(forecast.summary)}\n"
                f'<a href="{escape(forecast.url, quote=True)}">Open-Meteo</a>',
            )
        else:
            await message.answer("Прогноз для Рязани временно недоступен. Попробуйте позже.")

    @router.message(Command("sources"))
    async def source_list(message: Message) -> None:
        text = "\n".join(f"{escape(TOPIC_NAMES[s.topic])}: {escape(s.name)}" for s in sources)
        if weather:
            text += '\nПогода в Рязани: <a href="https://open-meteo.com/">Open-Meteo</a>'
        await message.answer(text or "Источники пока не настроены.")

    return router
