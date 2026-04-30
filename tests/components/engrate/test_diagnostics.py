"""Test the Engrate diagnostics."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from tests.common import MockConfigEntry
from tests.components.diagnostics import get_diagnostics_for_config_entry
from tests.typing import ClientSessionGenerator


async def test_diagnostics(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    mock_config_entry: MockConfigEntry,
    mock_engrate_client: AsyncMock,
    mock_recorder: MagicMock,
) -> None:
    """Test diagnostics returns tariff_raw, system operator, and redacted config."""
    mock_config_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.EngrateApiClient",
        return_value=mock_engrate_client,
    ):
        await hass.config_entries.async_setup(mock_config_entry.entry_id)
        await hass.async_block_till_done()

    result = await get_diagnostics_for_config_entry(
        hass, hass_client, mock_config_entry
    )

    assert result["config_entry"]["api_key"] == REDACTED
    assert result["config_entry"]["tariff_id"] == "tariff-uuid-1"
    assert result["tariff_raw"]["id"] == "tariff-uuid-1"
    assert result["tariff_raw"]["name"] == "Säkringsabonnemang - 20 A"
    assert result["system_operator_name"] == "Ellevio AB"
