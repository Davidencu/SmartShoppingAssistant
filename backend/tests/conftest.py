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
    mocker.patch("services.supabase_service.get_supabase_admin", return_value=mock)
    mocker.patch("routers.auth.get_supabase_admin", return_value=mock)
    mocker.patch("routers.wallet.get_supabase_admin", return_value=mock)
    mocker.patch("routers.webhooks.get_supabase_admin", return_value=mock)
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
