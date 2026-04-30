"""Test the Engrate sensor platform."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import MOCK_PARTY

from tests.common import MockConfigEntry


async def test_grid_cost_sensor_state(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test the grid cost sensor reports correct state."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.fuse_subscription_20_a_year_to_date_grid_cost")
    assert state is not None
    assert float(state.state) == 0.54


async def test_grid_cost_sensor_attributes(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test the grid cost sensor has component cost attributes."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get("sensor.fuse_subscription_20_a_year_to_date_grid_cost")
    assert state is not None
    # Component cost from mock: Energy tax = 0.54
    component_costs = json.loads(state.attributes["component_costs"])
    assert component_costs == [{"name": "Energy tax", "cost": 0.54}]
    assert "period_start" in state.attributes
    assert "period_end" in state.attributes
    assert "last_calculated" in state.attributes


async def test_grid_cost_sensor_device(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test the sensor creates a device with correct info."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(
        identifiers={("engrate", "tariff-uuid-1")}
    )
    assert device is not None
    assert device.manufacturer == MOCK_PARTY["name"]


async def test_grid_cost_sensor_unique_id(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test the sensor has the correct unique ID."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    entry = entity_registry.async_get(
        "sensor.fuse_subscription_20_a_year_to_date_grid_cost"
    )
    assert entry is not None
    assert entry.unique_id == "tariff-uuid-1_grid_cost"
