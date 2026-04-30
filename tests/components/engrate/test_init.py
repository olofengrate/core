"""Test the Engrate integration setup and coordinator."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.engrate.api import EngrateApiConnectionError
from homeassistant.components.engrate.coordinator import EngrateTariffData
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .conftest import MOCK_HOURLY_STATS_ENERGY, MOCK_PARTY, MOCK_TARIFF

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
    assert data.tariff_name == "Säkringsabonnemang - 20 A"
    assert data.system_operator_name == "Ellevio AB"
    assert data.statistic_id == "engrate:grid_cost_sakringsabonnemang_20_a"
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
    assert data.tariff_name == "Säkringsabonnemang - 20 A"
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
    assert coordinator.data.component_costs == [{"name": "Energiskatt", "cost": 0.54}]
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
