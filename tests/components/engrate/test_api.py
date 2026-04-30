"""Test the Engrate API client."""

from unittest.mock import AsyncMock, MagicMock

from aiohttp import ClientError, ClientResponseError, ClientSession
import pytest

from homeassistant.components.engrate.api import (
    EngrateApiAuthError,
    EngrateApiClient,
    EngrateApiConnectionError,
    EngrateApiError,
)


@pytest.fixture
def mock_session() -> MagicMock:
    """Return a mocked aiohttp ClientSession."""
    return MagicMock(spec=ClientSession)


def _make_response(status: int = 200, json_data: dict | None = None) -> MagicMock:
    """Create a mock response context manager for session.request()."""
    response = MagicMock()
    response.status = status
    response.json = AsyncMock(return_value=json_data or {})
    if status >= 400:
        response.raise_for_status.side_effect = ClientResponseError(
            request_info=MagicMock(),
            history=(),
            status=status,
            message="Error",
        )
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


async def test_list_system_operators(mock_session: MagicMock) -> None:
    """Test listing system operators."""
    mock_session.request.return_value = _make_response(
        200, {"parties": [{"id": "p1", "name": "Operator"}]}
    )
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_list_system_operators(country="SE")
    assert result == [{"id": "p1", "name": "Operator"}]
    mock_session.request.assert_called_once()


async def test_list_tariffs(mock_session: MagicMock) -> None:
    """Test listing tariffs."""
    mock_session.request.return_value = _make_response(
        200, {"tariffs": [{"id": "t1", "name": "Tariff A"}]}
    )
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_list_tariffs(system_operator_id="op1")
    assert result == [{"id": "t1", "name": "Tariff A"}]


async def test_list_tariffs_no_filter(mock_session: MagicMock) -> None:
    """Test listing tariffs without system operator filter."""
    mock_session.request.return_value = _make_response(200, {"tariffs": []})
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_list_tariffs()
    assert result == []


async def test_get_tariff(mock_session: MagicMock) -> None:
    """Test getting a single tariff."""
    tariff_data = {"id": "t1", "name": "Tariff A", "tariff_components": []}
    mock_session.request.return_value = _make_response(200, tariff_data)
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_get_tariff("t1")
    assert result == tariff_data


async def test_calculate_tariff(mock_session: MagicMock) -> None:
    """Test calculating tariff costs."""
    components = [{"name": "Energy tax", "datasets": []}]
    mock_session.request.return_value = _make_response(200, {"components": components})
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_calculate_tariff(
        tariff_id="t1",
        start_time="2026-01-01T00:00:00Z",
        end_time="2026-01-02T00:00:00Z",
        datasets=[],
    )
    assert result == components


async def test_list_mgas(mock_session: MagicMock) -> None:
    """Test listing metering grid areas."""
    mgas = [{"id": "mga1", "name": "Stockholm"}]
    mock_session.request.return_value = _make_response(200, {"mgas": mgas})
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_list_mgas(["mga1"])
    assert result == mgas


async def test_list_parties(mock_session: MagicMock) -> None:
    """Test listing parties."""
    parties = [{"id": "p1", "name": "Operator"}]
    mock_session.request.return_value = _make_response(200, {"parties": parties})
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_list_parties(["p1"])
    assert result == parties


async def test_resolve_system_operator(mock_session: MagicMock) -> None:
    """Test resolving system operator from tariff data."""
    tariff = {
        "eligibility": {"metering_grid_area_ids": ["mga1"]},
    }
    mgas = [{"id": "mga1", "system_operator": {"id": "p1"}}]
    parties = [{"id": "p1", "name": "Operator"}]

    call_count = 0

    def _side_effect(*args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_response(200, {"mgas": mgas})
        return _make_response(200, {"parties": parties})

    mock_session.request.side_effect = _side_effect
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_resolve_system_operator(tariff)
    assert result == {"id": "p1", "name": "Operator"}


async def test_resolve_system_operator_no_mgas(mock_session: MagicMock) -> None:
    """Test resolving system operator with no MGA IDs."""
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_resolve_system_operator({"eligibility": {}})
    assert result is None


async def test_resolve_system_operator_empty_mgas(mock_session: MagicMock) -> None:
    """Test resolving system operator when MGA lookup returns empty."""
    mock_session.request.return_value = _make_response(200, {"mgas": []})
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_resolve_system_operator(
        {"eligibility": {"metering_grid_area_ids": ["mga1"]}}
    )
    assert result is None


async def test_resolve_system_operator_no_party_id(mock_session: MagicMock) -> None:
    """Test resolving system operator when MGA has no system operator ID."""
    mgas = [{"id": "mga1", "system_operator": {}}]
    mock_session.request.return_value = _make_response(200, {"mgas": mgas})
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_resolve_system_operator(
        {"eligibility": {"metering_grid_area_ids": ["mga1"]}}
    )
    assert result is None


async def test_resolve_system_operator_no_parties(mock_session: MagicMock) -> None:
    """Test resolving system operator when party lookup returns empty."""
    call_count = 0

    def _side_effect(*args: object, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_response(
                200, {"mgas": [{"id": "mga1", "system_operator": {"id": "p1"}}]}
            )
        return _make_response(200, {"parties": []})

    mock_session.request.side_effect = _side_effect
    client = EngrateApiClient(mock_session, "test-key")
    result = await client.async_resolve_system_operator(
        {"eligibility": {"metering_grid_area_ids": ["mga1"]}}
    )
    assert result is None


async def test_auth_error_401(mock_session: MagicMock) -> None:
    """Test 401 response raises EngrateApiAuthError."""
    mock_session.request.return_value = _make_response(401)
    client = EngrateApiClient(mock_session, "bad-key")
    with pytest.raises(EngrateApiAuthError):
        await client.async_list_system_operators()


async def test_auth_error_403(mock_session: MagicMock) -> None:
    """Test 403 response raises EngrateApiAuthError."""
    mock_session.request.return_value = _make_response(403)
    client = EngrateApiClient(mock_session, "bad-key")
    with pytest.raises(EngrateApiAuthError):
        await client.async_list_system_operators()


async def test_client_response_error(mock_session: MagicMock) -> None:
    """Test non-auth HTTP error raises EngrateApiError."""
    mock_session.request.return_value = _make_response(500)
    client = EngrateApiClient(mock_session, "test-key")
    with pytest.raises(EngrateApiError, match="API request failed"):
        await client.async_list_system_operators()


async def test_connection_error(mock_session: MagicMock) -> None:
    """Test connection failure raises EngrateApiConnectionError."""
    mock_session.request.side_effect = ClientError("Connection refused")
    client = EngrateApiClient(mock_session, "test-key")
    with pytest.raises(EngrateApiConnectionError):
        await client.async_list_system_operators()
