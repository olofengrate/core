"""Sensor platform for the Engrate integration."""

from __future__ import annotations

from collections.abc import Callable

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
from .coordinator import EngrateConfigEntry, EngrateCoordinator, EngrateTariffData


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EngrateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Engrate sensor based on a config entry."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            EngrateCostSensor(coordinator, "grid_cost", lambda d: d.grid_cost),
            EngrateCostSensor(coordinator, "energy_cost", lambda d: d.energy_cost),
            EngrateCostSensor(coordinator, "total_cost", lambda d: d.total_cost),
        ]
    )


class EngrateCostSensor(CoordinatorEntity[EngrateCoordinator], SensorEntity):
    """Sensor tracking a cost value calculated by Engrate."""

    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL
    _attr_suggested_display_precision = 2
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EngrateCoordinator,
        translation_key: str,
        value_fn: Callable[[EngrateTariffData], float | None],
    ) -> None:
        """Initialize the cost sensor."""
        super().__init__(coordinator)
        self._attr_translation_key = translation_key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{translation_key}"
        self._attr_native_unit_of_measurement = coordinator.hass.config.currency
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.config_entry.entry_id)},
            name="Engrate",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._value_fn = value_fn

    @property
    def native_value(self) -> float | None:
        """Return the cost value."""
        if self.coordinator.data is None:
            return None
        return self._value_fn(self.coordinator.data)
