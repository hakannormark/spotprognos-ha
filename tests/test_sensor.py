"""Tests for the price sensors."""

from __future__ import annotations

from datetime import datetime, timedelta

from freezegun.api import FrozenDateTimeFactory
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import device_registry as dr, entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.spotprognos.const import (
    CONF_MARKUP,
    CONF_UNIT,
    CONF_VAT,
    DOMAIN,
    UNIT_EUR_MWH,
    UNIT_ORE_KWH,
)
from custom_components.spotprognos.sensor import (
    LIST_ATTRIBUTES,
    SpotprognosForecastSensor,
    hours_in_day,
)

from .conftest import setup_entry

RATE = 11.1495
# Indices into series[]: 0-23 is 2026-09-09, 24-47 today (2026-09-10),
# 48-71 tomorrow (official in the fixture), 72- forecast only.
TODAY = range(24, 48)
TOMORROW = range(48, 72)
NOW_INDEX = 40  # 16:00


def ore(eur: float) -> float:
    return round(eur * RATE / 10, 3)


def get_state(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> State:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id, key
    state = hass.states.get(entity_id)
    assert state, entity_id
    return state


async def move_to(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, when: str
) -> None:
    freezer.move_to(when)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def test_entities_and_device(hass: HomeAssistant, mock_api, config_entry) -> None:
    await setup_entry(hass, config_entry)

    entities = er.async_entries_for_config_entry(
        er.async_get(hass), config_entry.entry_id
    )
    assert {
        e.unique_id.removeprefix(f"{config_entry.entry_id}_") for e in entities
    } == {
        "current_price",
        "next_hour_price",
        "today_min",
        "today_average",
        "today_max",
        "tomorrow_min",
        "tomorrow_average",
        "tomorrow_max",
        "cheapest_3h",
        "forecast",
    }
    devices = dr.async_entries_for_config_entry(
        dr.async_get(hass), config_entry.entry_id
    )
    assert len(devices) == 1
    device = devices[0]
    assert device.identifiers == {(DOMAIN, config_entry.entry_id)}
    assert device.name == "Spotprognos SE3"
    assert device.entry_type is dr.DeviceEntryType.SERVICE
    assert hass.states.get("sensor.spotprognos_se3_current_price") is not None


async def test_current_and_next_hour(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    await setup_entry(hass, config_entry)
    series = api_data["forecast"]["series"]

    current = get_state(hass, config_entry, "current_price")
    assert float(current.state) == pytest.approx(ore(series[NOW_INDEX]["actual"]))
    assert current.attributes[ATTR_UNIT_OF_MEASUREMENT] == UNIT_ORE_KWH
    assert current.attributes["source"] == "official"
    assert current.attributes["p10"] is None
    assert current.attributes["model"] == "shrunk_scaled"
    assert current.attributes["fx_rate"] == RATE
    assert current.attributes["fx_stale"] is False

    nxt = get_state(hass, config_entry, "next_hour_price")
    assert float(nxt.state) == pytest.approx(ore(series[NOW_INDEX + 1]["actual"]))


async def test_current_price_without_actual(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    hour = api_data["forecast"]["series"][NOW_INDEX]
    hour["actual"] = None
    hour["source"] = "forecast"
    mock_api()

    await setup_entry(hass, config_entry)

    current = get_state(hass, config_entry, "current_price")
    band = hour["models"]["shrunk_scaled"]
    assert float(current.state) == pytest.approx(ore(band["p50"]))
    assert current.attributes["source"] == "forecast"
    assert current.attributes["p10"] == pytest.approx(ore(band["p10"]))
    assert current.attributes["p90"] == pytest.approx(ore(band["p90"]))


async def test_today_statistics(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    await setup_entry(hass, config_entry)
    values = [ore(api_data["forecast"]["series"][i]["actual"]) for i in TODAY]

    assert float(get_state(hass, config_entry, "today_min").state) == pytest.approx(
        min(values)
    )
    assert float(get_state(hass, config_entry, "today_max").state) == pytest.approx(
        max(values)
    )
    assert float(get_state(hass, config_entry, "today_average").state) == pytest.approx(
        sum(values) / 24, abs=0.001
    )


async def test_tomorrow_statistics(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    await setup_entry(hass, config_entry)
    values = [ore(api_data["forecast"]["series"][i]["actual"]) for i in TOMORROW]

    assert float(get_state(hass, config_entry, "tomorrow_min").state) == pytest.approx(
        min(values)
    )
    assert float(get_state(hass, config_entry, "tomorrow_max").state) == pytest.approx(
        max(values)
    )
    assert float(
        get_state(hass, config_entry, "tomorrow_average").state
    ) == pytest.approx(sum(values) / 24, abs=0.001)


async def test_tomorrow_missing(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    # As before the auction: tomorrow only has forecasts.
    for i in TOMORROW:
        api_data["forecast"]["series"][i]["actual"] = None
        api_data["forecast"]["series"][i]["source"] = "forecast"
    mock_api()

    await setup_entry(hass, config_entry)

    for key in ("tomorrow_min", "tomorrow_average", "tomorrow_max"):
        assert get_state(hass, config_entry, key).state == STATE_UNAVAILABLE
    forecast = get_state(hass, config_entry, "forecast")
    assert forecast.attributes["tomorrow_valid"] is False
    assert forecast.attributes["raw_tomorrow"] == []
    assert forecast.attributes["tomorrow"] == []
    # The forecast list still covers tomorrow.
    tomorrow_hours = [
        h
        for h in forecast.attributes["forecast"]
        if h["start"].date().isoformat() == "2026-09-11"
    ]
    assert len(tomorrow_hours) == 24
    assert {h["source"] for h in tomorrow_hours} == {"forecast"}
    assert all(h["p10"] is not None for h in tomorrow_hours)


async def test_tomorrow_partly_published_is_not_valid(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    hour = api_data["forecast"]["series"][TOMORROW[-1]]
    hour["actual"] = None
    hour["source"] = "forecast"
    mock_api()

    await setup_entry(hass, config_entry)

    assert get_state(hass, config_entry, "tomorrow_max").state == STATE_UNAVAILABLE
    assert (
        get_state(hass, config_entry, "forecast").attributes["tomorrow_valid"] is False
    )


async def test_hour_change(
    hass: HomeAssistant,
    mock_api,
    config_entry,
    api_data,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)
    series = api_data["forecast"]["series"]

    await move_to(hass, freezer, "2026-09-10T16:59:59+02:00")
    assert float(get_state(hass, config_entry, "current_price").state) == pytest.approx(
        ore(series[NOW_INDEX]["actual"])
    )

    await move_to(hass, freezer, "2026-09-10T17:00:00+02:00")
    assert float(get_state(hass, config_entry, "current_price").state) == pytest.approx(
        ore(series[NOW_INDEX + 1]["actual"])
    )
    assert float(
        get_state(hass, config_entry, "next_hour_price").state
    ) == pytest.approx(ore(series[NOW_INDEX + 2]["actual"]))


async def test_day_change(
    hass: HomeAssistant,
    mock_api,
    config_entry,
    api_data,
    freezer: FrozenDateTimeFactory,
) -> None:
    await setup_entry(hass, config_entry)
    series = api_data["forecast"]["series"]

    # Midnight: the fixture's tomorrow becomes today, and the new tomorrow
    # (2026-09-12) only has forecasts.
    await move_to(hass, freezer, "2026-09-11T00:00:00+02:00")

    values = [ore(series[i]["actual"]) for i in TOMORROW]
    assert float(get_state(hass, config_entry, "today_min").state) == pytest.approx(
        min(values)
    )
    assert float(get_state(hass, config_entry, "current_price").state) == pytest.approx(
        values[0]
    )
    assert get_state(hass, config_entry, "tomorrow_min").state == STATE_UNAVAILABLE
    forecast = get_state(hass, config_entry, "forecast")
    assert forecast.attributes["raw_today"][0]["start"] == datetime.fromisoformat(
        "2026-09-11T00:00:00+02:00"
    )


async def test_cheapest_three_hours(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    series = api_data["forecast"]["series"]
    for i in TODAY:
        series[i]["actual"] = 100.0
    # Cheapest run: 02:00-05:00.
    for i in (26, 27, 28):
        series[i]["actual"] = 10.0
    # Two very cheap hours that are not consecutive must not win.
    series[34]["actual"] = 0.0
    series[36]["actual"] = 0.0
    mock_api()

    await setup_entry(hass, config_entry)

    state = get_state(hass, config_entry, "cheapest_3h")
    assert datetime.fromisoformat(state.state) == datetime.fromisoformat(
        "2026-09-10T02:00:00+02:00"
    )
    assert state.attributes["end"] == datetime.fromisoformat(
        "2026-09-10T05:00:00+02:00"
    )
    assert state.attributes["average"] == pytest.approx(ore(10.0), abs=0.001)
    assert ATTR_UNIT_OF_MEASUREMENT not in state.attributes


async def test_forecast_sensor_attributes(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    await setup_entry(hass, config_entry)
    series = api_data["forecast"]["series"]

    state = get_state(hass, config_entry, "forecast")
    attrs = state.attributes
    assert float(state.state) == pytest.approx(ore(series[NOW_INDEX]["actual"]))

    # Same shape as the Nord Pool integration, which EV Smart Charging and
    # ApexCharts read: start/end as datetimes with time zone, value as float.
    raw_today = attrs["raw_today"]
    assert len(raw_today) == 24
    assert set(raw_today[0]) == {"start", "end", "value"}
    assert raw_today[0]["start"] == datetime.fromisoformat("2026-09-10T00:00:00+02:00")
    assert raw_today[0]["end"] == datetime.fromisoformat("2026-09-10T01:00:00+02:00")
    assert raw_today[0]["start"].tzinfo is not None
    assert attrs["today"] == [h["value"] for h in raw_today]
    assert attrs["today"][16] == pytest.approx(ore(series[NOW_INDEX]["actual"]))
    assert len(attrs["raw_tomorrow"]) == 24
    assert len(attrs["tomorrow"]) == 24
    assert attrs["tomorrow_valid"] is True

    forecast = attrs["forecast"]
    assert forecast[0]["start"] == datetime.fromisoformat("2026-09-10T16:00:00+02:00")
    assert forecast[-1]["start"] == datetime.fromisoformat(series[-1]["ts"])
    assert len(forecast) == len(series) - NOW_INDEX
    assert set(forecast[0]) == {"start", "end", "value", "p10", "p90", "source"}
    later = forecast[72 - NOW_INDEX]
    band = series[72]["models"]["shrunk_scaled"]
    assert later["source"] == "forecast"
    assert later["value"] == pytest.approx(ore(band["p50"]))
    assert later["p10"] == pytest.approx(ore(band["p10"]))
    assert later["p90"] == pytest.approx(ore(band["p90"]))

    assert attrs["model"] == "shrunk_scaled"
    assert attrs["unit"] == UNIT_ORE_KWH


def test_list_attributes_are_not_recorded() -> None:
    assert {
        "raw_today",
        "raw_tomorrow",
        "today",
        "tomorrow",
        "forecast",
    } == LIST_ATTRIBUTES
    assert SpotprognosForecastSensor._unrecorded_attributes == LIST_ATTRIBUTES


@pytest.mark.parametrize(
    "entry_options", [{CONF_UNIT: UNIT_EUR_MWH, CONF_MARKUP: 5.0, CONF_VAT: True}]
)
async def test_unit_markup_and_vat(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    await setup_entry(hass, config_entry)
    actual = api_data["forecast"]["series"][NOW_INDEX]["actual"]

    state = get_state(hass, config_entry, "current_price")
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == UNIT_EUR_MWH
    assert float(state.state) == pytest.approx(
        (actual + 5.0 * 10 / RATE) * 1.25, abs=0.001
    )


@pytest.mark.parametrize("entry_options", [{CONF_MARKUP: 5.0, CONF_VAT: True}])
async def test_markup_and_vat_in_ore(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    await setup_entry(hass, config_entry)
    actual = api_data["forecast"]["series"][NOW_INDEX]["actual"]

    state = get_state(hass, config_entry, "current_price")
    assert float(state.state) == pytest.approx(
        (actual * RATE / 10 + 5.0) * 1.25, abs=0.001
    )
    raw = get_state(hass, config_entry, "forecast").attributes["raw_today"][16]
    assert raw["value"] == pytest.approx((actual * RATE / 10 + 5.0) * 1.25, abs=0.001)


async def test_demo_data_is_unavailable(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    api_data["forecast"]["demo"] = True
    mock_api()

    await setup_entry(hass, config_entry)

    for key in ("current_price", "today_average", "cheapest_3h", "forecast"):
        assert get_state(hass, config_entry, key).state == STATE_UNAVAILABLE


async def test_update_failure_makes_sensors_unavailable(
    hass: HomeAssistant, mock_api, config_entry, freezer: FrozenDateTimeFactory
) -> None:
    await setup_entry(hass, config_entry)
    assert get_state(hass, config_entry, "current_price").state != STATE_UNAVAILABLE

    mock_api(forecast={"text": "not json"})
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert get_state(hass, config_entry, "current_price").state == STATE_UNAVAILABLE

    mock_api()
    freezer.tick(timedelta(minutes=31))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert get_state(hass, config_entry, "current_price").state != STATE_UNAVAILABLE


def test_hours_in_day_handles_dst() -> None:
    assert hours_in_day(datetime(2026, 9, 10).date()) == 24
    assert hours_in_day(datetime(2026, 3, 29).date()) == 23
    assert hours_in_day(datetime(2026, 10, 25).date()) == 25
