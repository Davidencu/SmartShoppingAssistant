import pytest
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4
from datetime import datetime, timezone

from fastapi.testclient import TestClient

TEST_USER_ID = uuid4()
TEST_WALLET_ID = uuid4()
NOW = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)


def _make_profile_row(user_id: UUID) -> dict:
    return {
        "id": str(user_id),
        "full_name": "Ion Popescu",
        "phone": "+40712345678",
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
    }


def _make_address_row(user_id: UUID) -> dict:
    return {
        "id": str(uuid4()),
        "user_id": str(user_id),
        "recipient_name": "Ion Popescu",
        "street": "Strada Victoriei 1",
        "city": "București",
        "state": None,
        "country": "RO",
        "zip_code": "010011",
        "is_default": True,
        "created_at": NOW.isoformat(),
    }


def _make_wallet_row(user_id: UUID, balance: int = 0, frozen: int = 0) -> dict:
    return {
        "id": str(TEST_WALLET_ID),
        "user_id": str(user_id),
        "balance_cents": balance,
        "frozen_cents": frozen,
        "currency": "USD",
        "updated_at": NOW.isoformat(),
    }


def _make_txn_row(wallet_id: UUID, txn_type: str = "TOPUP", amount: int = 5000) -> dict:
    return {
        "id": str(uuid4()),
        "wallet_id": str(wallet_id),
        "type": txn_type,
        "amount_cents": amount,
        "reference_id": "ls_order_123",
        "order_id": None,
        "created_at": NOW.isoformat(),
    }


@pytest.fixture
def mock_supabase():
    with patch("backend.services.supabase_service._make_client") as mock:
        client = MagicMock()
        mock.return_value = client
        yield client


@pytest.fixture
def app_client():
    with patch("backend.core.config.Settings") as MockSettings:
        MockSettings.return_value = MagicMock(
            supabase_url="https://test.supabase.co",
            supabase_service_role_key="service-key",
            lemonsqueezy_webhook_secret="test-secret",
            cors_origins=["http://localhost:3000"],
        )
        from main import app
        return TestClient(app)
