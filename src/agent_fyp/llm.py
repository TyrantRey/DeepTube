"""Shared google-genai client factory with bring-your-own-key (BYOK) support.

A deployed instance can let each user supply their own Google Gemini API key,
sent per request as the ``X-Gemini-Api-Key`` header. The LLM tools (summary,
chat, mermaid) resolve the effective key here: the caller-supplied key when
present, otherwise the server's ``GOOGLE_API_KEY``. Clients are cached per
distinct key so repeated calls reuse one connection pool.
"""

from __future__ import annotations

from functools import lru_cache

from google import genai

from .config import get_settings


class MissingApiKeyError(RuntimeError):
    """No Gemini API key available (neither user-supplied nor server-configured)."""


@lru_cache(maxsize=16)
def _client_for_key(api_key: str) -> genai.Client:
    """Return a cached google-genai client for a specific (non-empty) API key."""
    return genai.Client(api_key=api_key)


def resolve_api_key(api_key: str | None = None) -> str:
    """Resolve the effective key: the user's if given, else the server's (may be "")."""
    return (api_key or "").strip() or get_settings().google_api_key.strip()


def server_has_api_key() -> bool:
    """True when the server itself holds a fallback ``GOOGLE_API_KEY``."""
    return bool(get_settings().google_api_key.strip())


def get_genai_client(api_key: str | None = None) -> genai.Client:
    """Return a google-genai client, preferring ``api_key`` over the server key.

    Raises :class:`MissingApiKeyError` when neither a user key nor a server key
    is available, so callers can surface a clear "please add your API key" error
    instead of a generic SDK failure.
    """
    key = resolve_api_key(api_key)
    if not key:
        raise MissingApiKeyError(
            "未提供 Gemini API 金鑰：請在設定中輸入你自己的 "
            "Google Gemini API key（可至 Google AI Studio 免費取得）。"
        )
    return _client_for_key(key)
