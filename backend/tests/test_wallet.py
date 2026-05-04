import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetBalance:
    def test_unauthenticated(self, client):
        resp = client.get("/wallet/balance")
        assert resp.status_code == 401

    def test_success(self, client, mock_supabase, auth_token):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"balance": "50.00", "currency": "USD"}
        ]
        resp = client.get(
            "/wallet/balance", headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["balance"] == 50.0
        assert resp.json()["currency"] == "USD"

    def test_wallet_not_found(self, client, mock_supabase, auth_token):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        resp = client.get(
            "/wallet/balance", headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert resp.status_code == 404


class TestCreateCheckout:
    def test_unauthenticated(self, client):
        resp = client.post("/wallet/checkout", json={"amount": 10})
        assert resp.status_code == 401

    def test_invalid_amount(self, client, auth_token):
        resp = client.post(
            "/wallet/checkout",
            json={"amount": 99},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 422

    def test_valid_amounts_accepted(self, client, auth_token):
        import routers.wallet as wallet_module
        wallet_module._ls_store_id = "store-123"

        for amount in [10, 25, 40, 50, 80, 100]:
            with patch("routers.wallet.httpx.AsyncClient") as mock_cls:
                mock_resp = MagicMock()
                mock_resp.status_code = 201
                mock_resp.json.return_value = {
                    "data": {"attributes": {"url": "https://checkout.lemonsqueezy.com/test"}}
                }
                mock_ac = AsyncMock()
                mock_ac.post = AsyncMock(return_value=mock_resp)
                mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
                mock_ac.__aexit__ = AsyncMock(return_value=None)
                mock_cls.return_value = mock_ac

                resp = client.post(
                    "/wallet/checkout",
                    json={"amount": amount},
                    headers={"Authorization": f"Bearer {auth_token}"},
                )
            assert resp.status_code == 200, f"Amount {amount} should be valid"
            assert "checkout_url" in resp.json()

    def test_success_returns_checkout_url(self, client, auth_token):
        import routers.wallet as wallet_module
        wallet_module._ls_store_id = "store-123"

        with patch("routers.wallet.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {
                "data": {"attributes": {"url": "https://checkout.lemonsqueezy.com/buy/test"}}
            }
            mock_ac = AsyncMock()
            mock_ac.post = AsyncMock(return_value=mock_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac

            resp = client.post(
                "/wallet/checkout",
                json={"amount": 25},
                headers={"Authorization": f"Bearer {auth_token}"},
            )

        assert resp.status_code == 200
        assert resp.json()["checkout_url"] == "https://checkout.lemonsqueezy.com/buy/test"


class TestLemonSqueezyWebhook:
    def _sig(self, body: bytes) -> str:
        from core.config import settings
        return hmac.new(
            settings.lemonsqueezy_webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()

    def test_invalid_signature(self, client):
        body = json.dumps({"meta": {"event_name": "order_created"}}).encode()
        resp = client.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": "badsig", "Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_order_created_updates_balance(self, client, mock_supabase):
        payload = {
            "meta": {
                "event_name": "order_created",
                "custom_data": {"user_id": "user-uuid"},
            },
            "data": {"attributes": {"total": 2500}},
        }
        body = json.dumps(payload).encode()
        sig = self._sig(body)

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"balance": "10.00"}
        ]
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        resp = client.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}

        update_call = mock_supabase.table.return_value.update
        update_call.assert_called_once_with({"balance": 35.0})

    def test_unknown_event_ignored(self, client):
        payload = {"meta": {"event_name": "subscription_created"}}
        body = json.dumps(payload).encode()
        sig = self._sig(body)
        resp = client.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}

    def test_order_created_missing_user_id(self, client):
        payload = {
            "meta": {"event_name": "order_created", "custom_data": {}},
            "data": {"attributes": {"total": 1000}},
        }
        body = json.dumps(payload).encode()
        sig = self._sig(body)
        resp = client.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400
