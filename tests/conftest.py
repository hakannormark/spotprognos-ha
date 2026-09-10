"""Shared fixtures for the Spotprognos tests.

Nothing here touches the network: every request goes to aioclient_mock, which
serves the real files saved in tests/fixtures/.
"""

from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.spotprognos.api import DEFAULT_BASE_URL
from custom_components.spotprognos.const import (
    CONF_MARKUP,
    CONF_MODEL,
    CONF_UNIT,
    CONF_VAT,
    CONF_ZONE,
    DOMAIN,
    MODEL_FOLLOW_DEFAULT,
    UNIT_ORE_KWH,
)

from . import load_json

FORECAST_URL = f"{DEFAULT_BASE_URL}zones/SE3/forecast.json"
MODELS_URL = f"{DEFAULT_BASE_URL}models.json"
LONGTERM_URL = f"{DEFAULT_BASE_URL}longterm.json"

# The fixture is from the 13:30 run on 2026-09-10: official prices through
# 2026-09-11, forecast from 2026-09-12.
NOW = "2026-09-10T16:30:00+02:00"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load integrations from custom_components/."""
    return


@pytest.fixture(autouse=True)
async def swedish_time(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Run every test in Swedish time on the afternoon the fixture was fetched."""
    await hass.config.async_set_time_zone("Europe/Stockholm")
    freezer.move_to(NOW)


@pytest.fixture
def api_data() -> dict[str, dict[str, Any]]:
    """Return mutable copies of the fixture files, keyed by file."""
    return {
        "forecast": load_json("forecast_SE3.json"),
        "models": load_json("models.json"),
        "longterm": load_json("longterm.json"),
    }


@pytest.fixture
def mock_api(
    aioclient_mock: AiohttpClientMocker, api_data: dict[str, dict[str, Any]]
) -> Callable[..., None]:
    """Serve api_data. Call again after changing api_data to re-register.

    Keyword arguments replace a file's response, e.g.
    ``mock_api(forecast={"status": 500})``.
    """

    def register(**overrides: dict[str, Any]) -> None:
        aioclient_mock.clear_requests()
        for key, url in (
            ("forecast", FORECAST_URL),
            ("models", MODELS_URL),
            ("longterm", LONGTERM_URL),
        ):
            response = overrides.get(key) or {"text": json.dumps(api_data[key])}
            aioclient_mock.get(url, **response)

    register()
    return register


@pytest.fixture
def entry_options() -> dict[str, Any]:
    """Return the options the config entry is created with."""
    return {
        CONF_MODEL: MODEL_FOLLOW_DEFAULT,
        CONF_UNIT: UNIT_ORE_KWH,
        CONF_MARKUP: 0.0,
        CONF_VAT: False,
    }


@pytest.fixture
def config_entry(hass: HomeAssistant, entry_options: dict[str, Any]) -> MockConfigEntry:
    """Return a config entry for SE3, added to hass but not set up."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Spotprognos SE3",
        data={CONF_ZONE: "SE3"},
        options=entry_options,
        unique_id="SE3",
    )
    entry.add_to_hass(hass)
    return entry


async def setup_entry(hass: HomeAssistant, entry: MockConfigEntry) -> bool:
    """Set up the entry and wait for everything to settle."""
    result = await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return result
