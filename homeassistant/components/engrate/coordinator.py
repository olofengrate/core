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


def _month_start_local() -> datetime:
    """Return the 1st of the current month in the local timezone."""
    now = dt_util.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _build_quarter_hourly_series(
    stats: list[dict[str, Any]],
    value_key: str,
    period_start: datetime,
    period_end: datetime,
    *,
    divide: bool = False,
) -> list[dict[str, Any]]:
    """Build a complete quarter-hourly time series from hourly stats.

    Generates data points for every hour in the period. Hours missing
    from the recorder data are filled with 0.
    For energy/change values (divide=True), each hourly value is split
    into 4 equal quarter-hourly values.
    For price/mean values (divide=False), the value is replicated 4 times.
    """
    # Index stats by start timestamp for fast lookup
    stats_by_hour: dict[float, float] = {}
    for row in stats:
        value = row.get(value_key)
        if value is not None:
            stats_by_hour[row["start"]] = value

    quarter_hourly: list[dict[str, Any]] = []
    start_utc = dt_util.as_utc(period_start)
    end_utc = dt_util.as_utc(period_end)
    current = start_utc.replace(minute=0, second=0, microsecond=0)

    while current < end_utc:
        hourly_value = stats_by_hour.get(current.timestamp(), 0.0)
        qh_value = hourly_value / 4 if divide else hourly_value
        quarter_hourly.extend(
            {
                "timestamp": (current + timedelta(minutes=offset_min)).isoformat(),
                "value": qh_value,
            }
            for offset_min in (0, 15, 30, 45)
        )
        current += timedelta(hours=1)

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

        now = dt_util.now()
        period_start = _month_start_local()
        period_end = now

        grid_cost = await self._calculate_grid_cost(
            tariff_id,
            configured_datasets,
            period_start,
            period_end,
        )

        last_calculated = dt_util.utcnow()

        LOGGER.debug(
            "Update complete: grid_cost=%s, period=%s to %s",
            grid_cost,
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

    async def _calculate_grid_cost(
        self,
        tariff_id: str,
        configured_datasets: dict[str, str],
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
            is_price = dataset_name in ENERGY_COST_DATASET_IDS
            stat_type = "mean" if is_price else "change"
            rows = await self._query_stats(
                entity_id, period_start, period_end, {stat_type}
            )

            data_points = _build_quarter_hourly_series(
                rows, stat_type, period_start, period_end, divide=not is_price
            )
            api_datasets.append({"name": dataset_name, "data": data_points})

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
