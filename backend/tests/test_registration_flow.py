"""
Integration sequences for the full registration and plan-selection state machine.
Tests the magic-link path: send-otp → verify-magic → passkey/register → plan/select|checkout.
Each sequence exercises several endpoints as a chained client interaction, the same way
a real frontend would drive them.
"""
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose import jwt

from core.config import settings


# Fixtures

@pytest.fixture(autouse=True)
def clean_auth_state():
    """Wipe in-memory dicts before and after every test to prevent leakage."""
    import routers.auth as m
    m._challenges.clear()
    m._registration_data.clear()
    yield
    m._challenges.clear()
    m._registration_data.clear()


@pytest.fixture(autouse=True)
def reset_store_id():
    import routers.plan as m
    m._ls_store_id = None
    yield
    m._ls_store_id = None


# Helpers

REG = {
    "email": "alice@example.com",
    "phone": "+40712345678",
    "street_address": "10 Main St",
    "city": "Bucharest",
    "postal_code": "010101",
    "country": "Romania",
}


def _patch_otp_send(mocker, status: int = 200):
    mock_resp = MagicMock(status_code=status)
    mock_ac = AsyncMock()
    mock_ac.post = AsyncMock(return_value=mock_resp)
    mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
    mock_ac.__aexit__ = AsyncMock(return_value=None)
    mocker.patch("routers.auth.httpx.AsyncClient", return_value=mock_ac)


def _patch_magic_link(mocker, user_id: str, email: str, status: int = 200):
    mock_resp = MagicMock(status_code=status)
    mock_resp.json.return_value = {"id": user_id, "email": email}
    mock_ac = AsyncMock()
    mock_ac.get = AsyncMock(return_value=mock_resp)
    mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
    mock_ac.__aexit__ = AsyncMock(return_value=None)
    mocker.patch("routers.auth.httpx.AsyncClient", return_value=mock_ac)


def _patch_passkey_verification(mocker):
    mv = MagicMock()
    mv.credential_id = b"cred-id"
    mv.credential_public_key = b"pub-key"
    mv.sign_count = 0
    mocker.patch("routers.auth.verify_registration_response", return_value=mv)
    return mv


def _webhook_body_and_sig(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    sig = hmac.new(
        settings.lemonsqueezy_webhook_secret.encode(), body, hashlib.sha256
    ).hexdigest()
    return body, sig


def _no_profile(mock_supabase):
    mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []


# Seq A – Full happy path: register → free plan

class TestFullRegistrationToFreePlan:

    def test_seq_A_send_otp_stores_registration_data(self, client, mock_supabase, mocker):
        import routers.auth as m
        _no_profile(mock_supabase)
        _patch_otp_send(mocker)
        resp = client.post("/auth/send-otp", json=REG)
        assert resp.status_code == 200
        assert "OTP" in resp.json()["message"]
        reg = m._registration_data.get("alice@example.com")
        assert reg is not None
        assert reg["phone"] == "+40712345678"
        assert reg["city"] == "Bucharest"
        assert "user_id" not in reg  # not yet — DB write deferred until biometric

    def test_seq_A_verify_magic_stashes_user_id_no_db_write(self, client, mock_supabase, mocker):
        import routers.auth as m
        m._registration_data["alice@example.com"] = {
            "phone": "+40712345678", "street_address": "10 Main St",
            "city": "Bucharest", "postal_code": "010101", "country": "Romania",
        }
        _patch_magic_link(mocker, "user-uuid-a", "alice@example.com")
        resp = client.post("/auth/verify-magic", json={"access_token": "tok"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "user-uuid-a"
        assert resp.json()["email"] == "alice@example.com"
        assert "options" in resp.json()
        assert m._registration_data["alice@example.com"]["user_id"] == "user-uuid-a"
        # No DB inserts before biometric
        mock_supabase.table.return_value.insert.assert_not_called()

    def test_seq_A_passkey_register_creates_profile_and_passkey_only(self, client, mock_supabase, mocker):
        import routers.auth as m
        m._challenges["alice@example.com"] = b"challenge"
        m._registration_data["alice@example.com"] = {
            "user_id": "user-uuid-a",
            "phone": "+40712345678", "street_address": "10 Main St",
            "city": "Bucharest", "postal_code": "010101", "country": "Romania",
        }
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        _patch_passkey_verification(mocker)
        resp = client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x", "type": "public-key"}},
        )
        assert resp.status_code == 200
        assert "token" in resp.json()
        # Exactly 2 inserts: profiles + passkeys — no wallet
        assert mock_supabase.table.return_value.insert.call_count == 2
        tables_inserted = [
            call.args[0] if call.args else list(call.kwargs.values())[0]
            for call in mock_supabase.table.call_args_list
            if mock_supabase.table.return_value.insert.called
        ]
        assert "alice@example.com" not in m._challenges
        assert "alice@example.com" not in m._registration_data

    def test_seq_A_full_chain_to_free_plan(self, client, mock_supabase, mocker):
        import routers.auth as m
        # send-otp
        _no_profile(mock_supabase)
        _patch_otp_send(mocker)
        assert client.post("/auth/send-otp", json=REG).status_code == 200
        # verify-magic
        _patch_magic_link(mocker, "user-uuid-a", "alice@example.com")
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        verify_resp = client.post("/auth/verify-magic", json={"access_token": "tok"})
        assert verify_resp.status_code == 200
        # passkey/register
        _patch_passkey_verification(mocker)
        reg_resp = client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x", "type": "public-key"}},
        )
        assert reg_resp.status_code == 200
        token = reg_resp.json()["token"]
        # plan/select free
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        plan_resp = client.post(
            "/plan/select", json={"plan": "free"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert plan_resp.status_code == 200
        assert plan_resp.json() == {"plan": "free", "checkout_credits": 2}


# Seq B – Full happy path: register → pro plan via checkout + webhook

class TestFullRegistrationToProPlan:

    def _register_and_get_token(self, client, mock_supabase, mocker) -> str:
        import routers.auth as m
        _no_profile(mock_supabase)
        _patch_otp_send(mocker)
        client.post("/auth/send-otp", json=REG)
        _patch_magic_link(mocker, "user-uuid-b", "alice@example.com")
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        client.post("/auth/verify-magic", json={"access_token": "tok"})
        _patch_passkey_verification(mocker)
        resp = client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x", "type": "public-key"}},
        )
        return resp.json()["token"]

    def test_seq_B_checkout_url_returned(self, client, mock_supabase, mocker):
        import routers.plan as plan_module
        token = self._register_and_get_token(client, mock_supabase, mocker)
        plan_module._ls_store_id = "store-x"

        with patch("routers.plan.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock(status_code=201)
            mock_resp.json.return_value = {
                "data": {"attributes": {"url": "https://checkout.ls.com/pro"}}
            }
            mock_ac = AsyncMock()
            mock_ac.post = AsyncMock(return_value=mock_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac
            resp = client.post("/plan/checkout", headers={"Authorization": f"Bearer {token}"})

        assert resp.status_code == 200
        assert resp.json()["checkout_url"] == "https://checkout.ls.com/pro"

    def test_seq_B_webhook_upgrades_plan_to_pro(self, client, mock_supabase, mocker):
        token = self._register_and_get_token(client, mock_supabase, mocker)
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        payload = {"meta": {"event_name": "order_created", "custom_data": {"user_id": "user-uuid-b"}}}
        body, sig = _webhook_body_and_sig(payload)
        resp = client.post(
            "/webhooks/lemonsqueezy", content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        mock_supabase.table.return_value.update.assert_called_with({"plan": "pro"})

    def test_seq_B_plan_status_reflects_pro_after_webhook(self, client, mock_supabase, mocker):
        token = self._register_and_get_token(client, mock_supabase, mocker)
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        payload = {"meta": {"event_name": "subscription_created", "custom_data": {"user_id": "user-uuid-b"}}}
        body, sig = _webhook_body_and_sig(payload)
        client.post(
            "/webhooks/lemonsqueezy", content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"plan": "pro", "checkout_credits": 0}
        ]
        resp = client.get("/plan/status", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["plan"] == "pro"
        assert resp.json()["checkout_credits"] == 0


# Seq C – Duplicate email blocked at send-otp

class TestDuplicateEmailBlocked:

    def test_seq_C_409_and_data_not_stored(self, client, mock_supabase):
        import routers.auth as m
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "existing-uuid"}
        ]
        resp = client.post("/auth/send-otp", json=REG)
        assert resp.status_code == 409
        assert "already registered" in resp.json()["detail"].lower()
        assert "alice@example.com" not in m._registration_data

    def test_seq_C_after_409_login_still_works(self, client, mock_supabase, mocker):
        """Existing user can still log in after a 409 on send-otp."""
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "existing-uuid"}
        ]
        assert client.post("/auth/send-otp", json=REG).status_code == 409

        # Login path: check-email returns exists=True
        resp = client.post("/auth/check-email", json={"email": "alice@example.com"})
        assert resp.json()["exists"] is True


# Seq D – verify-magic edge cases

class TestVerifyMagicEdgeCases:

    def test_seq_D_bad_supabase_token_returns_401_data_intact(self, client, mocker):
        import routers.auth as m
        m._registration_data["alice@example.com"] = {"phone": "+40712345678"}
        _patch_magic_link(mocker, "", "", status=401)
        resp = client.post("/auth/verify-magic", json={"access_token": "bad-tok"})
        assert resp.status_code == 401
        assert "alice@example.com" in m._registration_data

    def test_seq_E_no_prior_send_otp_returns_400(self, client, mocker):
        _patch_magic_link(mocker, "user-x", "ghost@example.com")
        resp = client.post("/auth/verify-magic", json={"access_token": "tok"})
        assert resp.status_code == 400

    def test_verify_magic_challenge_generated_for_next_step(self, client, mocker):
        import routers.auth as m
        m._registration_data["alice@example.com"] = {
            "phone": "+40712345678", "street_address": "10 St",
            "city": "Bucharest", "postal_code": "010101", "country": "Romania",
        }
        _patch_magic_link(mocker, "user-uuid-v", "alice@example.com")
        client.post("/auth/verify-magic", json={"access_token": "tok"})
        assert "alice@example.com" in m._challenges
        assert isinstance(m._challenges["alice@example.com"], bytes)
        assert len(m._challenges["alice@example.com"]) > 0


# Seq F – passkey/register error cases

class TestPasskeyRegisterErrorCases:

    def test_seq_F_invalid_credential_returns_400(self, client, mock_supabase, mocker):
        import routers.auth as m
        m._challenges["alice@example.com"] = b"challenge"
        m._registration_data["alice@example.com"] = {
            "user_id": "uid", "phone": "+40712345678",
            "street_address": "10 St", "city": "Bucharest",
            "postal_code": "010101", "country": "Romania",
        }
        mocker.patch("routers.auth.verify_registration_response", side_effect=Exception("bad cred"))
        resp = client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x"}},
        )
        assert resp.status_code == 400
        assert "Passkey registration failed" in resp.json()["detail"]

    def test_seq_G_successful_register_clears_state_replay_blocked(self, client, mock_supabase, mocker):
        import routers.auth as m
        m._challenges["alice@example.com"] = b"challenge"
        m._registration_data["alice@example.com"] = {
            "user_id": "uid", "phone": "+40712345678",
            "street_address": "10 St", "city": "Bucharest",
            "postal_code": "010101", "country": "Romania",
        }
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        _patch_passkey_verification(mocker)

        assert client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x", "type": "public-key"}},
        ).status_code == 200

        # Replay: no challenge → 400
        assert client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x", "type": "public-key"}},
        ).status_code == 400

    def test_seq_P_missing_user_id_in_registration_data_returns_400(self, client):
        import routers.auth as m
        m._challenges["alice@example.com"] = b"challenge"
        m._registration_data["alice@example.com"] = {
            # user_id intentionally absent — verify-magic never called
            "phone": "+40712345678", "street_address": "10 St",
            "city": "Bucharest", "postal_code": "010101", "country": "Romania",
        }
        resp = client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x"}},
        )
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower()


# Seq H – JWT token integrity

class TestJwtIntegrity:

    def test_seq_H_token_encodes_correct_claims(self, client, mock_supabase, mocker):
        import routers.auth as m
        m._challenges["alice@example.com"] = b"challenge"
        m._registration_data["alice@example.com"] = {
            "user_id": "correct-uuid", "phone": "+40712345678",
            "street_address": "10 St", "city": "Bucharest",
            "postal_code": "010101", "country": "Romania",
        }
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        _patch_passkey_verification(mocker)

        token = client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x", "type": "public-key"}},
        ).json()["token"]

        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        assert claims["sub"] == "correct-uuid"
        assert claims["email"] == "alice@example.com"
        assert "exp" in claims

    def test_seq_H_token_accepted_by_protected_endpoints(self, client, mock_supabase, mocker):
        import routers.auth as m
        m._challenges["alice@example.com"] = b"challenge"
        m._registration_data["alice@example.com"] = {
            "user_id": "uid-plan", "phone": "+40712345678",
            "street_address": "10 St", "city": "Bucharest",
            "postal_code": "010101", "country": "Romania",
        }
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        _patch_passkey_verification(mocker)
        token = client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x", "type": "public-key"}},
        ).json()["token"]

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"plan": "free", "checkout_credits": 2}
        ]
        resp = client.get("/plan/status", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_tampered_token_rejected(self, client):
        resp = client.get("/plan/status", headers={"Authorization": "Bearer tampered.jwt.token"})
        assert resp.status_code == 401

    def test_missing_token_rejected(self, client):
        resp = client.get("/plan/status")
        assert resp.status_code == 401


# Seq I – Concurrent registrations are isolated

class TestConcurrentRegistrations:

    def test_seq_I_two_emails_do_not_interfere(self, client, mock_supabase, mocker):
        import routers.auth as m
        _no_profile(mock_supabase)
        _patch_otp_send(mocker)

        client.post("/auth/send-otp", json=REG)
        client.post("/auth/send-otp", json={**REG, "email": "bob@example.com"})

        assert "alice@example.com" in m._registration_data
        assert "bob@example.com" in m._registration_data

        # Alice verifies; Bob's state is untouched
        _patch_magic_link(mocker, "uuid-alice", "alice@example.com")
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        client.post("/auth/verify-magic", json={"access_token": "alice-tok"})

        assert m._registration_data["alice@example.com"]["user_id"] == "uuid-alice"
        assert "user_id" not in m._registration_data.get("bob@example.com", {})

    def test_seq_J_new_send_otp_overwrites_stale_data(self, client, mock_supabase, mocker):
        import routers.auth as m
        _no_profile(mock_supabase)
        _patch_otp_send(mocker)

        client.post("/auth/send-otp", json={**REG, "street_address": "Old St 1"})
        assert m._registration_data["alice@example.com"]["street_address"] == "Old St 1"

        client.post("/auth/send-otp", json={**REG, "street_address": "New St 99"})
        assert m._registration_data["alice@example.com"]["street_address"] == "New St 99"


# Plan endpoint integration

class TestPlanEndpointIntegration:

    def test_seq_K_plan_status_missing_auth(self, client):
        assert client.get("/plan/status").status_code == 401

    def test_seq_K_plan_status_invalid_jwt(self, client):
        assert client.get(
            "/plan/status", headers={"Authorization": "Bearer bad.jwt"}
        ).status_code == 401

    def test_seq_K_plan_status_free_user(self, client, mock_supabase, auth_token):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"plan": "free", "checkout_credits": 2}
        ]
        resp = client.get("/plan/status", headers={"Authorization": f"Bearer {auth_token}"})
        assert resp.status_code == 200
        assert resp.json() == {"plan": "free", "checkout_credits": 2}

    def test_seq_K_plan_status_pro_user(self, client, mock_supabase, auth_token):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"plan": "pro", "checkout_credits": 0}
        ]
        resp = client.get("/plan/status", headers={"Authorization": f"Bearer {auth_token}"})
        assert resp.json() == {"plan": "pro", "checkout_credits": 0}

    def test_seq_L_plan_select_pro_blocked_with_422(self, client, auth_token):
        resp = client.post(
            "/plan/select", json={"plan": "pro"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 422

    def test_seq_L_plan_select_free_accepted(self, client, mock_supabase, auth_token):
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        resp = client.post(
            "/plan/select", json={"plan": "free"},
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["plan"] == "free"

    def test_seq_M_checkout_store_id_cached_across_calls(self, client, auth_token):
        import routers.plan as plan_module
        plan_module._ls_store_id = None

        store_resp = MagicMock(status_code=200)
        store_resp.json.return_value = {"data": [{"id": "fetched-id"}]}
        checkout_resp = MagicMock(status_code=201)
        checkout_resp.json.return_value = {"data": {"attributes": {"url": "https://checkout.ls.com"}}}

        with patch("routers.plan.httpx.AsyncClient") as mock_cls:
            mock_ac = AsyncMock()
            mock_ac.get = AsyncMock(return_value=store_resp)
            mock_ac.post = AsyncMock(return_value=checkout_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac

            client.post("/plan/checkout", headers={"Authorization": f"Bearer {auth_token}"})
            assert mock_ac.get.call_count == 1
            assert plan_module._ls_store_id == "fetched-id"

            # Second call: store_id cached, no GET
            client.post("/plan/checkout", headers={"Authorization": f"Bearer {auth_token}"})
            assert mock_ac.get.call_count == 1

    def test_seq_M_checkout_store_fetch_failure_returns_502(self, client, auth_token):
        import routers.plan as plan_module
        plan_module._ls_store_id = None

        with patch("routers.plan.httpx.AsyncClient") as mock_cls:
            mock_ac = AsyncMock()
            mock_ac.get = AsyncMock(return_value=MagicMock(status_code=503))
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac
            resp = client.post("/plan/checkout", headers={"Authorization": f"Bearer {auth_token}"})

        assert resp.status_code == 502

    def test_seq_M_checkout_ls_creation_failure_returns_502(self, client, auth_token):
        import routers.plan as plan_module
        plan_module._ls_store_id = "store-123"

        with patch("routers.plan.httpx.AsyncClient") as mock_cls:
            mock_ac = AsyncMock()
            mock_ac.post = AsyncMock(return_value=MagicMock(status_code=422))
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac
            resp = client.post("/plan/checkout", headers={"Authorization": f"Bearer {auth_token}"})

        assert resp.status_code == 502

    def test_seq_M_checkout_empty_store_list_returns_502(self, client, auth_token):
        import routers.plan as plan_module
        plan_module._ls_store_id = None

        store_resp = MagicMock(status_code=200)
        store_resp.json.return_value = {"data": []}  # no stores

        with patch("routers.plan.httpx.AsyncClient") as mock_cls:
            mock_ac = AsyncMock()
            mock_ac.get = AsyncMock(return_value=store_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac
            resp = client.post("/plan/checkout", headers={"Authorization": f"Bearer {auth_token}"})

        assert resp.status_code == 502


# Seq N/O – Webhook integration

class TestWebhookIntegration:

    def test_seq_N_order_created_upgrades_plan(self, client, mock_supabase):
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        payload = {"meta": {"event_name": "order_created", "custom_data": {"user_id": "uid"}}}
        body, sig = _webhook_body_and_sig(payload)
        resp = client.post(
            "/webhooks/lemonsqueezy", content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        mock_supabase.table.return_value.update.assert_called_with({"plan": "pro"})

    def test_seq_O_subscription_created_also_upgrades(self, client, mock_supabase):
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        payload = {"meta": {"event_name": "subscription_created", "custom_data": {"user_id": "uid"}}}
        body, sig = _webhook_body_and_sig(payload)
        resp = client.post(
            "/webhooks/lemonsqueezy", content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        mock_supabase.table.return_value.update.assert_called_with({"plan": "pro"})

    def test_seq_O_webhook_replay_idempotent(self, client, mock_supabase):
        """Receiving the same webhook twice both succeed (DB upsert is idempotent)."""
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        payload = {"meta": {"event_name": "order_created", "custom_data": {"user_id": "uid"}}}
        body, sig = _webhook_body_and_sig(payload)
        headers = {"X-Signature": sig, "Content-Type": "application/json"}
        assert client.post("/webhooks/lemonsqueezy", content=body, headers=headers).status_code == 200
        assert client.post("/webhooks/lemonsqueezy", content=body, headers=headers).status_code == 200

    def test_webhook_invalid_signature_blocked(self, client):
        body = json.dumps({"meta": {"event_name": "order_created"}}).encode()
        resp = client.post(
            "/webhooks/lemonsqueezy", content=body,
            headers={"X-Signature": "bad", "Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_webhook_missing_user_id_returns_400(self, client):
        payload = {"meta": {"event_name": "order_created", "custom_data": {}}}
        body, sig = _webhook_body_and_sig(payload)
        resp = client.post(
            "/webhooks/lemonsqueezy", content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 400

    def test_webhook_unknown_event_ignored(self, client):
        payload = {"meta": {"event_name": "refund_created"}}
        body, sig = _webhook_body_and_sig(payload)
        resp = client.post(
            "/webhooks/lemonsqueezy", content=body,
            headers={"X-Signature": sig, "Content-Type": "application/json"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"message": "ok"}
