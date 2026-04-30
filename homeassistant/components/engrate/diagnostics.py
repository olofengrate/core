"""Diagnostics support for the Engrate integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import REDACTED
from homeassistant.core import HomeAssistant

from .coordinator import EngrateConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: EngrateConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "config_entry": {
            **entry.data,
            "api_key": REDACTED,
        },
        "tariff_raw": data.tariff_raw,
        "system_operator_name": data.system_operator_name,
    }
