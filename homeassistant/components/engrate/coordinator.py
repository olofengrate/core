"""DataUpdateCoordinator for the Engrate integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import EngrateApiAuthError, EngrateApiClient, EngrateApiConnectionError
from .const import (
    CONF_DATASETS,
    CONF_ENERGY_COST_ENTITY,
    CONF_TARIFF_ID,
    DOMAIN,
    ENERGY_COST_DATASET_IDS,
    LOGGER,
)

type EngrateConfigEntry = ConfigEntry[EngrateCoordinator]


@dataclass
class EngrateTariffData:
    """Data class for Engrate tariff information."""

    tariff_id: str
    tariff_name: str
    tariff_summary: str | None
    tariff_annotations: str | None
    tariff_raw: dict[str, Any]
    system_operator_name: str | None
    system_operator_description: str | None
    system_operator_logo_url: str | None
    grid_cost: float | None
    energy_cost: float | None
    total_cost: float | None


class EngrateCoordinator(DataUpdateCoordinator[EngrateTariffData]):
    """Engrate data update coordinator."""

    config_entry: EngrateConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: EngrateConfigEntry,
        client: EngrateApiClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=timedelta(minutes=5),
        )
        self.client = client
        self._last_readings: dict[str, float] = {}
        self._accumulated_grid_cost: float = 0.0
        self._accumulated_energy_cost: float = 0.0

    def restore_costs(self, grid_cost: float, energy_cost: float) -> None:
        """Restore accumulated costs from sensor states after restart."""
        self._accumulated_grid_cost = grid_cost
        self._accumulated_energy_cost = energy_cost

    async def _async_update_data(self) -> EngrateTariffData:
        """Fetch tariff and system operator data from the Engrate API."""
        tariff_id = self.config_entry.data[CONF_TARIFF_ID]

        try:
            tariff = await self.client.async_get_tariff(tariff_id)
        except EngrateApiAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except EngrateApiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err

        system_operator = await self._resolve_system_operator(tariff)

        # Calculate grid costs using configured dataset entities
        configured_datasets: dict[str, str] = self.config_entry.data.get(
            CONF_DATASETS, {}
        )
        energy_cost_entity_id = self.config_entry.data[CONF_ENERGY_COST_ENTITY]
        grid_cost = await self._calculate_grid_cost(
            tariff_id, configured_datasets, tariff
        )
        energy_cost = self._calculate_energy_cost(
            configured_datasets, energy_cost_entity_id
        )

        LOGGER.debug(
            "Update complete: grid_cost=%s, energy_cost=%s, last_readings=%s",
            grid_cost,
            energy_cost,
            self._last_readings,
        )

        # Compute total cost (grid + energy) when both are available
        total_cost: float | None = None
        if grid_cost is not None or energy_cost is not None:
            total_cost = (grid_cost or 0.0) + (energy_cost or 0.0)

        return EngrateTariffData(
            tariff_id=tariff["id"],
            tariff_name=tariff["name"],
            tariff_summary=tariff.get("summary"),
            tariff_annotations=tariff.get("annotations"),
            tariff_raw=tariff,
            system_operator_name=system_operator.get("name")
            if system_operator
            else None,
            system_operator_description=system_operator.get("description")
            if system_operator
            else None,
            system_operator_logo_url=system_operator.get("logo_url")
            if system_operator
            else None,
            grid_cost=grid_cost,
            energy_cost=energy_cost,
            total_cost=total_cost,
        )

    def _read_energy_cost_price(self, entity_id: str | None) -> float | None:
        """Read the current energy cost price from a sensor entity."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except ValueError, TypeError:
            return None

    def _calculate_energy_cost(
        self,
        configured_datasets: dict[str, str],
        energy_cost_entity_id: str,
    ) -> float | None:
        """Calculate energy cost from energy price × consumption delta.

        Uses the energy cost entity price and the offtake delta to compute
        the energy cost for the period.
        """

        price = self._read_energy_cost_price(energy_cost_entity_id)
        if price is None:
            return self._accumulated_energy_cost or None

        # Find the offtake entity to get consumption delta
        offtake_entity_id = configured_datasets.get("quarter-hourly-energy-offtake")
        if not offtake_entity_id:
            return self._accumulated_energy_cost or None

        state = self.hass.states.get(offtake_entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return self._accumulated_energy_cost or None

        try:
            current_reading = float(state.state)
        except ValueError, TypeError:
            return self._accumulated_energy_cost or None

        key = "__energy_cost_offtake"
        last = self._last_readings.get(key)
        self._last_readings[key] = current_reading

        if last is None:
            return self._accumulated_energy_cost or None

        delta = current_reading - last
        if delta <= 0:
            return self._accumulated_energy_cost or None

        self._accumulated_energy_cost += price * delta
        return self._accumulated_energy_cost

    async def _calculate_grid_cost(
        self,
        tariff_id: str,
        configured_datasets: dict[str, str],
        tariff: dict[str, Any],
    ) -> float | None:
        """Calculate grid cost using the Engrate calculate API.

        Reads each configured dataset entity's current state, computes deltas,
        and sends them to the calculate API. Returns the accumulated grid cost,
        or None if no datasets are configured.
        """
        if not configured_datasets:
            LOGGER.debug("No configured datasets, skipping grid cost calculation")
            return None

        now = dt_util.utcnow()
        interval = self.update_interval or timedelta(minutes=5)
        start = now - interval
        start_iso = start.isoformat()
        end_iso = now.isoformat()

        api_datasets: list[dict[str, Any]] = []
        for dataset_name, entity_id in configured_datasets.items():
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable"):
                continue

            try:
                current_reading = float(state.state)
            except ValueError, TypeError:
                continue

            last = self._last_readings.get(dataset_name)
            self._last_readings[dataset_name] = current_reading

            if last is None:
                # First reading — store baseline, skip this dataset
                continue

            delta = current_reading - last
            if delta <= 0:
                continue

            api_datasets.append(
                {
                    "name": dataset_name,
                    "data": [{"timestamp": start_iso, "value": delta}],
                }
            )

        # Include energy cost price for any energy cost datasets the tariff requires
        energy_cost_entity_id = self.config_entry.data[CONF_ENERGY_COST_ENTITY]
        price = self._read_energy_cost_price(energy_cost_entity_id)
        if price is not None:
            api_datasets.extend(
                {
                    "name": ds["id"],
                    "data": [{"timestamp": start_iso, "value": price}],
                }
                for component in tariff.get("tariff_components", [])
                for ds in component.get("datasets", [])
                if ds["id"] in ENERGY_COST_DATASET_IDS
            )

        if not api_datasets:
            return self._accumulated_grid_cost or None

        try:
            components = await self.client.async_calculate_tariff(
                tariff_id=tariff_id,
                start_time=start_iso,
                end_time=end_iso,
                datasets=api_datasets,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning("Failed to calculate tariff costs")
            return self._accumulated_grid_cost

        # Sum all cost values across all components
        period_cost = 0.0
        for component in components:
            for dataset in component.get("datasets", []):
                if dataset.get("name") == "cost":
                    for point in dataset.get("data", []):
                        period_cost += point.get("value", 0.0)

        self._accumulated_grid_cost += period_cost
        return self._accumulated_grid_cost

    async def _resolve_system_operator(
        self, tariff: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Resolve system operator from tariff data."""
        try:
            return await self.client.async_resolve_system_operator(tariff)
        except Exception:  # noqa: BLE001
            LOGGER.warning(
                "Failed to resolve system operator for tariff %s", tariff.get("id")
            )
            return None
