"""Tests for the config flow and the options flow."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.spotprognos.const import (
    CONF_MARKUP,
    CONF_MODEL,
    CONF_UNIT,
    CONF_VAT,
    CONF_ZONE,
    DOMAIN,
    MODEL_FOLLOW_DEFAULT,
    UNIT_EUR_MWH,
    UNIT_ORE_KWH,
)

from .conftest import setup_entry


def selector_options(result: dict[str, Any], field: str) -> list[dict[str, str]]:
    for key, value in result["data_schema"].schema.items():
        if key == field:
            return value.config["options"]
    raise KeyError(field)


def field_default(result: dict[str, Any], field: str) -> Any:
    for key in result["data_schema"].schema:
        if key == field:
            return key.default()
    raise KeyError(field)


async def test_user_flow_creates_entry(hass: HomeAssistant, mock_api) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {}

    zones = selector_options(result, CONF_ZONE)
    assert [z["value"] for z in zones] == ["SE1", "SE2", "SE3", "SE4"]
    assert zones[0]["label"] == "SE1 – Luleå"

    models = selector_options(result, CONF_MODEL)
    assert models[0]["value"] == MODEL_FOLLOW_DEFAULT
    assert [m["value"] for m in models[1:]] == [
        "seasonal_naive",
        "weather_scaled",
        "shrunk_scaled",
        "recency_scaled",
        "ensemble",
        "market_scaled",
    ]
    assert "(current default)" in models[3]["label"]

    assert field_default(result, CONF_MODEL) == MODEL_FOLLOW_DEFAULT
    assert field_default(result, CONF_UNIT) == UNIT_ORE_KWH
    assert field_default(result, CONF_MARKUP) == 0.0
    assert field_default(result, CONF_VAT) is False

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ZONE: "SE3",
            CONF_MODEL: "market_scaled",
            CONF_UNIT: UNIT_EUR_MWH,
            CONF_MARKUP: 4.5,
            CONF_VAT: True,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Spotprognos SE3"
    assert result["data"] == {CONF_ZONE: "SE3"}
    assert result["options"] == {
        CONF_MODEL: "market_scaled",
        CONF_UNIT: UNIT_EUR_MWH,
        CONF_MARKUP: 4.5,
        CONF_VAT: True,
    }
    entry = result["result"]
    assert entry.unique_id == "SE3"
    assert entry.state is ConfigEntryState.LOADED


async def test_user_flow_defaults(hass: HomeAssistant, mock_api) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ZONE: "SE1"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"] == {
        CONF_MODEL: MODEL_FOLLOW_DEFAULT,
        CONF_UNIT: UNIT_ORE_KWH,
        CONF_MARKUP: 0.0,
        CONF_VAT: False,
    }


async def test_swedish_labels(hass: HomeAssistant, mock_api) -> None:
    hass.config.language = "sv"
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    models = selector_options(result, CONF_MODEL)
    assert models[0]["label"] == "Följ Spotprognos standardmodell (rekommenderas)"
    assert models[3]["label"] == "Väderskalad, dämpad nivå (standard just nu)"


async def test_same_zone_cannot_be_added_twice(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ZONE: "SE3"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_other_zone_can_be_added(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ZONE: "SE4"}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert len(hass.config_entries.async_entries(DOMAIN)) == 2


async def test_model_list_unavailable(hass: HomeAssistant, mock_api) -> None:
    mock_api(models={"status": 500})

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "models_unavailable"}
    assert [m["value"] for m in selector_options(result, CONF_MODEL)] == [
        MODEL_FOLLOW_DEFAULT
    ]

    mock_api()
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ZONE: "SE3", CONF_MODEL: MODEL_FOLLOW_DEFAULT}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options_flow_changes_settings_and_reloads(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    await setup_entry(hass, config_entry)
    old_coordinator = config_entry.runtime_data

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert CONF_ZONE not in [str(key) for key in result["data_schema"].schema]
    assert field_default(result, CONF_MODEL) == MODEL_FOLLOW_DEFAULT

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_MODEL: "weather_scaled",
            CONF_UNIT: UNIT_EUR_MWH,
            CONF_MARKUP: 6.25,
            CONF_VAT: True,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {
        CONF_MODEL: "weather_scaled",
        CONF_UNIT: UNIT_EUR_MWH,
        CONF_MARKUP: 6.25,
        CONF_VAT: True,
    }
    assert config_entry.data == {CONF_ZONE: "SE3"}
    # The entry was reloaded, so a new coordinator uses the new settings.
    assert config_entry.state is ConfigEntryState.LOADED
    coordinator = config_entry.runtime_data
    assert coordinator is not old_coordinator
    assert coordinator.data.model == "weather_scaled"
    assert coordinator.settings.unit == UNIT_EUR_MWH
    assert coordinator.settings.markup == 6.25
    assert coordinator.settings.vat is True


@pytest.mark.parametrize(
    "entry_options",
    [
        {
            CONF_MODEL: "retired_model",
            CONF_UNIT: UNIT_ORE_KWH,
            CONF_MARKUP: 0.0,
            CONF_VAT: False,
        }
    ],
)
async def test_options_flow_keeps_retired_model_selectable(
    hass: HomeAssistant, mock_api, config_entry
) -> None:
    await setup_entry(hass, config_entry)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    values = [m["value"] for m in selector_options(result, CONF_MODEL)]
    assert "retired_model" in values
    assert field_default(result, CONF_MODEL) == "retired_model"
