import json

import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock

from main import app


# ── SSE helpers ───────────────────────────────────────────────────────────────
# /search/chat is a streaming SSE endpoint. TestClient collects the full body:
#   data: {"type": "status", "message": "..."}\n\n
#   data: {"type": "result", "data": {...}}\n\n
# Use these helpers instead of resp.json() in all mock tests.

def sse_events(resp) -> list[dict]:
    """Return all parsed SSE events from a TestClient response."""
    events = []
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


def sse_result(resp) -> dict:
    """Return the payload of the final 'result' event (ChatResponse dict)."""
    for ev in sse_events(resp):
        if ev.get("type") == "result":
            return ev["data"]
    raise AssertionError(f"No result event in SSE stream:\n{resp.text[:600]}")


def sse_statuses(resp) -> list[str]:
    """Return the 'message' of every status event in arrival order."""
    return [ev["message"] for ev in sse_events(resp) if ev.get("type") == "status"]


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
        "city": "Bucharest",
        "state": None,
        "country": "Romania",
    }


@pytest.fixture
def auth_token():
    from routers.auth import create_token
    return create_token("test-user-uuid", "test@example.com")
