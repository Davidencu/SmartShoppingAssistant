"""
Integration-style tests that exercise the login state machine as a sequence
of API calls, the same way a real frontend client would chain them.
"""
from unittest.mock import MagicMock, patch

import pytest


class TestLoginSequences:

    # Sequence A – unknown email → frontend should redirect to /register
    def test_seq_A_unknown_email(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        resp = client.post("/auth/check-email", json={"email": "new@example.com"})
        assert resp.status_code == 200
        assert resp.json() == {"exists": False}

    # Sequence B – full happy path: check → challenge → verify → token
    def test_seq_B_full_login_happy_path(self, client, mock_supabase, mocker):
        import routers.auth as auth_module

        # Step 1: email exists
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "user-uuid"}
        ]
        resp = client.post("/auth/check-email", json={"email": "user@example.com"})
        assert resp.json()["exists"] is True

        # Step 2: get challenge
        profile_result = MagicMock()
        profile_result.data = [{"id": "user-uuid"}]
        passkey_result = MagicMock()
        passkey_result.data = [{"credential_id": "Y3JlZC1pZA"}]

        def by_table(name):
            m = MagicMock()
            m.select.return_value.eq.return_value.execute.return_value = (
                profile_result if name == "profiles" else passkey_result
            )
            return m

        mock_supabase.table.side_effect = by_table
        resp = client.post("/auth/passkey/challenge", json={"email": "user@example.com"})
        assert resp.status_code == 200
        assert "options" in resp.json()

        # Step 3: verify credential
        auth_module._challenges["user@example.com"] = b"auth-challenge"
        mock_supabase.table.side_effect = None
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "user_id": "user-uuid",
                    "credential_id": "Y3JlZC1pZA",
                    "public_key": "cHViLWtleQ",
                    "sign_count": 0,
                }
            ]
        )
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        mock_ver = MagicMock()
        mock_ver.new_sign_count = 1
        mocker.patch("routers.auth.verify_authentication_response", return_value=mock_ver)

        resp = client.post(
            "/auth/passkey/verify",
            json={"email": "user@example.com", "credential": {"id": "x", "type": "public-key"}},
        )
        assert resp.status_code == 200
        assert "token" in resp.json()

    # Sequence C – profile exists but no passkey → challenge returns 404
    def test_seq_C_no_passkey_blocks_login(self, client, mock_supabase):
        profile_result = MagicMock()
        profile_result.data = [{"id": "user-uuid"}]
        passkey_result = MagicMock()
        passkey_result.data = []  # passkey not enrolled yet

        def by_table(name):
            m = MagicMock()
            m.select.return_value.eq.return_value.execute.return_value = (
                profile_result if name == "profiles" else passkey_result
            )
            return m

        mock_supabase.table.side_effect = by_table
        resp = client.post("/auth/passkey/challenge", json={"email": "user@example.com"})
        assert resp.status_code == 404

    # Sequence D – challenge issued, biometric signature rejected → 401
    def test_seq_D_wrong_credential_rejected(self, client, mock_supabase, mocker):
        import routers.auth as auth_module

        auth_module._challenges["user@example.com"] = b"auth-challenge"
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "user_id": "user-uuid",
                    "credential_id": "Y3JlZC1pZA",
                    "public_key": "cHViLWtleQ",
                    "sign_count": 0,
                }
            ]
        )
        mocker.patch(
            "routers.auth.verify_authentication_response",
            side_effect=Exception("Signature verification failed"),
        )

        resp = client.post(
            "/auth/passkey/verify",
            json={"email": "user@example.com", "credential": {"id": "x", "type": "public-key"}},
        )
        assert resp.status_code == 401
        assert "Passkey verification failed" in resp.json()["detail"]

    # Sequence E – verify called with no prior challenge → 400
    def test_seq_E_verify_without_challenge_rejected(self, client):
        import routers.auth as auth_module

        auth_module._challenges.pop("stale@example.com", None)
        resp = client.post(
            "/auth/passkey/verify",
            json={"email": "stale@example.com", "credential": {"id": "x"}},
        )
        assert resp.status_code == 400

    # Sequence F – profile not found → challenge gate returns 404
    def test_seq_F_unknown_profile_blocks_challenge(self, client, mock_supabase):
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        resp = client.post("/auth/passkey/challenge", json={"email": "ghost@example.com"})
        assert resp.status_code == 404

    # Sequence G – second challenge overwrites the first
    def test_seq_G_second_challenge_replaces_first(self, client, mock_supabase):
        import routers.auth as auth_module

        profile_result = MagicMock()
        profile_result.data = [{"id": "user-uuid"}]
        passkey_result = MagicMock()
        passkey_result.data = [{"credential_id": "Y3JlZC1pZA"}]

        def by_table(name):
            m = MagicMock()
            m.select.return_value.eq.return_value.execute.return_value = (
                profile_result if name == "profiles" else passkey_result
            )
            return m

        mock_supabase.table.side_effect = by_table

        client.post("/auth/passkey/challenge", json={"email": "user@example.com"})
        first = auth_module._challenges.get("user@example.com")

        client.post("/auth/passkey/challenge", json={"email": "user@example.com"})
        second = auth_module._challenges.get("user@example.com")

        assert first is not None
        assert second is not None
        # WebAuthn challenges are cryptographically random — they must differ
        assert first != second

    # Sequence H – successful login clears the challenge (no replay)
    def test_seq_H_challenge_consumed_after_verify(self, client, mock_supabase, mocker):
        import routers.auth as auth_module

        auth_module._challenges["user@example.com"] = b"auth-challenge"
        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "user_id": "user-uuid",
                    "credential_id": "Y3JlZC1pZA",
                    "public_key": "cHViLWtleQ",
                    "sign_count": 0,
                }
            ]
        )
        mock_supabase.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

        mock_ver = MagicMock()
        mock_ver.new_sign_count = 1
        mocker.patch("routers.auth.verify_authentication_response", return_value=mock_ver)

        # First verify succeeds
        resp = client.post(
            "/auth/passkey/verify",
            json={"email": "user@example.com", "credential": {"id": "x", "type": "public-key"}},
        )
        assert resp.status_code == 200

        # Replaying the same request with no active challenge → 400
        resp2 = client.post(
            "/auth/passkey/verify",
            json={"email": "user@example.com", "credential": {"id": "x", "type": "public-key"}},
        )
        assert resp2.status_code == 400
