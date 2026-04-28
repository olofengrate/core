"""DataUpdateCoordinator for the Engrate integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import statistics_during_period
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
    last_calculated: datetime | None
    period_start: datetime | None
    period_end: datetime | None


def _compute_update_interval(entry_id: str) -> timedelta:
    """Compute a jittered update interval to avoid clock-hour spikes.

    Returns an interval between 55 and 65 minutes, determined
    by the config entry ID for consistency across restarts.
    """
    offset = hash(entry_id) % 11
    return timedelta(minutes=55 + offset)


def _year_start_local() -> datetime:
    """Return Jan 1 of the current year in the local timezone."""
    now = dt_util.now()
    return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


def _expand_hourly_to_quarter_hourly(
    stats: list[dict[str, Any]], value_key: str, *, divide: bool = False
) -> list[dict[str, Any]]:
    """Expand hourly statistics into quarter-hourly data points.

    For energy/change values, divide by 4 to distribute evenly.
    For price/mean values, replicate the same value 4 times.
    """
    quarter_hourly: list[dict[str, Any]] = []
    for row in stats:
        ts = datetime.fromtimestamp(row["start"], tz=dt_util.UTC)
        value = row.get(value_key)
        if value is None:
            continue
        qh_value = value / 4 if divide else value
        quarter_hourly.extend(
            {
                "timestamp": (ts + timedelta(minutes=offset_min)).isoformat(),
                "value": qh_value,
            }
            for offset_min in (0, 15, 30, 45)
        )
    return quarter_hourly


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
            update_interval=_compute_update_interval(config_entry.entry_id),
        )
        self.client = client

    async def _async_update_data(self) -> EngrateTariffData:
        """Fetch tariff data and calculate costs from recorder history."""
        tariff_id = self.config_entry.data[CONF_TARIFF_ID]

        try:
            tariff = await self.client.async_get_tariff(tariff_id)
        except EngrateApiAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except EngrateApiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err

        system_operator = await self._resolve_system_operator(tariff)

        configured_datasets: dict[str, str] = self.config_entry.data.get(
            CONF_DATASETS, {}
        )
        energy_cost_entity_id: str = self.config_entry.data[CONF_ENERGY_COST_ENTITY]

        now = dt_util.now()
        year_start = _year_start_local()

        # Determine the common period where all required datasets have data
        period_start, period_end = await self._find_common_period(
            configured_datasets,
            tariff,
            energy_cost_entity_id,
            year_start,
            now,
        )

        grid_cost: float | None = None
        energy_cost: float | None = None

        if period_start is not None and period_end is not None:
            grid_cost = await self._calculate_grid_cost(
                tariff_id,
                configured_datasets,
                tariff,
                energy_cost_entity_id,
                period_start,
                period_end,
            )
            energy_cost = await self._calculate_energy_cost(
                configured_datasets,
                energy_cost_entity_id,
                period_start,
                period_end,
            )

        total_cost: float | None = None
        if grid_cost is not None or energy_cost is not None:
            total_cost = (grid_cost or 0.0) + (energy_cost or 0.0)

        last_calculated = dt_util.utcnow()

        LOGGER.debug(
            "Update complete: grid_cost=%s, energy_cost=%s, total_cost=%s, "
            "period=%s to %s",
            grid_cost,
            energy_cost,
            total_cost,
            period_start.isoformat() if period_start else None,
            period_end.isoformat() if period_end else None,
        )

        return EngrateTariffData(
            tariff_id=tariff["id"],
            tariff_name=tariff["name"],
            tariff_summary=tariff.get("summary"),
            tariff_annotations=tariff.get("annotations"),
            tariff_raw=tariff,
            system_operator_name=(
                system_operator.get("name") if system_operator else None
            ),
            system_operator_description=(
                system_operator.get("description") if system_operator else None
            ),
            system_operator_logo_url=(
                system_operator.get("logo_url") if system_operator else None
            ),
            grid_cost=grid_cost,
            energy_cost=energy_cost,
            total_cost=total_cost,
            last_calculated=last_calculated,
            period_start=period_start,
            period_end=period_end,
        )

    async def _query_stats(
        self,
        entity_id: str,
        start: datetime,
        end: datetime,
        types: set[str],
    ) -> list[dict[str, Any]]:
        """Query recorder statistics for an entity over a period."""
        start_utc = dt_util.as_utc(start)
        end_utc = dt_util.as_utc(end)
        stats: dict[str, list[Any]] = await get_instance(
            self.hass
        ).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start_utc,
            end_utc,
            {entity_id},
            "hour",
            None,
            types,
        )
        return stats.get(entity_id, [])

    async def _find_common_period(
        self,
        configured_datasets: dict[str, str],
        tariff: dict[str, Any],
        energy_cost_entity_id: str,
        year_start: datetime,
        now: datetime,
    ) -> tuple[datetime | None, datetime | None]:
        """Find the period covered by all required datasets.

        Queries recorder for each required entity and returns the
        intersection: (latest first-timestamp, now). If all data exists
        from Jan 1, returns (Jan 1, now). If any dataset has no data,
        returns (None, None).
        """
        # Collect all entity IDs that must have data
        required_entity_ids: list[str] = list(configured_datasets.values())

        # Check if tariff requires spot price datasets
        energy_cost_ds_ids = {
            ds["id"]
            for component in tariff.get("tariff_components", [])
            for ds in component.get("datasets", [])
            if ds["id"] in ENERGY_COST_DATASET_IDS
        }
        if energy_cost_ds_ids:
            required_entity_ids.append(energy_cost_entity_id)

        # Also need offtake + price for energy cost calculation
        offtake_entity_id = configured_datasets.get("quarter-hourly-energy-offtake")
        if offtake_entity_id and energy_cost_entity_id not in required_entity_ids:
            required_entity_ids.append(energy_cost_entity_id)

        if not required_entity_ids:
            return None, None

        # Find the latest "first data point" across all entities
        latest_start: float = year_start.timestamp()
        for entity_id in required_entity_ids:
            rows = await self._query_stats(
                entity_id, year_start, now, {"change", "mean"}
            )
            if not rows:
                LOGGER.debug(
                    "No recorder data for %s, cannot determine period", entity_id
                )
                return None, None
            first_ts = rows[0]["start"]
            latest_start = max(latest_start, first_ts)

        period_start = datetime.fromtimestamp(latest_start, tz=year_start.tzinfo)
        return period_start, now

    async def _calculate_grid_cost(
        self,
        tariff_id: str,
        configured_datasets: dict[str, str],
        tariff: dict[str, Any],
        energy_cost_entity_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> float | None:
        """Calculate grid cost for the full period using recorder history.

        Queries hourly statistics for each configured dataset entity,
        expands to quarter-hourly intervals, and sends to the Engrate
        calculate API.
        """
        if not configured_datasets:
            LOGGER.debug("No configured datasets, skipping grid cost calculation")
            return None

        start_iso = dt_util.as_utc(period_start).isoformat()
        end_iso = dt_util.as_utc(period_end).isoformat()

        api_datasets: list[dict[str, Any]] = []

        # Build time series for each configured dataset from recorder history
        for dataset_name, entity_id in configured_datasets.items():
            rows = await self._query_stats(
                entity_id, period_start, period_end, {"change"}
            )
            if not rows:
                LOGGER.debug(
                    "No recorder stats for %s (%s), skipping",
                    dataset_name,
                    entity_id,
                )
                continue

            data_points = _expand_hourly_to_quarter_hourly(rows, "change", divide=True)
            if data_points:
                api_datasets.append({"name": dataset_name, "data": data_points})

        # Add spot price data for energy cost datasets the tariff requires
        energy_cost_ds_ids = {
            ds["id"]
            for component in tariff.get("tariff_components", [])
            for ds in component.get("datasets", [])
            if ds["id"] in ENERGY_COST_DATASET_IDS
        }
        if energy_cost_ds_ids:
            price_rows = await self._query_stats(
                energy_cost_entity_id, period_start, period_end, {"mean"}
            )
            if price_rows:
                price_points = _expand_hourly_to_quarter_hourly(
                    price_rows, "mean", divide=False
                )
                api_datasets.extend(
                    {"name": ds_id, "data": price_points}
                    for ds_id in energy_cost_ds_ids
                )

        if not api_datasets:
            LOGGER.debug("No dataset time series available for grid cost calculation")
            return None

        try:
            components = await self.client.async_calculate_tariff(
                tariff_id=tariff_id,
                start_time=start_iso,
                end_time=end_iso,
                datasets=api_datasets,
            )
        except Exception:  # noqa: BLE001
            LOGGER.warning("Failed to calculate tariff costs")
            return self.data.grid_cost if self.data else None

        # Sum all cost values across all components
        total = 0.0
        for component in components:
            for dataset in component.get("datasets", []):
                if dataset.get("name") == "cost":
                    for point in dataset.get("data", []):
                        total += point.get("value", 0.0)

        return total

    async def _calculate_energy_cost(
        self,
        configured_datasets: dict[str, str],
        energy_cost_entity_id: str,
        period_start: datetime,
        period_end: datetime,
    ) -> float | None:
        """Calculate energy cost for the full period using recorder history.

        Multiplies hourly spot price by hourly energy consumption
        for each hour in the period.
        """
        offtake_entity_id = configured_datasets.get("quarter-hourly-energy-offtake")
        if not offtake_entity_id:
            return None

        # Query consumption deltas and spot prices from recorder
        consumption_rows = await self._query_stats(
            offtake_entity_id, period_start, period_end, {"change"}
        )
        price_rows = await self._query_stats(
            energy_cost_entity_id, period_start, period_end, {"mean"}
        )

        if not consumption_rows or not price_rows:
            return None

        # Build a lookup of hourly prices by start timestamp
        price_by_hour: dict[float, float] = {}
        for row in price_rows:
            mean = row.get("mean")
            if mean is not None:
                price_by_hour[row["start"]] = mean

        total = 0.0
        for row in consumption_rows:
            change = row.get("change")
            if change is None or change <= 0:
                continue
            price = price_by_hour.get(row["start"])
            if price is None:
                continue
            total += change * price

        return total if total > 0 else None

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
