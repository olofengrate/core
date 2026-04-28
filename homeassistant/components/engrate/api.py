"""API client for the Engrate integration.

TODO: Move to separate PyPI package.
"""

from __future__ import annotations

from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import API_BASE_URL


class EngrateApiError(Exception):
    """Base exception for Engrate API errors."""


class EngrateApiAuthError(EngrateApiError):
    """Exception for authentication errors."""


class EngrateApiConnectionError(EngrateApiError):
    """Exception for connection errors."""


def _raise_on_auth_error(status: int) -> None:
    """Raise an auth error for 401/403 responses."""
    if status == 401:
        raise EngrateApiAuthError("Invalid API key")
    if status == 403:
        raise EngrateApiAuthError("Forbidden")


class EngrateApiClient:
    """Client for the Engrate API."""

    def __init__(self, session: ClientSession, api_key: str) -> None:
        """Initialize the API client."""
        self._session = session
        self._api_key = api_key

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        """Make an authenticated request to the Engrate API."""
        headers = {"Authorization": self._api_key}
        try:
            async with self._session.request(
                method, f"{API_BASE_URL}{url}", headers=headers, **kwargs
            ) as resp:
                _raise_on_auth_error(resp.status)
                resp.raise_for_status()
                return await resp.json()
        except EngrateApiAuthError:
            raise
        except ClientResponseError as err:
            raise EngrateApiError(
                f"API request failed: {err.status} {err.message}"
            ) from err
        except ClientError as err:
            raise EngrateApiConnectionError(f"Connection error: {err}") from err

    async def async_list_tariffs(
        self, system_operator_id: str | None = None
    ) -> list[dict[str, Any]]:
        """List available tariffs, optionally filtered by system operator."""
        params: list[tuple[str, str]] = []
        if system_operator_id:
            params.append(("system_operator_id", system_operator_id))
        data = await self._request("GET", "/cost-of-energy/v1/tariffs", params=params)
        return data["tariffs"]

    async def async_get_tariff(self, tariff_id: str) -> dict[str, Any]:
        """Get a single tariff by ID."""
        return await self._request("GET", f"/cost-of-energy/v1/tariffs/{tariff_id}")

    async def async_list_mgas(self, mga_ids: list[str]) -> list[dict[str, Any]]:
        """List metering grid areas by IDs."""
        params = [("id", mga_id) for mga_id in mga_ids]
        data = await self._request("GET", "/core/v1/metering-grid-areas", params=params)
        return data["mgas"]

    async def async_list_parties(self, party_ids: list[str]) -> list[dict[str, Any]]:
        """List parties by IDs."""
        params = [("id", party_id) for party_id in party_ids]
        data = await self._request("GET", "/core/v1/parties", params=params)
        return data["parties"]

    async def async_list_system_operators(
        self, country: str = "SE"
    ) -> list[dict[str, Any]]:
        """List system operator parties, filtered by country."""
        data = await self._request(
            "GET",
            "/core/v1/parties",
            params=[("role", "system-operator"), ("country", country)],
        )
        return data["parties"]

    async def async_resolve_system_operator(
        self, tariff: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Resolve the system operator party for a tariff.

        Follows: tariff → eligibility.metering_grid_area_ids → MGAs →
        system_operator.id → parties → party details.
        """
        mga_ids = tariff.get("eligibility", {}).get("metering_grid_area_ids", [])
        if not mga_ids:
            return None

        mgas = await self.async_list_mgas(mga_ids)
        if not mgas:
            return None

        # Get the system operator ID from the first MGA
        sys_op = mgas[0].get("system_operator", {})
        party_id = sys_op.get("id")
        if not party_id:
            return None

        parties = await self.async_list_parties([party_id])
        if not parties:
            return None

        return parties[0]

    async def async_calculate_tariff(
        self,
        tariff_id: str,
        start_time: str,
        end_time: str,
        datasets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Calculate costs for a tariff.

        Returns the components array from the API response.
        Each component contains datasets including a 'cost' dataset.
        """
        payload = {
            "tariff_id": tariff_id,
            "start_time": start_time,
            "end_time": end_time,
            "datasets": datasets,
        }
        data = await self._request("POST", "/cost-of-energy/v1/calculate", json=payload)
        return data["components"]
