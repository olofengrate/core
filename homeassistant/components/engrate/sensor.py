"""Sensor platform for the Engrate integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EngrateConfigEntry, EngrateCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EngrateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Engrate sensor based on a config entry."""
    coordinator = entry.runtime_data
    async_add_entities([EngrateGridCostSensor(coordinator)])


class EngrateGridCostSensor(CoordinatorEntity[EngrateCoordinator], SensorEntity):
    """Sensor tracking grid cost calculated by Engrate."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    _attr_has_entity_name = True
    _attr_translation_key = "grid_cost"

    def __init__(self, coordinator: EngrateCoordinator) -> None:
        """Initialize the grid cost sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_grid_cost"
        self._attr_native_unit_of_measurement = coordinator.hass.config.currency
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="Engrate",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> float | None:
        """Return the grid cost value."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.grid_cost

    @property
    def last_reset(self) -> datetime | None:
        """Return the start of the current calculation period (year start)."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.period_start
