import asyncio
import logging
import math
import time
from datetime import date, timedelta
from typing import Any

import httpx

from tipnews.domain.models import DigestItem, Topic

logger = logging.getLogger(__name__)
CONDITIONS = {
    0: "ясно",
    1: "преимущественно ясно",
    2: "переменная облачность",
    3: "пасмурно",
    45: "туман",
    48: "туман с изморозью",
    51: "слабая морось",
    53: "морось",
    55: "сильная морось",
    56: "переохлаждённая морось",
    57: "переохлаждённая морось",
    61: "небольшой дождь",
    63: "дождь",
    65: "сильный дождь",
    66: "ледяной дождь",
    67: "сильный ледяной дождь",
    71: "небольшой снег",
    73: "снег",
    75: "сильный снег",
    77: "снежные зёрна",
    80: "кратковременный дождь",
    81: "ливни",
    82: "сильные ливни",
    85: "снежные заряды",
    86: "сильные снежные заряды",
    95: "гроза",
    96: "гроза с градом",
    99: "сильная гроза с градом",
}


def parse_forecast(payload: dict[str, Any], day: date) -> DigestItem:
    daily = payload["daily"]
    index = daily["time"].index(day.isoformat())
    units = payload["daily_units"]
    if (
        payload["hourly_units"].get("temperature_2m") != "°C"
        or units.get("wind_speed_10m_max") != "m/s"
    ):
        raise ValueError("Unexpected weather units")
    if units.get("precipitation_probability_max") != "%":
        raise ValueError("Unexpected precipitation units")

    def number(key: str) -> float:
        value = float(daily[key][index])
        if not math.isfinite(value):
            raise ValueError("Missing weather value")
        return value

    hourly = payload["hourly"]

    def temperature(target: date, hour: int) -> float:
        position = hourly["time"].index(f"{target.isoformat()}T{hour:02d}:00")
        value = float(hourly["temperature_2m"][position])
        if not math.isfinite(value):
            raise ValueError("Missing hourly temperature")
        return value

    morning = temperature(day, 8)
    afternoon = temperature(day, 14)
    night = temperature(day + timedelta(days=1), 3)
    rain, wind = number("precipitation_probability_max"), number("wind_speed_10m_max")
    if not 0 <= rain <= 100 or wind < 0:
        raise ValueError("Invalid weather values")
    code = int(number("weather_code"))
    condition = CONDITIONS.get(code, "прогноз погоды")
    summary = (
        f"Сегодня, {day:%d.%m}: {condition}. "
        f"Утро (08:00): {morning:+.0f} °C / день (14:00): {afternoon:+.0f} °C / "
        f"ближайшая ночь (03:00): {night:+.0f} °C; "
        f"вероятность осадков до {rain:.0f}%; ветер до {wind:.0f} м/с."
    )
    return DigestItem(
        f"weather:ryazan:{day}",
        Topic.WEATHER,
        "Погода в Рязани",
        summary,
        "https://open-meteo.com/",
        "Open-Meteo",
    )


class OpenMeteoWeather:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self._cache: tuple[date, float, DigestItem | None] | None = None
        self._lock = asyncio.Lock()

    async def today(self, day: date) -> DigestItem | None:
        async with self._lock:
            if self._cache and self._cache[0] == day and time.monotonic() < self._cache[1]:
                return self._cache[2]
            try:
                response = await self.client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": 54.6269,
                        "longitude": 39.6916,
                        "timezone": "Europe/Moscow",
                        "forecast_days": 2,
                        "wind_speed_unit": "ms",
                        "temperature_unit": "celsius",
                        "hourly": "temperature_2m",
                        "daily": "weather_code,precipitation_probability_max,wind_speed_10m_max",
                    },
                    timeout=10,
                )
                response.raise_for_status()
                item = parse_forecast(response.json(), day)
            except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError) as exc:
                logger.warning("weather_unavailable error=%s", type(exc).__name__)
                self._cache = (day, time.monotonic() + 300, None)
                return None
            self._cache = (day, time.monotonic() + 3600, item)
            return item
