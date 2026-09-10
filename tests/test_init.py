"""Tests for setting up and unloading the integration."""

from __future__ import annotations

import aiohttp
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .conftest import setup_entry


async def test_setup_and_unload(hass: HomeAssistant, mock_api, config_entry) -> None:
    assert await setup_entry(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.data.forecast.zone == "SE3"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_api_is_down(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    mock_api(forecast={"exc": aiohttp.ClientError()})

    await setup_entry(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_setup_retries_on_broken_json(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    mock_api(forecast={"text": '{"series": ['})

    await setup_entry(hass, config_entry)

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
