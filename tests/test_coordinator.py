"""Tests for the coordinator: fetching, model choice and conversion."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging

import aiohttp
from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.spotprognos.const import (
    CONF_MARKUP,
    CONF_MODEL,
    CONF_UNIT,
    CONF_VAT,
    UNIT_EUR_MWH,
)
from custom_components.spotprognos.coordinator import PriceSettings

from .conftest import setup_entry

RATE = 11.1495
# Series index 40 is 2026-09-10 16:00, official price 43.793 EUR/MWh.
NOW_INDEX = 40
# Series index 72 is 2026-09-12 00:00, forecast only.
FORECAST_INDEX = 72


def at(text: str) -> datetime:
    return datetime.fromisoformat(text)


@pytest.mark.parametrize(
    ("settings", "eur", "expected"),
    [
        # öre/kWh = EUR/MWh × rate ÷ 10, not just ÷ 10.
        (PriceSettings(), 100.0, 111.495),
        (PriceSettings(), 43.793, 48.827),
        (PriceSettings(), -5.0, -5.575),
        (PriceSettings(unit=UNIT_EUR_MWH), 43.793, 43.793),
        # Markup is öre/kWh excluding VAT; VAT applies to spot plus markup.
        (PriceSettings(markup=5.0), 43.793, 53.827),
        (PriceSettings(vat=True), 100.0, 139.369),
        (PriceSettings(markup=5.0, vat=True), 43.793, 67.284),
        # In EUR/MWh the markup is converted: 5 öre/kWh = 50 SEK/MWh.
        (PriceSettings(unit=UNIT_EUR_MWH, markup=5.0), 43.793, 48.277),
        (PriceSettings(unit=UNIT_EUR_MWH, markup=5.0, vat=True), 43.793, 60.347),
    ],
)
def test_convert(settings: PriceSettings, eur: float, expected: float) -> None:
    assert settings.convert(eur, RATE) == pytest.approx(expected, abs=0.001)


def test_convert_none() -> None:
    assert PriceSettings(markup=5.0, vat=True).convert(None, RATE) is None


async def test_current_hour_uses_actual(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    await setup_entry(hass, config_entry)
    data = config_entry.runtime_data.data

    point = data.price_at(at("2026-09-10T16:30:00+02:00"))

    raw = api_data["forecast"]["series"][NOW_INDEX]
    assert raw["ts"] == "2026-09-10T16:00:00+02:00"
    assert point.source == "official"
    assert point.value == pytest.approx(raw["actual"] * RATE / 10, abs=0.001)
    assert point.p10 is None
    assert point.p90 is None


async def test_current_hour_without_actual_uses_model_p50(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    raw = api_data["forecast"]["series"][NOW_INDEX]
    raw["actual"] = None
    raw["source"] = "forecast"
    mock_api()

    await setup_entry(hass, config_entry)
    point = config_entry.runtime_data.data.price_at(at("2026-09-10T16:30:00+02:00"))

    band = raw["models"]["shrunk_scaled"]
    assert point.source == "forecast"
    assert point.value == pytest.approx(band["p50"] * RATE / 10, abs=0.001)
    assert point.p10 == pytest.approx(band["p10"] * RATE / 10, abs=0.001)
    assert point.p90 == pytest.approx(band["p90"] * RATE / 10, abs=0.001)


async def test_hour_is_chosen_by_home_assistant_clock(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    # generated_at says 15:31; the clock says otherwise and wins.
    await setup_entry(hass, config_entry)
    data = config_entry.runtime_data.data
    series = api_data["forecast"]["series"]

    for when, index in (
        ("2026-09-10T15:59:59+02:00", NOW_INDEX - 1),
        ("2026-09-10T16:00:00+02:00", NOW_INDEX),
        ("2026-09-12T00:10:00+02:00", FORECAST_INDEX),
        ("2026-09-10T14:00:00+00:00", NOW_INDEX),  # same instant in UTC
    ):
        point = data.price_at(at(when))
        assert point.start == at(series[index]["ts"]), when


async def test_prices_are_grouped_by_swedish_day(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    await setup_entry(hass, config_entry)
    data = config_entry.runtime_data.data

    today = data.prices_on(date(2026, 9, 10))
    assert len(today) == 24
    assert today[0].start == at("2026-09-10T00:00:00+02:00")
    assert today[-1].end == at("2026-09-11T00:00:00+02:00")
    assert all(p.official for p in today)
    assert len(data.prices_on(date(2026, 9, 12))) == 24


async def test_follows_default_model(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    api_data["forecast"]["default_model"] = "weather_scaled"
    mock_api()

    await setup_entry(hass, config_entry)
    data = config_entry.runtime_data.data

    band = api_data["forecast"]["series"][FORECAST_INDEX]["models"]["weather_scaled"]
    assert data.model == "weather_scaled"
    assert data.model_fallback is False
    point = data.price_at(at("2026-09-12T00:10:00+02:00"))
    assert point.value == pytest.approx(band["p50"] * RATE / 10, abs=0.001)


@pytest.mark.parametrize("entry_options", [{CONF_MODEL: "market_scaled"}])
async def test_uses_configured_model(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    await setup_entry(hass, config_entry)
    data = config_entry.runtime_data.data

    assert data.model == "market_scaled"
    assert data.model_fallback is False
    last = api_data["forecast"]["series"][-1]["models"]
    point = data.prices[-1]
    assert point.value == pytest.approx(
        last["market_scaled"]["p50"] * RATE / 10, abs=0.001
    )
    assert last["market_scaled"]["p50"] != last["shrunk_scaled"]["p50"]


@pytest.mark.parametrize("entry_options", [{CONF_MODEL: "weather_scaled"}])
async def test_missing_model_falls_back_and_logs_once(
    hass: HomeAssistant,
    mock_api,
    config_entry,
    api_data,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for hour in api_data["forecast"]["series"]:
        hour["models"].pop("weather_scaled", None)
    mock_api()

    with caplog.at_level(logging.WARNING):
        await setup_entry(hass, config_entry)
        coordinator = config_entry.runtime_data
        coordinator.async_add_listener(lambda: None)
        assert coordinator.data.model == "shrunk_scaled"
        assert coordinator.data.model_fallback is True

        # Two more polls: still falling back, but no new warning.
        for _ in range(2):
            freezer.tick(timedelta(minutes=31))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()

    assert coordinator.data.model_fallback is True
    warnings = [r for r in caplog.records if "weather_scaled is missing" in r.message]
    assert len(warnings) == 1


@pytest.mark.parametrize("entry_options", [{CONF_MODEL: "weather_scaled"}])
async def test_model_missing_for_single_hour(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    del api_data["forecast"]["series"][FORECAST_INDEX]["models"]["weather_scaled"]
    mock_api()

    await setup_entry(hass, config_entry)
    data = config_entry.runtime_data.data

    assert data.model == "weather_scaled"
    assert data.price_at(at("2026-09-12T00:10:00+02:00")).value is None
    assert data.price_at(at("2026-09-12T01:10:00+02:00")).value is not None


@pytest.mark.parametrize(
    "entry_options", [{CONF_UNIT: UNIT_EUR_MWH, CONF_MARKUP: 5.0, CONF_VAT: True}]
)
async def test_settings_apply_to_all_values(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    await setup_entry(hass, config_entry)
    data = config_entry.runtime_data.data

    band = api_data["forecast"]["series"][FORECAST_INDEX]["models"]["shrunk_scaled"]
    point = data.price_at(at("2026-09-12T00:10:00+02:00"))
    markup_eur = 5.0 * 10 / RATE
    assert point.value == pytest.approx((band["p50"] + markup_eur) * 1.25, abs=0.001)
    assert point.p10 == pytest.approx((band["p10"] + markup_eur) * 1.25, abs=0.001)
    assert point.p90 == pytest.approx((band["p90"] + markup_eur) * 1.25, abs=0.001)


async def test_demo_and_degraded_flags(
    hass: HomeAssistant,
    mock_api,
    config_entry,
    api_data,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_data["forecast"]["demo"] = True
    api_data["forecast"]["degraded"] = True
    api_data["forecast"]["fx"]["stale"] = True
    mock_api()

    with caplog.at_level(logging.WARNING):
        await setup_entry(hass, config_entry)
        config_entry.runtime_data.async_add_listener(lambda: None)
        freezer.tick(timedelta(minutes=31))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    forecast = config_entry.runtime_data.data.forecast
    assert forecast.demo is True
    assert forecast.degraded is True
    assert forecast.fx.stale is True
    assert len([r for r in caplog.records if "demo data" in r.message]) == 1


async def test_update_failure_keeps_entry_loaded(
    hass: HomeAssistant, mock_api, config_entry, freezer: FrozenDateTimeFactory
) -> None:
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data
    coordinator.async_add_listener(lambda: None)

    mock_api(forecast={"status": 503})
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert coordinator.last_update_success is False

    mock_api()
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert coordinator.last_update_success is True


async def test_polls_every_30_minutes(
    hass: HomeAssistant,
    mock_api,
    config_entry,
    aioclient_mock,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)
    # The coordinator only polls while something listens; entities do that.
    config_entry.runtime_data.async_add_listener(lambda: None)
    calls = aioclient_mock.call_count

    freezer.tick(timedelta(minutes=29))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == calls

    freezer.tick(timedelta(minutes=2))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert aioclient_mock.call_count > calls


async def test_longterm_failure_does_not_break_hourly_data(
    hass: HomeAssistant, mock_api, config_entry, freezer: FrozenDateTimeFactory
) -> None:
    mock_api(longterm={"exc": aiohttp.ClientError()})
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data
    coordinator.async_add_listener(lambda: None)
    assert coordinator.last_update_success is True
    assert coordinator.data.longterm is None
    assert coordinator.data.next_month() is None

    mock_api()
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert coordinator.data.next_month().month == "2026-10"

    # A later failure keeps the long-term data it already has.
    mock_api(longterm={"status": 500})
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert coordinator.last_update_success is True
    assert coordinator.data.next_month().month == "2026-10"


async def test_listeners_are_told_when_the_hour_changes(
    hass: HomeAssistant, mock_api, config_entry, freezer: FrozenDateTimeFactory
) -> None:
    # Start at 16:45 so the next 30-minute poll (17:15) does not coincide
    # with the hour change being tested.
    freezer.move_to("2026-09-10T16:45:00+02:00")
    await setup_entry(hass, config_entry)
    coordinator = config_entry.runtime_data
    calls = []
    coordinator.async_add_listener(lambda: calls.append(1))

    freezer.move_to("2026-09-10T16:59:59+02:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls == []

    freezer.move_to("2026-09-10T17:00:00+02:00")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert calls == [1]
