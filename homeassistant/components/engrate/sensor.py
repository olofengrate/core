"""Sensor platform for the Engrate integration."""

from __future__ import annotations

import json
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EngrateConfigEntry, EngrateCoordinator

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EngrateConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Engrate sensors from a config entry."""
    async_add_entities([EngrateGridCostSensor(entry.runtime_data)])


class EngrateGridCostSensor(CoordinatorEntity[EngrateCoordinator], SensorEntity):
    """Sensor for year-to-date grid cost."""

    _attr_has_entity_name = True
    _attr_translation_key = "grid_cost"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: EngrateCoordinator) -> None:
        """Initialize the grid cost sensor."""
        super().__init__(coordinator)
        tariff_id = coordinator.config_entry.data["tariff_id"]
        self._attr_unique_id = f"{tariff_id}_grid_cost"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tariff_id)},
            name=coordinator.data.tariff_name,
            manufacturer=coordinator.data.system_operator_name,
        )

    @property
    def native_value(self) -> float | None:
        """Return the year-to-date grid cost."""
        return self.coordinator.data.grid_cost

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the currency from HA config."""
        return self.hass.config.currency

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return component cost breakdown and period metadata."""
        data = self.coordinator.data
        attrs: dict[str, Any] = {}
        if data.component_costs:
            attrs["component_costs"] = json.dumps(data.component_costs)
        if data.period_start:
            attrs["period_start"] = data.period_start.isoformat()
        if data.period_end:
            attrs["period_end"] = data.period_end.isoformat()
        if data.last_calculated:
            attrs["last_calculated"] = data.last_calculated.isoformat()
        return attrs
