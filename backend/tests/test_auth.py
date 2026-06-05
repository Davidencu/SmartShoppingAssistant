from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCheckEmail:
    def test_not_exists(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        resp = client.post("/auth/check-email", json={"email": "new@example.com"})
        assert resp.status_code == 200
        assert resp.json() == {"exists": False}

    def test_exists(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "some-uuid"}
        ]
        resp = client.post("/auth/check-email", json={"email": "existing@example.com"})
        assert resp.status_code == 200
        assert resp.json() == {"exists": True}

    def test_invalid_email_format(self, client):
        resp = client.post("/auth/check-email", json={"email": "notanemail"})
        assert resp.status_code == 422

    def test_missing_at_symbol(self, client):
        resp = client.post("/auth/check-email", json={"email": "userdomain.com"})
        assert resp.status_code == 422


class TestSendOtp:
    def test_invalid_email_format(self, client):
        resp = client.post(
            "/auth/send-otp",
            json={
                "email": "bad",
                "phone": "+40712345678",
                "city": "City",
                "country": "RO",
            },
        )
        assert resp.status_code == 422

    def test_invalid_phone_format(self, client):
        resp = client.post(
            "/auth/send-otp",
            json={
                "email": "test@example.com",
                "phone": "0712345678",  # missing + prefix
                "city": "City",
                "country": "RO",
            },
        )
        assert resp.status_code == 422

    def test_already_registered(self, client, mock_supabase, valid_user_data):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "uuid"}
        ]
        resp = client.post("/auth/send-otp", json=valid_user_data)
        assert resp.status_code == 409

    def test_success(self, client, mock_supabase, valid_user_data):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        with patch("routers.auth.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_ac = AsyncMock()
            mock_ac.post = AsyncMock(return_value=mock_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac

            resp = client.post("/auth/send-otp", json=valid_user_data)

        assert resp.status_code == 200
        assert "OTP" in resp.json()["message"]


class TestVerifyOtp:
    def test_invalid_otp(self, client):
        with patch("routers.auth.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_ac = AsyncMock()
            mock_ac.post = AsyncMock(return_value=mock_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac

            resp = client.post(
                "/auth/verify-otp", json={"email": "test@example.com", "otp": "000000"}
            )
        assert resp.status_code == 400

    def test_success(self, client, mock_supabase):
        import routers.auth as auth_module

        auth_module._registration_data["test@example.com"] = {
            "phone": "+40712345678",
            "city": "City",
            "state": None,
            "country": "RO",
        }

        with patch("routers.auth.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"user": {"id": "new-user-uuid"}}
            mock_ac = AsyncMock()
            mock_ac.post = AsyncMock(return_value=mock_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac

            mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

            resp = client.post(
                "/auth/verify-otp", json={"email": "test@example.com", "otp": "123456"}
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "new-user-uuid"
        assert "options" in data


class TestPasskeyRegister:
    def test_no_challenge(self, client):
        import routers.auth as auth_module

        auth_module._challenges.pop("nochal@example.com", None)
        resp = client.post(
            "/auth/passkey/register",
            json={"email": "nochal@example.com", "credential": {}},
        )
        assert resp.status_code == 400

    def test_missing_registration_data(self, client):
        import routers.auth as auth_module

        auth_module._challenges["ghost@example.com"] = b"challenge"
        auth_module._registration_data.pop("ghost@example.com", None)

        resp = client.post(
            "/auth/passkey/register",
            json={"email": "ghost@example.com", "credential": {"id": "x"}},
        )
        assert resp.status_code == 400

    def test_success(self, client, mock_supabase, mocker):
        import routers.auth as auth_module

        auth_module._challenges["test@example.com"] = b"test-challenge-bytes"
        auth_module._registration_data["test@example.com"] = {
            "user_id": "user-uuid",
            "phone": "+40712345678",
            "city": "Bucharest",
            "state": None,
            "country": "Romania",
        }
        mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock()

        mock_verification = MagicMock()
        mock_verification.credential_id = b"cred-id"
        mock_verification.credential_public_key = b"pub-key"
        mock_verification.sign_count = 0
        mocker.patch("routers.auth.verify_registration_response", return_value=mock_verification)

        resp = client.post(
            "/auth/passkey/register",
            json={"email": "test@example.com", "credential": {"id": "x", "type": "public-key"}},
        )
        assert resp.status_code == 200
        assert "token" in resp.json()
        # Profile and passkey inserted after biometric confirmation
        assert mock_supabase.table.return_value.insert.call_count == 2


class TestPasskeyChallenge:
    def test_user_not_found(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        resp = client.post("/auth/passkey/challenge", json={"email": "ghost@example.com"})
        assert resp.status_code == 404

    def test_success(self, client, mock_supabase):
        profile_result = MagicMock()
        profile_result.data = [{"id": "user-uuid"}]
        passkey_result = MagicMock()
        passkey_result.data = [{"credential_id": "Y3JlZC1pZA"}]

        def table_side(name: str):
            m = MagicMock()
            if name == "profiles":
                m.select.return_value.eq.return_value.execute.return_value = profile_result
            else:
                m.select.return_value.eq.return_value.execute.return_value = passkey_result
            return m

        mock_supabase.table.side_effect = table_side

        resp = client.post("/auth/passkey/challenge", json={"email": "test@example.com"})
        assert resp.status_code == 200
        assert "options" in resp.json()


class TestVerifyMagic:
    def test_invalid_token(self, client):
        with patch("routers.auth.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 401
            mock_ac = AsyncMock()
            mock_ac.get = AsyncMock(return_value=mock_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac

            resp = client.post("/auth/verify-magic", json={"access_token": "bad-token"})

        assert resp.status_code == 401

    def test_success(self, client):
        import routers.auth as auth_module

        auth_module._registration_data["test@example.com"] = {
            "phone": "+40712345678",
            "city": "Bucharest",
            "state": None,
            "country": "Romania",
        }

        with patch("routers.auth.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"id": "user-uuid", "email": "test@example.com"}
            mock_ac = AsyncMock()
            mock_ac.get = AsyncMock(return_value=mock_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac

            resp = client.post("/auth/verify-magic", json={"access_token": "valid-token"})

        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "user-uuid"
        assert data["email"] == "test@example.com"
        assert "options" in data
        # user_id stashed for passkey/register — no DB writes yet
        assert auth_module._registration_data["test@example.com"]["user_id"] == "user-uuid"

    def test_missing_registration_data(self, client):
        import routers.auth as auth_module

        auth_module._registration_data.pop("ghost@example.com", None)

        with patch("routers.auth.httpx.AsyncClient") as mock_cls:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"id": "user-uuid", "email": "ghost@example.com"}
            mock_ac = AsyncMock()
            mock_ac.get = AsyncMock(return_value=mock_resp)
            mock_ac.__aenter__ = AsyncMock(return_value=mock_ac)
            mock_ac.__aexit__ = AsyncMock(return_value=None)
            mock_cls.return_value = mock_ac

            resp = client.post("/auth/verify-magic", json={"access_token": "valid-token"})

        assert resp.status_code == 400


class TestPasskeyVerify:
    def test_no_challenge(self, client):
        import routers.auth as auth_module

        auth_module._challenges.pop("nochallenge@example.com", None)
        resp = client.post(
            "/auth/passkey/verify",
            json={"email": "nochallenge@example.com", "credential": {}},
        )
        assert resp.status_code == 400

    def test_success(self, client, mock_supabase, mocker):
        import routers.auth as auth_module

        auth_module._challenges["test@example.com"] = b"auth-challenge"

        passkey_result = MagicMock()
        passkey_result.data = [
            {
                "user_id": "user-uuid",
                "credential_id": "Y3JlZC1pZA",
                "public_key": "cHViLWtleQ",
                "sign_count": 0,
            }
        ]
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = passkey_result
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        mock_verification = MagicMock()
        mock_verification.new_sign_count = 1
        mocker.patch("routers.auth.verify_authentication_response", return_value=mock_verification)

        resp = client.post(
            "/auth/passkey/verify",
            json={"email": "test@example.com", "credential": {"id": "x", "type": "public-key"}},
        )
        assert resp.status_code == 200
        assert "token" in resp.json()
