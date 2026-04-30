"""Test the Engrate integration setup and coordinator."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.engrate.api import EngrateApiConnectionError
from homeassistant.components.engrate.const import (
    CONF_API_KEY,
    CONF_COUNTRY,
    CONF_DATASETS,
    CONF_SYSTEM_OPERATOR_ID,
    CONF_TARIFF_ID,
    DOMAIN,
)
from homeassistant.components.engrate.coordinator import EngrateTariffData
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .conftest import (
    MOCK_HOURLY_STATS_CAPACITY,
    MOCK_HOURLY_STATS_ENERGY,
    MOCK_HOURLY_STATS_PRICE,
    MOCK_PARTY,
    MOCK_TARIFF,
    MOCK_TARIFF_WITH_CAPACITY,
    MOCK_TARIFF_WITH_SPOT_PRICE,
)

from tests.common import MockConfigEntry


async def test_setup_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test successful setup of a config entry."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    coordinator = mock_config_entry.runtime_data
    assert coordinator.data is not None
    assert coordinator.data.tariff_name == MOCK_TARIFF["name"]
    assert coordinator.data.system_operator_name == MOCK_PARTY["name"]


async def test_setup_entry_api_error(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test setup fails gracefully on API error."""
    mock_engrate_client.async_get_tariff.side_effect = EngrateApiConnectionError(
        "Connection error"
    )

    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_unload_entry(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test unloading a config entry."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.LOADED

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state is ConfigEntryState.NOT_LOADED


async def test_coordinator_data_structure(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test the coordinator produces correct EngrateTariffData."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    data: EngrateTariffData = mock_config_entry.runtime_data.data
    assert data.tariff_id == "tariff-uuid-1"
    assert data.tariff_name == "Fuse subscription - 20 A"
    assert data.system_operator_name == "Ellevio AB"
    assert data.statistic_id == "engrate:grid_cost_fuse_subscription_20_a"
    assert isinstance(data.component_costs, list)
    assert data.tariff_raw is not None
    # Period is always the current calendar year
    assert data.period_start is not None
    assert data.period_end is not None
    assert isinstance(data.period_start, datetime)
    assert isinstance(data.period_end, datetime)


async def test_coordinator_no_system_operator(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test coordinator handles missing system operator gracefully."""
    mock_engrate_client.async_resolve_system_operator.return_value = None
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    data: EngrateTariffData = mock_config_entry.runtime_data.data
    assert data.tariff_name == "Fuse subscription - 20 A"
    assert data.system_operator_name is None


async def test_cost_from_recorder(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that grid cost is calculated from recorder statistics."""

    def _stats_side_effect(
        _hass: HomeAssistant,
        start: datetime,
        end: datetime,
        statistic_ids: set[str],
        period: str,
        units: dict[str, str] | None,
        types: set[str],
    ) -> dict[str, list[dict]]:
        entity_id = next(iter(statistic_ids))
        if entity_id == "sensor.energy_meter":
            return {entity_id: MOCK_HOURLY_STATS_ENERGY}
        return {}

    mock_recorder.side_effect = _stats_side_effect

    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data
    # Grid cost comes from the calculate API mock (0.54)
    assert coordinator.data.grid_cost == 0.54
    assert coordinator.data.component_costs == [{"name": "Energy tax", "cost": 0.54}]
    assert coordinator.data.last_calculated is not None
    assert coordinator.data.period_start is not None
    assert isinstance(coordinator.data.period_start, datetime)
    mock_engrate_client.async_calculate_tariff.assert_called_once()


async def test_cost_no_recorder_data(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that costs are calculated with 0-filled data when recorder is empty."""
    # mock_recorder returns {} by default (no stats)
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data
    # Missing recorder data is filled with 0s, API still called
    assert coordinator.data.grid_cost == 0.54
    mock_engrate_client.async_calculate_tariff.assert_called_once()


async def test_external_statistics_imported(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that external statistics are imported with correct hourly data."""
    mock_config_entry.add_to_hass(hass)

    with (
        patch(
            "homeassistant.components.engrate.EngrateApiClient",
            return_value=mock_engrate_client,
        ),
        patch(
            "homeassistant.components.engrate.coordinator.async_add_external_statistics"
        ) as mock_import,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    mock_import.assert_called_once()
    metadata = mock_import.call_args[0][1]
    statistics = mock_import.call_args[0][2]

    assert metadata["source"] == "engrate"
    assert metadata["statistic_id"].startswith("engrate:grid_cost_")
    assert metadata["has_sum"] is True
    assert len(statistics) > 0
    # First stat should have state and cumulative sum
    assert "state" in statistics[0]
    assert "sum" in statistics[0]
    assert "start" in statistics[0]


async def test_quarter_hourly_energy_uses_change_stat(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that quarter-hourly energy datasets query 'change' and divide by 4."""

    def _stats_side_effect(
        _hass: HomeAssistant,
        start: datetime,
        end: datetime,
        statistic_ids: set[str],
        period: str,
        units: dict[str, str] | None,
        types: set[str],
    ) -> dict[str, list[dict]]:
        entity_id = next(iter(statistic_ids))
        if entity_id == "sensor.energy_meter":
            assert types == {"change"}, "Energy datasets must use 'change' stat"
            return {entity_id: MOCK_HOURLY_STATS_ENERGY}
        return {}

    mock_recorder.side_effect = _stats_side_effect

    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    # Verify the datasets sent to API have QH expansion (4 points per hour)
    call_args = mock_engrate_client.async_calculate_tariff.call_args
    api_datasets = call_args.kwargs.get("datasets") or call_args[1].get("datasets")
    energy_ds = next(
        d for d in api_datasets if d["name"] == "quarter-hourly-energy-offtake"
    )
    # Should have QH points (4 per hour for the period)
    assert len(energy_ds["data"]) >= 8
    # Find data points with non-zero values (from mock stats with change=10.0)
    nonzero = [p for p in energy_ds["data"] if p["value"] != 0.0]
    # 2 hours × 4 QH = 8 non-zero points, each = 10.0 / 4 = 2.5
    assert len(nonzero) == 8
    for point in nonzero:
        assert point["value"] == 10.0 / 4


async def test_quarter_hourly_price_uses_mean_stat(
    hass: HomeAssistant,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that quarter-hourly price datasets query 'mean' and replicate (no divide)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="tariff-uuid-3",
        title="Spot price tariff",
        data={
            CONF_API_KEY: "test-api-key",
            CONF_COUNTRY: "SE",
            CONF_SYSTEM_OPERATOR_ID: "party-uuid-1",
            CONF_TARIFF_ID: "tariff-uuid-3",
            CONF_DATASETS: {
                "quarter-hourly-energy-offtake": "sensor.energy_meter",
                "quarter-hourly-day-ahead-price-se3": "sensor.nordpool_se3",
            },
        },
    )

    mock_engrate_client.async_get_tariff.return_value = MOCK_TARIFF_WITH_SPOT_PRICE

    def _stats_side_effect(
        _hass: HomeAssistant,
        start: datetime,
        end: datetime,
        statistic_ids: set[str],
        period: str,
        units: dict[str, str] | None,
        types: set[str],
    ) -> dict[str, list[dict]]:
        entity_id = next(iter(statistic_ids))
        if entity_id == "sensor.nordpool_se3":
            assert types == {"mean"}, "Price datasets must use 'mean' stat"
            return {entity_id: MOCK_HOURLY_STATS_PRICE}
        if entity_id == "sensor.energy_meter":
            return {entity_id: MOCK_HOURLY_STATS_ENERGY}
        return {}

    mock_recorder.side_effect = _stats_side_effect
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    call_args = mock_engrate_client.async_calculate_tariff.call_args
    api_datasets = call_args.kwargs.get("datasets") or call_args[1].get("datasets")
    price_ds = next(
        d for d in api_datasets if d["name"] == "quarter-hourly-day-ahead-price-se3"
    )
    # Price values are replicated (not divided) — first 4 QH values equal the hourly mean
    first_four = price_ds["data"][:4]
    for point in first_four:
        assert point["value"] == 0.50


async def test_hourly_dataset_kept_hourly(
    hass: HomeAssistant,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that hourly datasets produce hourly (not QH) data points."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="tariff-uuid-4",
        title="Capacity tariff",
        data={
            CONF_API_KEY: "test-api-key",
            CONF_COUNTRY: "SE",
            CONF_SYSTEM_OPERATOR_ID: "party-uuid-1",
            CONF_TARIFF_ID: "tariff-uuid-4",
            CONF_DATASETS: {
                "quarter-hourly-energy-offtake": "sensor.energy_meter",
                "hourly-available-conditional-offtake-capacity": "sensor.capacity",
                "yearly-firm-subscribed-offtake-capacity": "sensor.subscribed_capacity",
            },
        },
    )

    mock_engrate_client.async_get_tariff.return_value = MOCK_TARIFF_WITH_CAPACITY

    def _stats_side_effect(
        _hass: HomeAssistant,
        start: datetime,
        end: datetime,
        statistic_ids: set[str],
        period: str,
        units: dict[str, str] | None,
        types: set[str],
    ) -> dict[str, list[dict]]:
        entity_id = next(iter(statistic_ids))
        if entity_id == "sensor.capacity":
            assert types == {"mean"}, "Hourly capacity must use 'mean' stat"
            return {entity_id: MOCK_HOURLY_STATS_CAPACITY}
        if entity_id == "sensor.energy_meter":
            return {entity_id: MOCK_HOURLY_STATS_ENERGY}
        return {}

    mock_recorder.side_effect = _stats_side_effect

    # Set up a state for the yearly entity
    hass.states.async_set("sensor.subscribed_capacity", "25.0")

    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    call_args = mock_engrate_client.async_calculate_tariff.call_args
    api_datasets = call_args.kwargs.get("datasets") or call_args[1].get("datasets")

    # Hourly dataset: 1 point per hour, values are mean (not divided)
    hourly_ds = next(
        d
        for d in api_datasets
        if d["name"] == "hourly-available-conditional-offtake-capacity"
    )
    # Should have hourly granularity — each data point represents 1 hour
    # Check that first two values match the mock means directly
    first_two_values = [p["value"] for p in hourly_ds["data"][:2]]
    assert 5.0 in first_two_values
    assert 6.0 in first_two_values


async def test_yearly_dataset_reads_entity_state(
    hass: HomeAssistant,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that yearly datasets read the current entity state (no recorder)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="tariff-uuid-4",
        title="Capacity tariff",
        data={
            CONF_API_KEY: "test-api-key",
            CONF_COUNTRY: "SE",
            CONF_SYSTEM_OPERATOR_ID: "party-uuid-1",
            CONF_TARIFF_ID: "tariff-uuid-4",
            CONF_DATASETS: {
                "quarter-hourly-energy-offtake": "sensor.energy_meter",
                "hourly-available-conditional-offtake-capacity": "sensor.capacity",
                "yearly-firm-subscribed-offtake-capacity": "sensor.subscribed_capacity",
            },
        },
    )

    mock_engrate_client.async_get_tariff.return_value = MOCK_TARIFF_WITH_CAPACITY

    def _stats_side_effect(
        _hass: HomeAssistant,
        start: datetime,
        end: datetime,
        statistic_ids: set[str],
        period: str,
        units: dict[str, str] | None,
        types: set[str],
    ) -> dict[str, list[dict]]:
        entity_id = next(iter(statistic_ids))
        if entity_id == "sensor.capacity":
            return {entity_id: MOCK_HOURLY_STATS_CAPACITY}
        if entity_id == "sensor.energy_meter":
            return {entity_id: MOCK_HOURLY_STATS_ENERGY}
        return {}

    mock_recorder.side_effect = _stats_side_effect

    # Set the yearly entity state
    hass.states.async_set("sensor.subscribed_capacity", "25.0")

    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    call_args = mock_engrate_client.async_calculate_tariff.call_args
    api_datasets = call_args.kwargs.get("datasets") or call_args[1].get("datasets")

    yearly_ds = next(
        d
        for d in api_datasets
        if d["name"] == "yearly-firm-subscribed-offtake-capacity"
    )
    # Yearly = single data point with the entity's current state value
    assert len(yearly_ds["data"]) == 1
    assert yearly_ds["data"][0]["value"] == 25.0


async def test_unknown_resolution_prefix_fails_update(
    hass: HomeAssistant,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that an unknown dataset resolution prefix causes UpdateFailed."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="tariff-uuid-bad",
        title="Bad tariff",
        data={
            CONF_API_KEY: "test-api-key",
            CONF_COUNTRY: "SE",
            CONF_SYSTEM_OPERATOR_ID: "party-uuid-1",
            CONF_TARIFF_ID: "tariff-uuid-bad",
            CONF_DATASETS: {
                "monthly-some-dataset": "sensor.something",
            },
        },
    )

    mock_engrate_client.async_get_tariff.return_value = {
        "id": "tariff-uuid-bad",
        "name": "Bad tariff",
        "tariff_components": [],
    }

    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # UpdateFailed causes SETUP_RETRY
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_system_operator_cached_across_updates(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that the system operator is resolved once and then cached."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data

    # First update: resolved once
    assert mock_engrate_client.async_resolve_system_operator.call_count == 1
    assert coordinator.data.system_operator_name == MOCK_PARTY["name"]

    # Force a second refresh
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Still only called once — cached
    assert mock_engrate_client.async_resolve_system_operator.call_count == 1
    assert coordinator.data.system_operator_name == MOCK_PARTY["name"]
