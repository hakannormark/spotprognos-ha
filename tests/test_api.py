"""Tests for the plain API client."""

from __future__ import annotations

import asyncio
from datetime import datetime
import json

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.spotprognos.api import (
    DEFAULT_BASE_URL,
    SpotprognosClient,
    SpotprognosConnectionError,
    SpotprognosDataError,
    parse_forecast,
    parse_longterm,
    parse_models,
)

from . import load_json

FORECAST_URL = f"{DEFAULT_BASE_URL}zones/SE3/forecast.json"


def test_parse_real_forecast() -> None:
    forecast = parse_forecast(load_json("forecast_SE3.json"))

    assert forecast.zone == "SE3"
    assert forecast.zone_name == "Stockholm"
    assert forecast.run_id == "20260910T1331Z"
    assert forecast.default_model == "shrunk_scaled"
    assert "market_scaled" in forecast.models
    assert forecast.degraded is False
    assert forecast.demo is False
    assert forecast.fx.rate == pytest.approx(11.1495)
    assert forecast.fx.stale is False
    assert len(forecast.series) == 207

    first = forecast.series[0]
    assert first.start == datetime.fromisoformat("2026-09-09T00:00:00+02:00")
    assert first.actual == pytest.approx(85.03)
    assert first.source == "official"
    # Yesterday's hours carry no model values in this file.
    assert first.models == {}

    later = forecast.series[72]
    assert later.actual is None
    assert later.source == "forecast"
    band = later.models["shrunk_scaled"]
    assert (band.p10, band.p50, band.p90) == pytest.approx((3.309, 26.906, 74.314))

    starts = [hour.start for hour in forecast.series]
    assert starts == sorted(starts)


def test_unknown_fields_are_ignored() -> None:
    data = load_json("forecast_SE3.json")
    data["something_new"] = {"nested": [1, 2, 3]}
    data["series"][30]["quarter_prices"] = [1, 2, 3, 4]
    data["series"][30]["models"]["new_model"] = {"p50": 1.0, "extra": "x"}

    forecast = parse_forecast(data)

    assert forecast.series[30].models["new_model"].p50 == 1.0
    assert forecast.series[30].models["new_model"].p10 is None


def test_model_without_p50_is_dropped_for_that_hour() -> None:
    data = load_json("forecast_SE3.json")
    data["series"][30]["models"]["shrunk_scaled"] = {"p10": 1.0, "p90": 2.0}
    del data["series"][31]["models"]["weather_scaled"]

    forecast = parse_forecast(data)

    assert "shrunk_scaled" not in forecast.series[30].models
    assert "weather_scaled" not in forecast.series[31].models
    assert "shrunk_scaled" in forecast.series[31].models


def test_hours_without_valid_timestamp_are_skipped() -> None:
    data = load_json("forecast_SE3.json")
    data["series"][0]["ts"] = "not a time"
    data["series"][1]["ts"] = "2026-09-09T01:00:00"  # no offset
    del data["series"][2]["ts"]

    assert len(parse_forecast(data).series) == 204


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("fx"),
        lambda d: d["fx"].pop("rate"),
        lambda d: d["fx"].update(rate=0),
        lambda d: d["fx"].update(rate="11.1"),
        lambda d: d.pop("series"),
        lambda d: d.update(series=[]),
        lambda d: d.pop("default_model"),
        lambda d: d.pop("zone"),
        lambda d: d.update(generated_at="yesterday"),
    ],
)
def test_forecast_missing_required_fields(mutate) -> None:
    data = load_json("forecast_SE3.json")
    mutate(data)
    with pytest.raises(SpotprognosDataError):
        parse_forecast(data)


def test_parse_models() -> None:
    catalog = parse_models(load_json("models.json"))

    assert catalog.default_model == "shrunk_scaled"
    assert [m.id for m in catalog.models] == [
        "seasonal_naive",
        "weather_scaled",
        "shrunk_scaled",
        "recency_scaled",
        "ensemble",
        "market_scaled",
    ]
    default = next(m for m in catalog.models if m.is_default)
    assert default.id == "shrunk_scaled"
    assert default.name_sv == "Väderskalad, dämpad nivå"


def test_parse_longterm() -> None:
    longterm = parse_longterm(load_json("longterm.json"))

    assert longterm.default_model == "lt_damped"
    assert set(longterm.zones) == {"SE1", "SE2", "SE3", "SE4"}
    months = longterm.zones["SE3"]
    assert [m.horizon for m in months] == [1, 2, 3]
    nxt = months[0]
    assert nxt.month == "2026-10"
    assert nxt.models["lt_damped"].p10 is not None
    assert nxt.models["lt_damped"].p90 is not None
    assert nxt.market is not None
    assert nxt.market["tenor"] in {"month", "quarter", "year"}
    assert nxt.models["lt_market"].p50 == nxt.market["p50"]


@pytest.fixture
async def client(aioclient_mock: AiohttpClientMocker):
    session = aioclient_mock.create_session(asyncio.get_running_loop())
    yield SpotprognosClient(session)
    await session.close()


async def test_client_fetches_and_parses(
    aioclient_mock: AiohttpClientMocker, client: SpotprognosClient
) -> None:
    aioclient_mock.get(FORECAST_URL, text=json.dumps(load_json("forecast_SE3.json")))
    aioclient_mock.get(
        f"{DEFAULT_BASE_URL}models.json", text=json.dumps(load_json("models.json"))
    )
    aioclient_mock.get(
        f"{DEFAULT_BASE_URL}longterm.json", text=json.dumps(load_json("longterm.json"))
    )

    assert (await client.async_get_forecast("SE3")).zone == "SE3"
    assert (await client.async_get_models()).default_model == "shrunk_scaled"
    assert (await client.async_get_longterm()).default_model == "lt_damped"
    assert aioclient_mock.call_count == 3


@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"status": 404}, SpotprognosConnectionError),
        ({"status": 500}, SpotprognosConnectionError),
        ({"exc": aiohttp.ClientError()}, SpotprognosConnectionError),
        ({"exc": TimeoutError()}, SpotprognosConnectionError),
        ({"text": "<html>not json</html>"}, SpotprognosDataError),
        ({"text": "[1, 2, 3]"}, SpotprognosDataError),
        ({"text": '{"zone": "SE3"}'}, SpotprognosDataError),
    ],
)
async def test_client_errors(
    aioclient_mock: AiohttpClientMocker, client: SpotprognosClient, kwargs, error
) -> None:
    aioclient_mock.get(FORECAST_URL, **kwargs)

    with pytest.raises(error):
        await client.async_get_forecast("SE3")
