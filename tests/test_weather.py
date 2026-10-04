from datetime import date

import httpx
import pytest

from tipnews.adapters.weather import OpenMeteoWeather, parse_forecast
from tipnews.application.rendering import render_digest
from tipnews.domain.models import Topic

DAY = date(2026, 10, 4)


def payload() -> dict:
    return {
        "hourly_units": {"temperature_2m": "°C"},
        "hourly": {
            "time": ["2026-10-04T08:00", "2026-10-04T14:00", "2026-10-05T03:00"],
            "temperature_2m": [4.0, 12.0, 2.0],
        },
        "daily_units": {
            "temperature_2m_min": "°C",
            "wind_speed_10m_max": "m/s",
            "precipitation_probability_max": "%",
        },
        "daily": {
            "time": [DAY.isoformat()],
            "weather_code": [61],
            "temperature_2m_min": [4.0],
            "temperature_2m_max": [12.0],
            "precipitation_probability_max": [80],
            "wind_speed_10m_max": [5.0],
        },
    }


def test_forecast_is_russian_dated_and_uses_correct_units() -> None:
    item = parse_forecast(payload(), DAY)
    assert "04.10" in item.summary and "небольшой дождь" in item.summary
    assert "Утро (08:00): +4 °C" in item.summary
    assert "день (14:00): +12 °C" in item.summary
    assert "ближайшая ночь (03:00): +2 °C" in item.summary
    assert "80%" in item.summary and "5 м/с" in item.summary
    assert item.topic == Topic.WEATHER
    assert item.url == "https://open-meteo.com/"
    assert "Погода" in render_digest(DAY.isoformat(), [item], set())


def test_missing_or_wrong_day_is_never_rendered_as_today() -> None:
    with pytest.raises(ValueError):
        parse_forecast(payload(), date(2026, 10, 5))
    data = payload()
    data["hourly"]["temperature_2m"][0] = None
    with pytest.raises(TypeError):
        parse_forecast(data, DAY)


async def test_forecast_shared_cache_and_explicit_moscow_timezone() -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.url.params["timezone"] == "Europe/Moscow"
        assert request.url.params["wind_speed_unit"] == "ms"
        return httpx.Response(200, json=payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        service = OpenMeteoWeather(client)
        assert await service.today(DAY) is not None
        assert await service.today(DAY) is not None
    assert len(calls) == 1


async def test_api_failure_is_cached_without_inventing_weather() -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        service = OpenMeteoWeather(client)
        assert await service.today(DAY) is None
        assert await service.today(DAY) is None
    assert len(calls) == 1
