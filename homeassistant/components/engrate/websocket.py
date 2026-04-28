"""Websocket API for the Engrate integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN
from .coordinator import EngrateConfigEntry


def async_setup(hass: HomeAssistant) -> None:
    """Set up the Engrate websocket API."""
    websocket_api.async_register_command(hass, ws_get_tariff_data)


@websocket_api.websocket_command(
    {
        vol.Required("type"): "engrate/tariff_data",
        vol.Required("entry_id"): str,
    }
)
@callback
def ws_get_tariff_data(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return tariff and system operator data for the given config entry."""
    entry_id = msg["entry_id"]
    entry: EngrateConfigEntry | None = hass.config_entries.async_get_entry(entry_id)

    if entry is None or entry.domain != DOMAIN:
        connection.send_error(msg["id"], "entry_not_found", "Config entry not found")
        return

    coordinator = entry.runtime_data
    data = coordinator.data

    if data is None:
        connection.send_error(msg["id"], "no_data", "No tariff data available")
        return

    connection.send_result(
        msg["id"],
        {
            "tariff_id": data.tariff_id,
            "tariff_name": data.tariff_name,
            "tariff_summary": data.tariff_summary,
            "tariff_annotations": data.tariff_annotations,
            "tariff_raw": data.tariff_raw,
            "system_operator_name": data.system_operator_name,
            "system_operator_description": data.system_operator_description,
            "system_operator_logo_url": data.system_operator_logo_url,
            "grid_cost": data.grid_cost,
            "energy_cost": data.energy_cost,
            "total_cost": data.total_cost,
            "last_calculated": data.last_calculated.isoformat()
            if data.last_calculated
            else None,
            "period_start": data.period_start.isoformat()
            if data.period_start
            else None,
            "period_end": data.period_end.isoformat() if data.period_end else None,
        },
    )
