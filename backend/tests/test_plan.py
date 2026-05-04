import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetPlanStatus:
    def test_unauthenticated(self, client):
        resp = client.get("/plan/status")
        assert resp.status_code == 401

    def test_success_free_plan(self, client, mock_supabase, auth_token):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"plan": "free", "checkout_credits": 2}
        ]
        resp = client.get(
            "/plan/status", headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"plan": "free", "checkout_credits": 2}

    def test_success_pro_plan(self, client, mock_supabase, auth_token):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"plan": "pro", "checkout_credits": 0}
        ]
        resp = client.get(
            "/plan/status", headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"plan": "pro", "checkout_credits": 0}

    def test_profile_not_found(self, client, mock_supabase, auth_token):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        resp = client.get(
            "/plan/status", headers={"Authorization": f"Bearer {auth_token}"}
        )
        assert resp.status_code == 404


class TestSelectFreePlan:
    def test_unauthenticated(self, client):
        resp = client.post("/plan/select", json={"plan": "free"})
        assert resp.status_code == 401

    def test_invalid_plan_value(self, client, auth_token):
        resp = client.post(
            "/plan/select",
            json={"plan": "pro"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 422

    def test_select_free_plan(self, client, mock_supabase, auth_token):
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        resp = client.post(
            "/plan/select",
            json={"plan": "free"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"plan": "free", "checkout_credits": 2}
        mock_supabase.table.return_value.update.assert_called_once_with({"plan": "free"})


class TestCreateProCheckout:
    def test_unauthenticated(self, client):
        resp = client.post("/plan/checkout")
        assert resp.status_code == 401

    def test_success_returns_checkout_url(self, client, auth_token):
        import routers.plan as plan_module
        plan_module._ls_store_id = "store-123"

        with patch("routers.plan.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 201
            mock_resp.json.return_value = {
                "data": {"attributes": {"url": "https://checkout.lemonsqueezy.com/buy/pro"}}
            }
            mock_ac = AsyncMock()
            mock_ac.post = AsyncMock(return_value=mock_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac

            resp = client.post(
                "/plan/checkout",
                headers={"Authorization": f"Bearer {auth_token}"},
            )

        assert resp.status_code == 200
        assert resp.json()["checkout_url"] == "https://checkout.lemonsqueezy.com/buy/pro"

    def test_lemonsqueezy_failure_returns_502(self, client, auth_token):
        import routers.plan as plan_module
        plan_module._ls_store_id = "store-123"

        with patch("routers.plan.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_ac = AsyncMock()
            mock_ac.post = AsyncMock(return_value=mock_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac

            resp = client.post(
                "/plan/checkout",
                headers={"Authorization": f"Bearer {auth_token}"},
            )

        assert resp.status_code == 502


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

    def test_order_created_upgrades_to_pro(self, client, mock_supabase):
        payload = {
            "meta": {
                "event_name": "order_created",
                "custom_data": {"user_id": "user-uuid"},
            },
        }
        body = json.dumps(payload).encode()
        sig = self._sig(body)
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        resp = client.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}
        mock_supabase.table.return_value.update.assert_called_once_with({"plan": "pro"})

    def test_subscription_created_upgrades_to_pro(self, client, mock_supabase):
        payload = {
            "meta": {
                "event_name": "subscription_created",
                "custom_data": {"user_id": "user-uuid"},
            },
        }
        body = json.dumps(payload).encode()
        sig = self._sig(body)
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        resp = client.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        mock_supabase.table.return_value.update.assert_called_once_with({"plan": "pro"})

    def test_order_created_missing_user_id(self, client):
        payload = {
            "meta": {"event_name": "order_created", "custom_data": {}},
        }
        body = json.dumps(payload).encode()
        sig = self._sig(body)
        resp = client.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_unknown_event_ignored(self, client):
        payload = {"meta": {"event_name": "refund_created"}}
        body = json.dumps(payload).encode()
        sig = self._sig(body)
        resp = client.post(
            "/webhooks/lemonsqueezy",
            content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}
