"""
Integration sequences for the full registration state machine.
Tests the magic-link path: send-otp → verify-magic → passkey/register → /dashboard.
Each sequence exercises several endpoints as a chained client interaction, the same way
a real frontend would drive them.
"""
from unittest.mock import AsyncMock, MagicMock

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


# Helpers

REG = {
    "email": "alice@example.com",
    "phone": "+40712345678",
    "city": "Bucharest",
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
            "phone": "+40712345678",
            "city": "Bucharest", "state": None, "country": "Romania",
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
            "phone": "+40712345678",
            "city": "Bucharest", "state": None, "country": "Romania",
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

    def test_seq_A_full_chain_to_dashboard(self, client, mock_supabase, mocker):
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
        # passkey/register → token issued, user lands on /dashboard
        _patch_passkey_verification(mocker)
        reg_resp = client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x", "type": "public-key"}},
        )
        assert reg_resp.status_code == 200
        assert "token" in reg_resp.json()


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
            "phone": "+40712345678",
            "city": "Bucharest", "state": None, "country": "Romania",
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
            "city": "Bucharest", "state": None, "country": "Romania",
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
            "city": "Bucharest", "state": None, "country": "Romania",
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
            "phone": "+40712345678",
            "city": "Bucharest", "state": None, "country": "Romania",
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
            "city": "Bucharest", "state": None, "country": "Romania",
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
            "city": "Bucharest", "state": None, "country": "Romania",
        }
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()
        _patch_passkey_verification(mocker)
        token = client.post(
            "/auth/passkey/register",
            json={"email": "alice@example.com", "credential": {"id": "x", "type": "public-key"}},
        ).json()["token"]

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"entries": []}
        ]
        resp = client.get("/search/history", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_tampered_token_rejected(self, client):
        resp = client.get("/search/history", headers={"Authorization": "Bearer tampered.jwt.token"})
        assert resp.status_code == 401

    def test_missing_token_rejected(self, client):
        resp = client.get("/search/history")
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

        client.post("/auth/send-otp", json={**REG, "city": "Old City"})
        assert m._registration_data["alice@example.com"]["city"] == "Old City"

        client.post("/auth/send-otp", json={**REG, "city": "New City"})
        assert m._registration_data["alice@example.com"]["city"] == "New City"


