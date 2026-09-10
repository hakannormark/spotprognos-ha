"""Tests for the degraded-run binary sensor."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, EntityCategory
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.spotprognos.const import DOMAIN

from .conftest import setup_entry


def get_state(
    hass: HomeAssistant, entry: MockConfigEntry, platform: str, key: str
) -> State:
    entity_id = er.async_get(hass).async_get_entity_id(
        platform, DOMAIN, f"{entry.entry_id}_{key}"
    )
    assert entity_id, key
    return hass.states.get(entity_id)


async def test_normal_run_is_off(hass: HomeAssistant, mock_api, config_entry) -> None:
    await setup_entry(hass, config_entry)

    state = get_state(hass, config_entry, "binary_sensor", "degraded")
    assert state.state == STATE_OFF
    assert state.attributes["device_class"] == "problem"
    assert state.attributes["run_id"] == "20260910T1331Z"
    entry = er.async_get(hass).async_get(state.entity_id)
    assert entry.entity_category is EntityCategory.DIAGNOSTIC


async def test_degraded_run_is_on(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    api_data["forecast"]["degraded"] = True
    mock_api()

    await setup_entry(hass, config_entry)

    assert get_state(hass, config_entry, "binary_sensor", "degraded").state == STATE_ON
    # Degraded data is still shown; it is flagged, not hidden.
    assert (
        get_state(hass, config_entry, "sensor", "current_price").state
        != STATE_UNAVAILABLE
    )


async def test_available_with_demo_data(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    api_data["forecast"]["demo"] = True
    api_data["forecast"]["degraded"] = True
    mock_api()

    await setup_entry(hass, config_entry)

    state = get_state(hass, config_entry, "binary_sensor", "degraded")
    assert state.state == STATE_ON
    assert state.attributes["demo"] is True
    assert (
        get_state(hass, config_entry, "sensor", "current_price").state
        == STATE_UNAVAILABLE
    )
