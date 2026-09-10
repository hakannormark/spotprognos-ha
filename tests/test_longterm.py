"""Tests for next month's average price from longterm.json."""

from __future__ import annotations

import aiohttp
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spotprognos.const import (
    CONF_UNIT,
    DOMAIN,
    UNIT_EUR_MWH,
    UNIT_ORE_KWH,
)

from .conftest import setup_entry

RATE = 11.1495


def ore(eur: float) -> float:
    return round(eur * RATE / 10, 3)


def get_state(hass: HomeAssistant, entry: MockConfigEntry) -> State:
    entity_id = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_next_month_average"
    )
    assert entity_id
    return hass.states.get(entity_id)


def next_month(api_data) -> dict:
    month = api_data["longterm"]["zones"]["SE3"]["months"][0]
    assert month["horizon"] == 1
    return month


async def test_next_month_average(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    await setup_entry(hass, config_entry)
    month = next_month(api_data)
    band = month["models"]["lt_damped"]
    market = month["models"]["lt_market"]

    state = get_state(hass, config_entry)
    assert float(state.state) == pytest.approx(ore(band["p50"]))
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == UNIT_ORE_KWH
    assert state.attributes["month"] == "2026-10"
    assert state.attributes["label"] == "oktober 2026"
    assert state.attributes["model"] == "lt_damped"
    assert state.attributes["p10"] == pytest.approx(ore(band["p10"]))
    assert state.attributes["p90"] == pytest.approx(ore(band["p90"]))
    assert state.attributes["lt_market"] == pytest.approx(ore(market["p50"]))
    assert state.attributes["lt_market_tenor"] == market["tenor"]
    assert state.attributes["last_year"] == pytest.approx(ore(month["last_year"]))


async def test_follows_longterm_default_model(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    api_data["longterm"]["default_model"] = "lt_fundamental"
    mock_api()

    await setup_entry(hass, config_entry)

    band = next_month(api_data)["models"]["lt_fundamental"]
    state = get_state(hass, config_entry)
    assert float(state.state) == pytest.approx(ore(band["p50"]))
    assert state.attributes["model"] == "lt_fundamental"
    # This model has no interval in the file.
    assert state.attributes["p10"] is None


async def test_without_futures_price(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    del next_month(api_data)["models"]["lt_market"]
    mock_api()

    await setup_entry(hass, config_entry)

    state = get_state(hass, config_entry)
    assert state.state != STATE_UNAVAILABLE
    assert state.attributes["lt_market"] is None
    assert state.attributes["lt_market_tenor"] is None


@pytest.mark.parametrize("entry_options", [{CONF_UNIT: UNIT_EUR_MWH}])
async def test_in_eur(hass: HomeAssistant, mock_api, config_entry, api_data) -> None:
    await setup_entry(hass, config_entry)

    state = get_state(hass, config_entry)
    assert state.attributes[ATTR_UNIT_OF_MEASUREMENT] == UNIT_EUR_MWH
    assert float(state.state) == pytest.approx(
        next_month(api_data)["models"]["lt_damped"]["p50"]
    )


async def test_unavailable_without_longterm(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    mock_api(longterm={"exc": aiohttp.ClientError()})

    await setup_entry(hass, config_entry)

    assert get_state(hass, config_entry).state == STATE_UNAVAILABLE


async def test_unavailable_when_zone_missing(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    del api_data["longterm"]["zones"]["SE3"]
    mock_api()

    await setup_entry(hass, config_entry)

    assert get_state(hass, config_entry).state == STATE_UNAVAILABLE
