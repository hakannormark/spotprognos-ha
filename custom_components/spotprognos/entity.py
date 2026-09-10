"""Base entity for Spotprognos."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import ATTRIBUTION, DOMAIN, ZONES
from .coordinator import SpotprognosCoordinator


class SpotprognosEntity(CoordinatorEntity[SpotprognosCoordinator]):
    """An entity on the Spotprognos device for one price zone."""

    _attr_has_entity_name = True
    _attr_attribution = ATTRIBUTION

    def __init__(self, coordinator: SpotprognosCoordinator, key: str) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        zone = coordinator.zone
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"Spotprognos {zone}",
            manufacturer="Spotprognos",
            model=f"{zone} {ZONES.get(zone, '')}".strip(),
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://hakannormark.github.io/power-price-oracle/",
        )

    @property
    def available(self) -> bool:
        """Unavailable when the update failed or the data is synthetic demo data."""
        return (
            super().available
            and self.coordinator.data is not None
            and not self.coordinator.data.forecast.demo
        )
