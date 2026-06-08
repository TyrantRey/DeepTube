"""Bring-your-own-key (BYOK) tests: client factory resolution + /config endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agent_fyp import config, llm
from agent_fyp.api import app as app_module

client = TestClient(app_module.app)


# ── llm.get_genai_client (key resolution) ────────────────────────────────────


def test_user_key_preferred_over_server_key(monkeypatch):
    """A caller-supplied key wins over the server's GOOGLE_API_KEY."""
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        llm, "_client_for_key", lambda key: captured.setdefault("key", key) or object()
    )

    llm.get_genai_client("user-key")
    assert captured["key"] == "user-key"


def test_falls_back_to_server_key(monkeypatch):
    """With no caller key, the server's GOOGLE_API_KEY is used (set to 'test-key')."""
    captured: dict[str, str] = {}
    monkeypatch.setattr(
        llm, "_client_for_key", lambda key: captured.setdefault("key", key) or object()
    )

    llm.get_genai_client(None)
    assert captured["key"] == "test-key"  # from conftest's GOOGLE_API_KEY


def test_missing_key_raises(monkeypatch):
    """No caller key and no server key -> MissingApiKeyError (actionable failure)."""
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    config.get_settings.cache_clear()

    with pytest.raises(llm.MissingApiKeyError):
        llm.get_genai_client(None)


# ── GET /config ──────────────────────────────────────────────────────────────


def test_config_reports_no_key_required_when_server_has_one():
    """conftest sets GOOGLE_API_KEY, so the server does not require a user key."""
    body = client.get("/config").json()
    assert body["requires_api_key"] is False
    assert body["gemini_model"]  # the configured model is surfaced


def test_config_requires_key_when_server_has_none(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "")
    config.get_settings.cache_clear()

    body = client.get("/config").json()
    assert body["requires_api_key"] is True
