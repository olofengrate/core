"""The Engrate integration."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EngrateApiClient
from .const import CONF_API_KEY
from .coordinator import EngrateConfigEntry, EngrateCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: EngrateConfigEntry) -> bool:
    """Set up Engrate from a config entry."""
    session = async_get_clientsession(hass)
    client = EngrateApiClient(session, entry.data[CONF_API_KEY])

    coordinator = EngrateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: EngrateConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
