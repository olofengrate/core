"""DataUpdateCoordinator for the Engrate integration."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import UNDEFINED, UndefinedType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util, slugify

from .api import EngrateApiAuthError, EngrateApiClient, EngrateApiConnectionError
from .const import CONF_DATASETS, CONF_TARIFF_ID, DOMAIN, LOGGER, PRICE_DATASET_IDS

type EngrateConfigEntry = ConfigEntry[EngrateCoordinator]


@dataclass
class EngrateTariffData:
    """Data class for Engrate tariff information."""

    tariff_id: str
    tariff_name: str
    tariff_raw: dict[str, Any]
    system_operator_name: str | None
    grid_cost: float | None
    component_costs: list[dict[str, Any]]
    last_calculated: datetime | None
    period_start: datetime | None
    period_end: datetime | None
    statistic_id: str


def _compute_update_interval(entry_id: str) -> timedelta:
    """Compute a jittered update interval to avoid clock-hour spikes.

    Returns an interval between 55 and 65 minutes, determined
    by the config entry ID for consistency across restarts.
    """
    offset = int.from_bytes(entry_id[:4].encode(), "big") % 11
    return timedelta(minutes=55 + offset)


def _year_start_local() -> datetime:
    """Return January 1st of the current year in the local timezone."""
    now = dt_util.now()
    return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)


class DatasetResolution(StrEnum):
    """Resolution of an Engrate dataset."""

    QUARTER_HOURLY = "quarter_hourly"
    HOURLY = "hourly"
    YEARLY = "yearly"


def _parse_resolution(dataset_name: str) -> DatasetResolution:
    """Parse the resolution from a dataset ID prefix.

    Dataset IDs follow the pattern: {resolution}-{description}
    where resolution is 'quarter-hourly', 'hourly', or 'yearly'.

    Raises UpdateFailed if the prefix is unrecognized.
    """
    if dataset_name.startswith("quarter-hourly-"):
        return DatasetResolution.QUARTER_HOURLY
    if dataset_name.startswith("hourly-"):
        return DatasetResolution.HOURLY
    if dataset_name.startswith("yearly-"):
        return DatasetResolution.YEARLY
    raise UpdateFailed(f"Unknown dataset resolution prefix for '{dataset_name}'")


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


def _build_hourly_series(
    stats: list[dict[str, Any]],
    period_start: datetime,
    period_end: datetime,
) -> list[dict[str, Any]]:
    """Build an hourly time series from hourly recorder stats.

    Uses the 'mean' value from each hour. Missing hours are filled with 0.
    """
    stats_by_hour: dict[float, float] = {}
    for row in stats:
        value = row.get("mean")
        if value is not None:
            stats_by_hour[row["start"]] = value

    hourly: list[dict[str, Any]] = []
    start_utc = dt_util.as_utc(period_start)
    end_utc = dt_util.as_utc(period_end)
    current = start_utc.replace(minute=0, second=0, microsecond=0)

    while current < end_utc:
        hourly.append(
            {
                "timestamp": current.isoformat(),
                "value": stats_by_hour.get(current.timestamp(), 0.0),
            }
        )
        current += timedelta(hours=1)

    return hourly


def _aggregate_hourly_costs(
    components: list[dict[str, Any]],
) -> dict[datetime, float]:
    """Aggregate quarter-hourly cost data points into hourly buckets.

    Sums cost values across all tariff components, grouped by the
    clock hour each data point falls into.
    Returns a dict mapping hour-start datetimes (UTC) to total cost.
    """
    hourly: dict[datetime, float] = defaultdict(float)
    for component in components:
        for dataset in component.get("datasets", []):
            if dataset.get("name") != "cost":
                continue
            for point in dataset.get("data", []):
                ts = dt_util.parse_datetime(point["timestamp"])
                if ts is None:
                    continue
                hour_start = dt_util.as_utc(ts).replace(
                    minute=0, second=0, microsecond=0
                )
                hourly[hour_start] += point.get("value", 0.0)
    return dict(hourly)


def _compute_component_costs(
    components: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute per-component total cost from the API response.

    Returns a list of dicts with 'name' and 'cost' for each tariff component.
    """
    result: list[dict[str, Any]] = []
    for component in components:
        total = 0.0
        for dataset in component.get("datasets", []):
            if dataset.get("name") != "cost":
                continue
            for point in dataset.get("data", []):
                total += point.get("value", 0.0)
        result.append({"name": component.get("name", "Unknown"), "cost": total})
    return result


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
        tariff_slug = slugify(config_entry.title)
        self.statistic_id = f"{DOMAIN}:grid_cost_{tariff_slug}"
        self._cached_system_operator: dict[str, Any] | None | UndefinedType = UNDEFINED
        self._last_imported_costs: dict[datetime, float] = {}

    async def _async_update_data(self) -> EngrateTariffData:
        """Fetch tariff data and calculate costs from recorder history."""
        tariff_id = self.config_entry.data[CONF_TARIFF_ID]

        try:
            tariff = await self.client.async_get_tariff(tariff_id)
        except EngrateApiAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except EngrateApiConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err

        # Resolve system operator once, then cache
        if self._cached_system_operator is UNDEFINED:
            self._cached_system_operator = await self._resolve_system_operator(tariff)
        system_operator = self._cached_system_operator

        configured_datasets: dict[str, str] = self.config_entry.data[CONF_DATASETS]

        now = dt_util.now()
        period_start = _year_start_local()
        period_end = now

        grid_cost, hourly_costs, component_costs = await self._calculate_grid_cost(
            tariff_id,
            configured_datasets,
            period_start,
            period_end,
        )

        if hourly_costs:
            self._import_cost_statistics(hourly_costs)

        last_calculated = dt_util.utcnow()

        LOGGER.debug(
            "Update complete: grid_cost=%s, period=%s to %s, hours=%d",
            grid_cost,
            period_start.isoformat(),
            period_end.isoformat(),
            len(hourly_costs) if hourly_costs else 0,
        )

        return EngrateTariffData(
            tariff_id=tariff["id"],
            tariff_name=tariff["name"],
            tariff_raw=tariff,
            system_operator_name=(
                system_operator.get("name") if system_operator else None
            ),
            grid_cost=grid_cost,
            component_costs=component_costs,
            last_calculated=last_calculated,
            period_start=period_start,
            period_end=period_end,
            statistic_id=self.statistic_id,
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
    ) -> tuple[float | None, dict[datetime, float] | None, list[dict[str, Any]]]:
        """Calculate grid cost for the full period using recorder history.

        Returns a tuple of (total_cost, hourly_cost_breakdown, component_costs).
        The hourly breakdown maps hour-start datetimes to cost values,
        used for importing external statistics.
        """
        if not configured_datasets:
            LOGGER.debug("No configured datasets, skipping grid cost calculation")
            return None, None, []

        start_iso = dt_util.as_utc(period_start).isoformat()
        end_iso = dt_util.as_utc(period_end).isoformat()

        api_datasets: list[dict[str, Any]] = []

        # Build time series for each configured dataset from recorder history
        for dataset_name, entity_id in configured_datasets.items():
            resolution = _parse_resolution(dataset_name)

            if resolution is DatasetResolution.YEARLY:
                # Yearly datasets are static scalars — read current entity state
                state = self.hass.states.get(entity_id)
                if state and state.state not in (None, "unknown", "unavailable"):
                    try:
                        value = float(state.state)
                    except ValueError:
                        value = 0.0
                else:
                    value = 0.0
                data_points = [
                    {
                        "timestamp": dt_util.as_utc(period_start).isoformat(),
                        "value": value,
                    }
                ]
            elif resolution is DatasetResolution.HOURLY:
                # Hourly datasets (e.g. available capacity) — keep hourly
                rows = await self._query_stats(
                    entity_id, period_start, period_end, {"mean"}
                )
                data_points = _build_hourly_series(rows, period_start, period_end)
            else:
                # Quarter-hourly: expand hourly recorder stats to QH
                is_price = dataset_name in PRICE_DATASET_IDS
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
            prev_cost = self.data.grid_cost if self.data else None
            prev_components = self.data.component_costs if self.data else []
            return prev_cost, None, prev_components

        hourly_costs = _aggregate_hourly_costs(components)
        total = sum(hourly_costs.values())
        component_costs = _compute_component_costs(components)

        return total, hourly_costs, component_costs

    def _import_cost_statistics(
        self,
        hourly_costs: dict[datetime, float],
    ) -> None:
        """Import hourly cost data as external statistics.

        Each hour's cost is stored as `state` (the cost for that hour)
        and `sum` (cumulative cost from the start of the year).
        Only hours that are new or changed since the last import are sent,
        along with all subsequent hours (since cumulative sums shift).
        """
        # Find the first hour that differs from the previous import
        sorted_hours = sorted(hourly_costs)
        first_changed_idx = len(sorted_hours)
        for idx, hour_start in enumerate(sorted_hours):
            prev = self._last_imported_costs.get(hour_start)
            if prev is None or prev != hourly_costs[hour_start]:
                first_changed_idx = idx
                break

        # Also check if hours were removed (fewer hours than before)
        if len(hourly_costs) < len(self._last_imported_costs):
            first_changed_idx = 0

        if first_changed_idx >= len(sorted_hours):
            return  # Nothing changed

        metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"Engrate {self.config_entry.title}",
            source=DOMAIN,
            statistic_id=self.statistic_id,
            unit_of_measurement=self.hass.config.currency,
            unit_class=None,
        )

        # Compute cumulative sum from the start of the year
        cumulative = 0.0
        statistics: list[StatisticData] = []
        for idx, hour_start in enumerate(sorted_hours):
            hourly_value = hourly_costs[hour_start]
            cumulative += hourly_value
            if idx >= first_changed_idx:
                statistics.append(
                    StatisticData(
                        start=hour_start,
                        state=hourly_value,
                        sum=cumulative,
                    )
                )

        if statistics:
            async_add_external_statistics(self.hass, metadata, statistics)

        self._last_imported_costs = dict(hourly_costs)

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
