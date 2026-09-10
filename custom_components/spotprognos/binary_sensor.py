"""Binary sensor for degraded Spotprognos runs."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SpotprognosConfigEntry, SpotprognosCoordinator
from .entity import SpotprognosEntity

PARALLEL_UPDATES = 0

DEGRADED = BinarySensorEntityDescription(
    key="degraded",
    translation_key="degraded",
    device_class=BinarySensorDeviceClass.PROBLEM,
    entity_category=EntityCategory.DIAGNOSTIC,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SpotprognosConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensor for one price zone."""
    async_add_entities([SpotprognosDegradedSensor(entry.runtime_data, DEGRADED)])


class SpotprognosDegradedSensor(SpotprognosEntity, BinarySensorEntity):
    """On when a source failed and parts of the file may be from an earlier run."""

    def __init__(
        self,
        coordinator: SpotprognosCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def available(self) -> bool:
        """Stay available with demo data; it says something about the run too."""
        # Skip SpotprognosEntity.available, which hides demo data.
        return (
            super(SpotprognosEntity, self).available
            and self.coordinator.data is not None
        )

    @property
    def is_on(self) -> bool:
        """Return True if the latest run is degraded."""
        return self.coordinator.data.forecast.degraded

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return which run the file comes from."""
        forecast = self.coordinator.data.forecast
        return {
            "run_id": forecast.run_id,
            "generated_at": forecast.generated_at,
            "demo": forecast.demo,
            "fx_stale": forecast.fx.stale,
        }
