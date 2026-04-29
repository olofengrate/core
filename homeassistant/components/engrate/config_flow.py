"""Config flow for the Engrate integration."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    EntityFilterSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
)

from .api import (
    EngrateApiAuthError,
    EngrateApiClient,
    EngrateApiConnectionError,
    EngrateApiError,
)
from .const import (
    CONF_API_KEY,
    CONF_DATASETS,
    CONF_SYSTEM_OPERATOR_ID,
    CONF_TARIFF_ID,
    DOMAIN,
    LOGGER,
)

# Dataset IDs that map to energy sensors (kWh) — use device_class filter
ENERGY_DATASET_IDS = {
    "quarter-hourly-energy-offtake",
    "quarter-hourly-energy-injection",
}

# Energy cost dataset IDs (should not appear in configure_datasets step)
# These are auto-detected from the tariff definition


def _natural_sort_key(text: str) -> list[str | int]:
    """Generate a sort key that sorts embedded numbers numerically."""
    return [
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", text)
    ]


def _extract_required_datasets(tariff: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract unique required dataset definitions from a tariff's components.

    Returns a deduplicated list of dataset dicts (with id, resolution, unit).
    Only returns datasets the user must supply (registered input datasets).
    """
    seen: set[str] = set()
    datasets: list[dict[str, Any]] = []
    for component in tariff.get("tariff_components", []):
        for dataset in component.get("datasets", []):
            ds_id = dataset["id"]
            if ds_id not in seen:
                seen.add(ds_id)
                datasets.append(dataset)
    return datasets


class EngrateConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Engrate."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._api_key: str | None = None
        self._client: EngrateApiClient | None = None
        self._system_operators: list[dict[str, Any]] = []
        self._system_operator_id: str | None = None
        self._tariffs: list[dict[str, Any]] = []
        self._tariff: dict[str, Any] | None = None
        self._required_datasets: list[dict[str, Any]] = []
        self._datasets: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the API key input step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            session = async_get_clientsession(self.hass)
            client = EngrateApiClient(session, api_key)
            try:
                system_operators = await client.async_list_system_operators()
            except EngrateApiAuthError:
                errors["base"] = "invalid_auth"
            except EngrateApiConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                if not system_operators:
                    return self.async_abort(reason="no_system_operators")
                self._api_key = api_key
                self._client = client
                self._system_operators = system_operators
                return await self.async_step_select_system_operator()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): str}),
            errors=errors,
            description_placeholders={"console_url": "https://console.engrate.io/"},
        )

    async def async_step_select_system_operator(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle system operator selection step."""
        assert self._client is not None

        if user_input is not None:
            operator_id = user_input[CONF_SYSTEM_OPERATOR_ID]
            self._system_operator_id = operator_id

            try:
                all_tariffs = await self._client.async_list_tariffs(
                    system_operator_id=operator_id
                )
            except (
                EngrateApiAuthError,
                EngrateApiConnectionError,
                EngrateApiError,
            ):
                return self.async_abort(reason="cannot_connect")
            except Exception:  # noqa: BLE001
                LOGGER.exception("Unexpected exception")
                return self.async_abort(reason="unknown")

            # Only show fuse-based tariffs
            self._tariffs = [
                t
                for t in all_tariffs
                if "fuse_based" in t.get("eligibility", {}).get("other", [])
            ]

            if not self._tariffs:
                return self.async_abort(reason="no_tariffs")

            return await self.async_step_select_tariff()

        sorted_operators = sorted(self._system_operators, key=lambda op: op["name"])
        operator_options = {op["id"]: op["name"] for op in sorted_operators}
        return self.async_show_form(
            step_id="select_system_operator",
            data_schema=vol.Schema(
                {vol.Required(CONF_SYSTEM_OPERATOR_ID): vol.In(operator_options)}
            ),
        )

    async def async_step_select_tariff(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle tariff selection step."""
        if user_input is not None:
            tariff_id = user_input[CONF_TARIFF_ID]
            await self.async_set_unique_id(tariff_id)
            self._abort_if_unique_id_configured()

            self._tariff = next(t for t in self._tariffs if t["id"] == tariff_id)
            all_datasets = _extract_required_datasets(self._tariff)

            self._required_datasets = all_datasets

            if not self._required_datasets:
                # No datasets needed — create entry directly
                return self._create_config_entry({})

            return await self.async_step_configure_datasets()

        sorted_tariffs = sorted(
            self._tariffs, key=lambda t: _natural_sort_key(t["name"])
        )
        tariff_options = {t["id"]: t["name"] for t in sorted_tariffs}
        return self.async_show_form(
            step_id="select_tariff",
            data_schema=vol.Schema(
                {vol.Required(CONF_TARIFF_ID): vol.In(tariff_options)}
            ),
        )

    async def async_step_configure_datasets(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle dataset entity mapping step."""
        assert self._tariff is not None

        if user_input is not None:
            return self._create_config_entry(user_input)

        # Build a schema with one entity selector per required dataset
        schema_dict: dict[vol.Marker, Any] = {}
        for ds in self._required_datasets:
            ds_id = ds["id"]
            if ds_id in ENERGY_DATASET_IDS:
                selector = EntitySelector(
                    EntitySelectorConfig(
                        domain="sensor",
                        filter=EntityFilterSelectorConfig(
                            device_class=[SensorDeviceClass.ENERGY],
                        ),
                    )
                )
            else:
                selector = EntitySelector(EntitySelectorConfig(domain="sensor"))
            schema_dict[vol.Required(ds_id)] = selector

        return self.async_show_form(
            step_id="configure_datasets",
            data_schema=vol.Schema(schema_dict),
        )

    def _create_config_entry(self, datasets: dict[str, Any]) -> ConfigFlowResult:
        """Create the config entry with the collected data."""
        assert self._tariff is not None
        return self.async_create_entry(
            title=self._tariff["name"],
            data={
                CONF_API_KEY: self._api_key,
                CONF_SYSTEM_OPERATOR_ID: self._system_operator_id,
                CONF_TARIFF_ID: self._tariff["id"],
                CONF_DATASETS: datasets,
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle reconfiguration to change the selected tariff."""
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()
        api_key = reconfigure_entry.data[CONF_API_KEY]

        if user_input is not None:
            tariff_id = user_input[CONF_TARIFF_ID]
            return self.async_update_reload_and_abort(
                reconfigure_entry,
                unique_id=tariff_id,
                data={**reconfigure_entry.data, CONF_TARIFF_ID: tariff_id},
            )

        try:
            session = async_get_clientsession(self.hass)
            client = EngrateApiClient(session, api_key)
            tariffs = await client.async_list_tariffs()
        except EngrateApiAuthError:
            errors["base"] = "invalid_auth"
            tariffs = []
        except EngrateApiConnectionError:
            errors["base"] = "cannot_connect"
            tariffs = []
        except Exception:  # noqa: BLE001
            LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"
            tariffs = []

        if not tariffs and not errors:
            return self.async_abort(reason="no_tariffs")

        if errors:
            return self.async_abort(reason="cannot_connect")

        sorted_tariffs = sorted(tariffs, key=lambda t: _natural_sort_key(t["name"]))
        tariff_options = {t["id"]: t["name"] for t in sorted_tariffs}
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TARIFF_ID,
                        default=reconfigure_entry.data[CONF_TARIFF_ID],
                    ): vol.In(tariff_options)
                }
            ),
            errors=errors,
        )
