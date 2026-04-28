"""Test the Engrate integration setup and coordinator."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.engrate.api import EngrateApiConnectionError
from homeassistant.components.engrate.coordinator import EngrateTariffData
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .conftest import (
    MOCK_HOURLY_STATS_ENERGY,
    MOCK_HOURLY_STATS_PRICE,
    MOCK_PARTY,
    MOCK_TARIFF,
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
    assert data.tariff_name == "Säkringsabonnemang - 20 A"
    assert data.tariff_summary == "Fuse-based tariff for 20A."
    assert data.system_operator_name == "Ellevio AB"
    assert data.system_operator_description == "A major Swedish DSO."
    assert data.system_operator_logo_url == "https://example.com/logo.png"
    # No recorder data provided, so period is None
    assert data.period_start is None
    assert data.period_end is None


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
    assert data.system_operator_logo_url is None


async def test_cost_sensor_created(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that the cost sensor entity is created."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.engrate_grid_cost")
    assert state is not None
    assert state.attributes["device_class"] == "monetary"
    assert state.attributes["state_class"] == "total"

    # Verify all three sensors exist
    assert hass.states.get("sensor.engrate_energy_cost") is not None
    assert hass.states.get("sensor.engrate_total_cost") is not None


async def test_cost_from_recorder(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test that costs are calculated from recorder statistics."""

    def _stats_side_effect(
        _hass,
        start,
        end,
        statistic_ids,
        period,
        units,
        types,
    ):
        entity_id = next(iter(statistic_ids))
        if entity_id == "sensor.energy_meter":
            return {entity_id: MOCK_HOURLY_STATS_ENERGY}
        if entity_id == "sensor.energy_price":
            return {entity_id: MOCK_HOURLY_STATS_PRICE}
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
    # Energy cost: (10+10) kWh * 0.50 SEK/kWh = 10.0
    assert coordinator.data.energy_cost == 10.0
    assert coordinator.data.total_cost == 10.54
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
    """Test that costs are None when recorder has no data."""
    # mock_recorder returns {} by default (no stats)
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    coordinator = mock_config_entry.runtime_data
    assert coordinator.data.grid_cost is None
    assert coordinator.data.energy_cost is None
    assert coordinator.data.total_cost is None
