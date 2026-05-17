import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_supabase(mocker):
    mock = MagicMock()

    # The search endpoint fetches city/country from the user's profile.
    # Configure the .table().select().eq().single().execute() chain so tests
    # receive a real dict instead of a truthy MagicMock.
    # .single() is only called for the profile lookup, so this won't collide
    # with other table access patterns (insert, order/limit, etc.).
    _profile_resp = MagicMock()
    _profile_resp.data = {"city": "", "country": ""}
    (
        mock.table.return_value
        .select.return_value
        .eq.return_value
        .single.return_value
        .execute.return_value
    ) = _profile_resp

    mocker.patch("services.supabase_service.get_supabase_admin", return_value=mock)
    mocker.patch("routers.auth.get_supabase_admin", return_value=mock)
    mocker.patch("routers.plan.get_supabase_admin", return_value=mock)
    mocker.patch("routers.webhooks.get_supabase_admin", return_value=mock)
    mocker.patch("routers.search.get_supabase_admin", return_value=mock)
    mocker.patch("services.cache_service.get_supabase_admin", return_value=mock)
    return mock


@pytest.fixture
def valid_user_data():
    return {
        "email": "test@example.com",
        "phone": "+40712345678",
        "street_address": "123 Main St",
        "city": "Bucharest",
        "state": None,
        "postal_code": "010101",
        "country": "Romania",
    }


@pytest.fixture
def auth_token():
    from routers.auth import create_token
    return create_token("test-user-uuid", "test@example.com")
