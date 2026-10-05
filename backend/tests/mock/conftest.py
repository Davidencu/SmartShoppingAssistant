import pytest


@pytest.fixture(autouse=True)
def _no_real_openai(mocker):
    """
    Never hit the real OpenAI API from mock tests.
    With no client, openai_router falls back to gemini_service.classify_intent
    (which tests mock), the sanity check fails open, and the fallback scorer
    returns []. Tests that need OpenAI behaviour patch openai_router functions directly.
    """
    mocker.patch("services.openai_router._openai_client", None)
