"""Config and options flow for Spotprognos."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .api import SpotprognosClient, SpotprognosError
from .const import (
    CONF_MARKUP,
    CONF_MODEL,
    CONF_UNIT,
    CONF_VAT,
    CONF_ZONE,
    DEFAULT_MARKUP,
    DEFAULT_MODEL,
    DEFAULT_UNIT,
    DEFAULT_VAT,
    DOMAIN,
    LOGGER,
    MODEL_FOLLOW_DEFAULT,
    UNIT_ORE_KWH,
    UNITS,
    ZONES,
)

ERROR_MODELS_UNAVAILABLE = "models_unavailable"


async def _async_model_options(
    hass: HomeAssistant, current: str | None = None
) -> tuple[list[SelectOptionDict], bool]:
    """Build the model choices from models.json.

    Returns the options and whether models.json could be fetched. If it
    could not, only "follow the default model" is offered, which is always a
    valid choice.
    """
    swedish = hass.config.language.startswith("sv")
    options = [
        SelectOptionDict(
            value=MODEL_FOLLOW_DEFAULT,
            label="Följ Spotprognos standardmodell (rekommenderas)"
            if swedish
            else "Follow the Spotprognos default model (recommended)",
        )
    ]
    try:
        catalog = await SpotprognosClient(
            async_get_clientsession(hass)
        ).async_get_models()
    except SpotprognosError as err:
        LOGGER.warning("Could not fetch the Spotprognos model list: %s", err)
        available = False
        known: set[str] = set()
    else:
        available = True
        known = {model.id for model in catalog.models}
        for model in catalog.models:
            label = model.name_sv
            if model.id == catalog.default_model:
                label += " (standard just nu)" if swedish else " (current default)"
            options.append(SelectOptionDict(value=model.id, label=label))

    # Keep a previously chosen model selectable even if it is gone from the
    # list, so the form does not silently change it.
    if current and current != MODEL_FOLLOW_DEFAULT and current not in known:
        options.append(SelectOptionDict(value=current, label=current))
    return options, available


def _settings_schema(
    model_options: list[SelectOptionDict], defaults: dict[str, Any]
) -> dict[vol.Marker, Any]:
    """Return the fields shared by the config flow and the options flow."""
    return {
        vol.Required(
            CONF_MODEL, default=defaults.get(CONF_MODEL, DEFAULT_MODEL)
        ): SelectSelector(
            SelectSelectorConfig(
                options=model_options, mode=SelectSelectorMode.DROPDOWN
            )
        ),
        vol.Required(
            CONF_UNIT, default=defaults.get(CONF_UNIT, DEFAULT_UNIT)
        ): SelectSelector(
            SelectSelectorConfig(options=list(UNITS), mode=SelectSelectorMode.LIST)
        ),
        vol.Required(
            CONF_MARKUP, default=defaults.get(CONF_MARKUP, DEFAULT_MARKUP)
        ): NumberSelector(
            NumberSelectorConfig(
                min=0,
                max=1000,
                step=0.01,
                unit_of_measurement=UNIT_ORE_KWH,
                mode=NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_VAT, default=defaults.get(CONF_VAT, DEFAULT_VAT)
        ): BooleanSelector(),
    }


def _settings(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_MODEL: user_input[CONF_MODEL],
        CONF_UNIT: user_input[CONF_UNIT],
        CONF_MARKUP: float(user_input[CONF_MARKUP]),
        CONF_VAT: bool(user_input[CONF_VAT]),
    }


class SpotprognosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add one price zone."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> SpotprognosOptionsFlow:
        """Return the options flow."""
        return SpotprognosOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for zone, model, unit, markup and VAT."""
        if user_input is not None:
            zone = user_input[CONF_ZONE]
            await self.async_set_unique_id(zone)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Spotprognos {zone}",
                data={CONF_ZONE: zone},
                options=_settings(user_input),
            )

        model_options, available = await _async_model_options(self.hass)
        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=zone, label=f"{zone} – {name}")
                            for zone, name in ZONES.items()
                        ],
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                **_settings_schema(model_options, {}),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors={} if available else {"base": ERROR_MODELS_UNAVAILABLE},
        )


class SpotprognosOptionsFlow(OptionsFlowWithReload):
    """Change model, unit, markup and VAT without re-adding the zone."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the current settings."""
        if user_input is not None:
            return self.async_create_entry(data=_settings(user_input))

        current = dict(self.config_entry.options)
        model_options, available = await _async_model_options(
            self.hass, current.get(CONF_MODEL)
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(_settings_schema(model_options, current)),
            errors={} if available else {"base": ERROR_MODELS_UNAVAILABLE},
        )
