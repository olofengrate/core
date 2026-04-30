"""Common fixtures for the Engrate tests."""

from collections.abc import Generator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components.engrate.const import (
    CONF_API_KEY,
    CONF_COUNTRY,
    CONF_DATASETS,
    CONF_SYSTEM_OPERATOR_ID,
    CONF_TARIFF_ID,
    DOMAIN,
)

from tests.common import MockConfigEntry

MOCK_SYSTEM_OPERATORS = [
    {
        "id": "party-uuid-1",
        "name": "Ellevio AB",
        "description": "A major Swedish DSO.",
        "logo_url": "https://example.com/logo.png",
        "countries": ["SE"],
        "website_url": "https://ellevio.se",
        "extra_ids": [{"kind": "eic", "value": "46X000000000245K"}],
    },
    {
        "id": "party-uuid-2",
        "name": "Vattenfall Eldistribution AB",
        "countries": ["SE"],
        "extra_ids": [],
    },
]

MOCK_TARIFFS = [
    {
        "id": "tariff-uuid-1",
        "name": "Fuse subscription - 20 A",
        "summary": "Fuse-based tariff for 20A.",
        "eligibility": {
            "metering_grid_area_ids": ["mga-uuid-1"],
            "type": "system_operator",
            "other": ["fuse_based"],
        },
        "tariff_components": [
            {
                "applicable_from": "2026-01-01T00:00:00+01:00",
                "name": "Energy tax",
                "datasets": [
                    {
                        "id": "quarter-hourly-energy-offtake",
                        "resolution": "quarter_hourly",
                        "unit": "kWh",
                    }
                ],
                "functions": [],
                "cost": {
                    "id": "cost",
                    "resolution": "quarter_hourly",
                    "unit": "SEK",
                },
                "timezone": "Europe/Stockholm",
            }
        ],
    },
    {
        "id": "tariff-uuid-2",
        "name": "Power subscription - 63 A",
        "summary": "Power-based tariff.",
        "eligibility": {
            "metering_grid_area_ids": ["mga-uuid-2"],
            "type": "system_operator",
            "other": ["fuse_based"],
        },
        "tariff_components": [
            {
                "applicable_from": "2026-01-01T00:00:00+01:00",
                "name": "Energy tax",
                "datasets": [
                    {
                        "id": "quarter-hourly-energy-offtake",
                        "resolution": "quarter_hourly",
                        "unit": "kWh",
                    },
                    {
                        "id": "quarter-hourly-energy-injection",
                        "resolution": "quarter_hourly",
                        "unit": "kWh",
                    },
                ],
                "functions": [],
                "cost": {
                    "id": "cost",
                    "resolution": "quarter_hourly",
                    "unit": "SEK",
                },
                "timezone": "Europe/Stockholm",
            }
        ],
    },
]

MOCK_TARIFF = MOCK_TARIFFS[0]
MOCK_TARIFF_WITH_INJECTION = MOCK_TARIFFS[1]

MOCK_TARIFF_WITH_SPOT_PRICE = {
    "id": "tariff-uuid-3",
    "name": "Spot price tariff",
    "summary": "Tariff that needs spot price.",
    "eligibility": {
        "metering_grid_area_ids": ["mga-uuid-1"],
        "type": "system_operator",
        "other": ["fuse_based"],
    },
    "tariff_components": [
        {
            "applicable_from": "2026-01-01T00:00:00+01:00",
            "name": "Energy tax",
            "datasets": [
                {
                    "id": "quarter-hourly-energy-offtake",
                    "resolution": "quarter_hourly",
                    "unit": "kWh",
                },
                {
                    "id": "quarter-hourly-day-ahead-price-se3",
                    "resolution": "quarter_hourly",
                    "unit": "SEK_per_kWh",
                },
            ],
            "functions": [],
            "cost": {
                "id": "cost",
                "resolution": "quarter_hourly",
                "unit": "SEK",
            },
            "timezone": "Europe/Stockholm",
        }
    ],
}

MOCK_MGAS = [
    {
        "id": "mga-uuid-1",
        "name": "Stockholm",
        "system_operator": {
            "id": "party-uuid-1",
            "extra_ids": [{"kind": "eic", "value": "46X000000000245K"}],
        },
    },
]

MOCK_PARTY = MOCK_SYSTEM_OPERATORS[0]

MOCK_CALCULATE_RESPONSE = [
    {
        "applicable_from": "2026-01-01T00:00:00+01:00",
        "name": "Energy tax",
        "datasets": [
            {
                "name": "cost",
                "data": [
                    {"timestamp": "2026-01-01T00:00:00+01:00", "value": 0.54},
                ],
            }
        ],
    }
]


@pytest.fixture
def mock_setup_entry() -> Generator[AsyncMock]:
    """Override async_setup_entry."""
    with patch(
        "homeassistant.components.engrate.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        yield mock_setup_entry


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """Return a mock config entry."""
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="tariff-uuid-1",
        title="Fuse subscription - 20 A",
        data={
            CONF_API_KEY: "test-api-key",
            CONF_COUNTRY: "SE",
            CONF_SYSTEM_OPERATOR_ID: "party-uuid-1",
            CONF_TARIFF_ID: "tariff-uuid-1",
            CONF_DATASETS: {
                "quarter-hourly-energy-offtake": "sensor.energy_meter",
            },
        },
    )


@pytest.fixture
def mock_engrate_client() -> Generator[AsyncMock]:
    """Mock the Engrate API client."""
    with patch(
        "homeassistant.components.engrate.api.EngrateApiClient", autospec=True
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(
            return_value=MOCK_SYSTEM_OPERATORS
        )
        client.async_list_tariffs = AsyncMock(return_value=MOCK_TARIFFS)
        client.async_get_tariff = AsyncMock(return_value=MOCK_TARIFF)
        client.async_list_mgas = AsyncMock(return_value=MOCK_MGAS)
        client.async_list_parties = AsyncMock(return_value=[MOCK_PARTY])
        client.async_resolve_system_operator = AsyncMock(return_value=MOCK_PARTY)
        client.async_calculate_tariff = AsyncMock(return_value=MOCK_CALCULATE_RESPONSE)
        yield client


def make_recorder_stats(
    entity_id: str,
    hourly_data: list[dict],
) -> dict[str, list[dict]]:
    """Build a statistics_during_period return value for an entity.

    Each item in hourly_data should be a dict with 'start' (epoch float)
    and optionally 'change' and/or 'mean'.
    """
    return {entity_id: hourly_data}


@pytest.fixture
def mock_recorder() -> Generator[MagicMock]:
    """Mock recorder get_instance, statistics_during_period, and external stats."""
    with (
        patch(
            "homeassistant.components.engrate.coordinator.get_instance"
        ) as mock_get_instance,
        patch(
            "homeassistant.components.engrate.coordinator.statistics_during_period"
        ) as mock_stats,
        patch(
            "homeassistant.components.engrate.coordinator.async_add_external_statistics"
        ),
    ):
        # Make async_add_executor_job call the function synchronously
        recorder_instance = MagicMock()

        async def _run_sync(func, *args):
            return func(*args)

        recorder_instance.async_add_executor_job = _run_sync
        mock_get_instance.return_value = recorder_instance

        # Default: no stats
        mock_stats.return_value = {}
        yield mock_stats


MOCK_HOURLY_STATS_ENERGY = [
    {
        "start": datetime(2026, 1, 1, 8, 0, tzinfo=UTC).timestamp(),
        "change": 10.0,
    },
    {
        "start": datetime(2026, 1, 1, 9, 0, tzinfo=UTC).timestamp(),
        "change": 10.0,
    },
]

MOCK_HOURLY_STATS_PRICE = [
    {
        "start": datetime(2026, 1, 1, 8, 0, tzinfo=UTC).timestamp(),
        "mean": 0.50,
    },
    {
        "start": datetime(2026, 1, 1, 9, 0, tzinfo=UTC).timestamp(),
        "mean": 0.55,
    },
]

MOCK_HOURLY_STATS_CAPACITY = [
    {
        "start": datetime(2026, 1, 1, 8, 0, tzinfo=UTC).timestamp(),
        "mean": 5.0,
    },
    {
        "start": datetime(2026, 1, 1, 9, 0, tzinfo=UTC).timestamp(),
        "mean": 6.0,
    },
]

MOCK_TARIFF_WITH_CAPACITY = {
    "id": "tariff-uuid-4",
    "name": "Capacity tariff",
    "summary": "Tariff with yearly and hourly capacity datasets.",
    "eligibility": {
        "metering_grid_area_ids": ["mga-uuid-1"],
        "type": "system_operator",
    },
    "tariff_components": [
        {
            "applicable_from": "2026-01-01T00:00:00+01:00",
            "name": "Capacity fee",
            "datasets": [
                {
                    "id": "quarter-hourly-energy-offtake",
                    "resolution": "quarter_hourly",
                    "unit": "kWh",
                },
                {
                    "id": "yearly-firm-subscribed-offtake-capacity",
                    "resolution": "yearly",
                    "unit": "kW",
                },
                {
                    "id": "hourly-available-conditional-offtake-capacity",
                    "resolution": "hourly",
                    "unit": "kW",
                },
            ],
            "functions": [],
            "cost": {
                "id": "cost",
                "resolution": "quarter_hourly",
                "unit": "SEK",
            },
            "timezone": "Europe/Stockholm",
        }
    ],
}
