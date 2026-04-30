"""Test the Engrate config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.components.engrate.api import EngrateApiConnectionError
from homeassistant.components.engrate.const import (
    CONF_API_KEY,
    CONF_COUNTRY,
    CONF_DATASETS,
    CONF_SYSTEM_OPERATOR_ID,
    CONF_TARIFF_ID,
    DOMAIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import (
    MOCK_SYSTEM_OPERATORS,
    MOCK_TARIFF,
    MOCK_TARIFF_WITH_CAPACITY,
    MOCK_TARIFF_WITH_SPOT_PRICE,
    MOCK_TARIFFS,
)

from tests.common import MockConfigEntry


async def test_user_flow_full(hass: HomeAssistant, mock_setup_entry: AsyncMock) -> None:
    """Test full flow: country → API key → system operator → tariff → datasets."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_country"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_COUNTRY: "SE"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "api_key"
    assert result["errors"] == {}

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(
            return_value=MOCK_SYSTEM_OPERATORS
        )
        client.async_list_tariffs = AsyncMock(return_value=MOCK_TARIFFS)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "test-api-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_system_operator"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SYSTEM_OPERATOR_ID: "party-uuid-1"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_tariff"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TARIFF_ID: "tariff-uuid-1"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "configure_datasets"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"quarter-hourly-energy-offtake": "sensor.energy_meter"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Fuse subscription - 20 A"
    assert result["data"] == {
        CONF_API_KEY: "test-api-key",
        CONF_COUNTRY: "SE",
        CONF_SYSTEM_OPERATOR_ID: "party-uuid-1",
        CONF_TARIFF_ID: "tariff-uuid-1",
        CONF_DATASETS: {"quarter-hourly-energy-offtake": "sensor.energy_meter"},
    }
    assert result["result"].unique_id == "tariff-uuid-1"
    assert len(mock_setup_entry.mock_calls) == 1


async def test_user_flow_with_injection(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test flow with a tariff that requires both offtake and injection."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_COUNTRY: "SE"},
    )

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(
            return_value=MOCK_SYSTEM_OPERATORS
        )
        client.async_list_tariffs = AsyncMock(return_value=MOCK_TARIFFS)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "test-api-key"},
        )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SYSTEM_OPERATOR_ID: "party-uuid-1"},
    )

    # Select the tariff with injection requirement
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TARIFF_ID: "tariff-uuid-2"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "configure_datasets"

    # Both offtake and injection should be required
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "quarter-hourly-energy-offtake": "sensor.energy_import",
            "quarter-hourly-energy-injection": "sensor.energy_export",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_DATASETS] == {
        "quarter-hourly-energy-offtake": "sensor.energy_import",
        "quarter-hourly-energy-injection": "sensor.energy_export",
    }


async def test_user_flow_invalid_auth(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test handling of an invalid API key."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_COUNTRY: "SE"},
    )

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(
            side_effect=__import__(
                "homeassistant.components.engrate.api",
                fromlist=["EngrateApiAuthError"],
            ).EngrateApiAuthError,
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "bad-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    # Recover from error
    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(
            return_value=MOCK_SYSTEM_OPERATORS
        )
        client.async_list_tariffs = AsyncMock(return_value=MOCK_TARIFFS)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "test-api-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_system_operator"


async def test_user_flow_cannot_connect(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test handling of a connection error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_COUNTRY: "SE"},
    )

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(
            side_effect=__import__(
                "homeassistant.components.engrate.api",
                fromlist=["EngrateApiConnectionError"],
            ).EngrateApiConnectionError,
        )

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "test-api-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_flow_no_system_operators(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test abort when no system operators are found."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_COUNTRY: "SE"},
    )

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(return_value=[])

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "test-api-key"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_system_operators"


async def test_user_flow_no_tariffs(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test abort when no tariffs are found for operator."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_COUNTRY: "SE"},
    )

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(
            return_value=MOCK_SYSTEM_OPERATORS
        )
        client.async_list_tariffs = AsyncMock(return_value=[])

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "test-api-key"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_system_operator"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SYSTEM_OPERATOR_ID: "party-uuid-1"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_tariffs"


async def test_user_flow_already_configured(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test abort if tariff is already configured."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="tariff-uuid-1",
        data={
            CONF_API_KEY: "test-api-key",
            CONF_COUNTRY: "SE",
            CONF_SYSTEM_OPERATOR_ID: "party-uuid-1",
            CONF_TARIFF_ID: "tariff-uuid-1",
            CONF_DATASETS: {},
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(
            return_value=MOCK_SYSTEM_OPERATORS
        )
        client.async_list_tariffs = AsyncMock(return_value=MOCK_TARIFFS)

        # Pre-fill skips country and API key steps, goes to system operator
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_system_operator"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SYSTEM_OPERATOR_ID: "party-uuid-1"},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TARIFF_ID: "tariff-uuid-1"},
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_user_flow_with_spot_price_dataset(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test flow where tariff requires a spot price dataset."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_COUNTRY: "SE"},
    )

    tariffs_with_spot = [*MOCK_TARIFFS, MOCK_TARIFF_WITH_SPOT_PRICE]

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(
            return_value=MOCK_SYSTEM_OPERATORS
        )
        client.async_list_tariffs = AsyncMock(return_value=tariffs_with_spot)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "test-api-key"},
        )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SYSTEM_OPERATOR_ID: "party-uuid-1"},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_TARIFF_ID: "tariff-uuid-3"},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "configure_datasets"

    # Both energy offtake and spot price datasets should appear
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "quarter-hourly-energy-offtake": "sensor.energy_meter",
            "quarter-hourly-day-ahead-price-se3": "sensor.nordpool_se3",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Spot price tariff"
    assert result["data"][CONF_DATASETS] == {
        "quarter-hourly-energy-offtake": "sensor.energy_meter",
        "quarter-hourly-day-ahead-price-se3": "sensor.nordpool_se3",
    }


async def test_reconfigure_flow(
    hass: HomeAssistant,
) -> None:
    """Test the reconfigure flow shows tariff selection then dataset mapping."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="tariff-uuid-1",
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
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_tariffs = AsyncMock(return_value=MOCK_TARIFFS)
        client.async_get_tariff = AsyncMock(return_value=MOCK_TARIFF)

        result = await entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # Select the same tariff — triggers dataset re-prompt
    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_get_tariff = AsyncMock(return_value=MOCK_TARIFF)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_TARIFF_ID: "tariff-uuid-1"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure_datasets"


async def test_reconfigure_flow_with_new_tariff(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test reconfigure flow changes tariff and re-prompts datasets."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="tariff-uuid-1",
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
    entry.add_to_hass(hass)

    all_tariffs = [*MOCK_TARIFFS, MOCK_TARIFF_WITH_CAPACITY]

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_tariffs = AsyncMock(return_value=all_tariffs)

        result = await entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"

    # Select a different tariff with capacity datasets
    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_get_tariff = AsyncMock(return_value=MOCK_TARIFF_WITH_CAPACITY)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_TARIFF_ID: "tariff-uuid-4"},
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure_datasets"

    # Submit dataset mapping
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "quarter-hourly-energy-offtake": "sensor.energy_meter",
            "yearly-firm-subscribed-offtake-capacity": "sensor.subscribed",
            "hourly-available-conditional-offtake-capacity": "sensor.capacity",
        },
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_TARIFF_ID] == "tariff-uuid-4"
    assert entry.data[CONF_DATASETS] == {
        "quarter-hourly-energy-offtake": "sensor.energy_meter",
        "yearly-firm-subscribed-offtake-capacity": "sensor.subscribed",
        "hourly-available-conditional-offtake-capacity": "sensor.capacity",
    }


async def test_reconfigure_flow_connection_error(
    hass: HomeAssistant,
    mock_setup_entry: AsyncMock,
) -> None:
    """Test reconfigure flow aborts on connection error when fetching tariff."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="tariff-uuid-1",
        data={
            CONF_API_KEY: "test-api-key",
            CONF_COUNTRY: "SE",
            CONF_SYSTEM_OPERATOR_ID: "party-uuid-1",
            CONF_TARIFF_ID: "tariff-uuid-1",
            CONF_DATASETS: {},
        },
    )
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_tariffs = AsyncMock(return_value=MOCK_TARIFFS)

        result = await entry.start_reconfigure_flow(hass)

    assert result["type"] is FlowResultType.FORM

    # Selecting tariff fails to fetch full tariff
    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_get_tariff = AsyncMock(side_effect=EngrateApiConnectionError)

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_TARIFF_ID: "tariff-uuid-1"},
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "cannot_connect"


async def test_user_flow_prefills_from_existing_entry(
    hass: HomeAssistant, mock_setup_entry: AsyncMock
) -> None:
    """Test that adding a second tariff reuses the API key from the first entry."""
    # Create an existing entry
    existing = MockConfigEntry(
        domain=DOMAIN,
        unique_id="tariff-uuid-1",
        data={
            CONF_API_KEY: "existing-api-key",
            CONF_COUNTRY: "SE",
            CONF_SYSTEM_OPERATOR_ID: "party-uuid-1",
            CONF_TARIFF_ID: "tariff-uuid-1",
            CONF_DATASETS: {},
        },
    )
    existing.add_to_hass(hass)

    with patch(
        "homeassistant.components.engrate.config_flow.EngrateApiClient",
    ) as mock_client_class:
        client = mock_client_class.return_value
        client.async_list_system_operators = AsyncMock(
            return_value=MOCK_SYSTEM_OPERATORS
        )
        client.async_list_tariffs = AsyncMock(return_value=MOCK_TARIFFS)

        # Starting the flow should skip API key step and go to system operator
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

    # Should skip directly to select_system_operator
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_system_operator"
