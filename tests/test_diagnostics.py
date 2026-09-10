"""Tests for diagnostics."""

from __future__ import annotations

import json

from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import JSONEncoder
import pytest

from custom_components.spotprognos.const import CONF_MODEL, CONF_ZONE
from custom_components.spotprognos.diagnostics import async_get_config_entry_diagnostics

from .conftest import setup_entry


async def test_diagnostics(hass: HomeAssistant, mock_api, config_entry) -> None:
    await setup_entry(hass, config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    # Must be serializable, since it is downloaded as a JSON file.
    json.dumps(diagnostics, cls=JSONEncoder)
    assert diagnostics["entry"]["data"] == {CONF_ZONE: "SE3"}
    assert diagnostics["entry"]["options"] == dict(config_entry.options)
    assert diagnostics["last_update_success"] is True
    assert diagnostics["model"] == {
        "configured": "follow_default",
        "used": "shrunk_scaled",
        "fallback": False,
    }
    forecast = diagnostics["forecast"]
    assert forecast["generated_at"] == "2026-09-10T15:31:32+02:00"
    assert forecast["run_id"] == "20260910T1331Z"
    assert forecast["degraded"] is False
    assert forecast["demo"] is False
    assert forecast["default_model"] == "shrunk_scaled"
    assert forecast["fx"]["rate"] == 11.1495
    assert forecast["fx"]["stale"] is False
    assert forecast["hours"] == 207
    assert forecast["official_hours"] == 72
    assert diagnostics["longterm"]["next_month"] == "2026-10"


@pytest.mark.parametrize("entry_options", [{CONF_MODEL: "weather_scaled"}])
async def test_diagnostics_show_model_fallback(
    hass: HomeAssistant, mock_api, config_entry, api_data
) -> None:
    for hour in api_data["forecast"]["series"]:
        hour["models"].pop("weather_scaled", None)
    api_data["forecast"]["degraded"] = True
    mock_api()
    await setup_entry(hass, config_entry)

    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["model"] == {
        "configured": "weather_scaled",
        "used": "shrunk_scaled",
        "fallback": True,
    }
    assert diagnostics["forecast"]["degraded"] is True
