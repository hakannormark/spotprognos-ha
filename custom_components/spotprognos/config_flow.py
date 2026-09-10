"""Config flow for Spotprognos."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .const import CONF_ZONE, DOMAIN, ZONES


class SpotprognosConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Spotprognos."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a price zone."""
        if user_input is not None:
            zone = user_input[CONF_ZONE]
            await self.async_set_unique_id(zone)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Spotprognos {zone}", data={CONF_ZONE: zone}
            )

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
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
