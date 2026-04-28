"""The Engrate integration."""

from __future__ import annotations

import pathlib
from typing import Final

from homeassistant.components import frontend, panel_custom
from homeassistant.components.frontend import async_panel_exists
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import websocket as engrate_ws
from .api import EngrateApiClient
from .const import CONF_API_KEY, DOMAIN
from .coordinator import EngrateConfigEntry, EngrateCoordinator

PLATFORMS: Final = [Platform.SENSOR]
URL_BASE: Final = "/engrate_static"
FRONTEND_DIR: Final = pathlib.Path(__file__).parent / "frontend"


async def async_setup_entry(hass: HomeAssistant, entry: EngrateConfigEntry) -> bool:
    """Set up Engrate from a config entry."""
    session = async_get_clientsession(hass)
    client = EngrateApiClient(session, entry.data[CONF_API_KEY])

    coordinator = EngrateCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Register websocket commands (idempotent)
    engrate_ws.async_setup(hass)

    # Register panel and card frontend assets
    await _async_register_panel(hass)
    _register_card_js(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: EngrateConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Only remove panel if no other engrate entries remain
    remaining = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id
    ]
    if not remaining:
        frontend.async_remove_panel(hass, DOMAIN, warn_if_unknown=False)

    return unload_ok


async def _async_register_panel(hass: HomeAssistant) -> None:
    """Register the Engrate sidebar panel."""
    if async_panel_exists(hass, DOMAIN):
        return

    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(FRONTEND_DIR), cache_headers=False)]
    )
    await panel_custom.async_register_panel(
        hass=hass,
        frontend_url_path=DOMAIN,
        webcomponent_name="engrate-panel",
        sidebar_title="Engrate",
        sidebar_icon="mdi:alpha-e-box",
        module_url=f"{URL_BASE}/engrate-panel.js?v=8",
        embed_iframe=False,
        require_admin=False,
        config_panel_domain=DOMAIN,
    )


def _register_card_js(hass: HomeAssistant) -> None:
    """Register the Engrate Lovelace card as an extra JS module."""
    card_url = f"{URL_BASE}/engrate-card.js?v=8"
    frontend.add_extra_js_url(hass, card_url)
