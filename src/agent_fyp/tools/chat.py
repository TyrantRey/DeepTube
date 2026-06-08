"""Chat tool: answer questions grounded in a single video's transcript via Gemini."""

from __future__ import annotations

import re

from google import genai
from google.genai import types

from ..config import get_settings

# Matches [MM:SS] or [H:MM:SS] timestamp markers the model is told to cite.
_TIMESTAMP_RE = re.compile(r"\[(\d{1,2}):(\d{2})(?::(\d{2}))?\]")

_SYSTEM_PROMPT = """\
你是一個影片問答助理。使用者會針對某一支 YouTube 影片提問，\
你只能根據以下提供的「影片逐字稿」內容作答。

規則：
1. 僅根據逐字稿回答；若逐字稿中沒有相關資訊，請明確說明「逐字稿中沒有提到」。
2. 使用與逐字稿相同的語言回答；若無法判斷，預設使用繁體中文。
3. 在適當時引用相關的時間戳記（格式 [MM:SS]）以佐證你的回答。
4. 回答力求精確、簡潔。

影片逐字稿：
"""

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Return a cached Gemini client (reads GOOGLE_API_KEY from settings/env)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = genai.Client(api_key=settings.google_api_key or None)
    return _client


def _to_contents(history: list[dict] | None, message: str) -> list[dict]:
    """Build the google-genai contents list from prior turns + the new message."""
    contents: list[dict] = []
    for turn in history or []:
        role = "model" if turn.get("role") in ("model", "assistant") else "user"
        contents.append({"role": role, "parts": [{"text": turn.get("content", "")}]})
    contents.append({"role": "user", "parts": [{"text": message}]})
    return contents


def chat_with_transcript(
    transcript_text: str, message: str, history: list[dict] | None = None
) -> str:
    """Answer ``message`` about a video, grounded in ``transcript_text``."""
    settings = get_settings()
    client = _get_client()

    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=_to_contents(history, message),
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT + transcript_text,
            max_output_tokens=settings.chat_max_tokens,
        ),
    )
    return (response.text or "").strip()


def _marker_to_seconds(match: re.Match) -> int:
    """Convert a matched [MM:SS] / [H:MM:SS] marker to seconds."""
    a, b, c = match.group(1), match.group(2), match.group(3)
    if c is None:
        return int(a) * 60 + int(b)  # MM:SS
    return int(a) * 3600 + int(b) * 60 + int(c)  # H:MM:SS


def extract_citations(answer: str, segments: list[dict]) -> list[dict]:
    """Map [MM:SS]/[H:MM:SS] markers in ``answer`` to supporting transcript segments.

    For each unique timestamp the model cited, pick the segment that covers it
    (greatest ``start <= t``, else the nearest) and use its text as the quote.
    Returns ``[{timestamp, start, quote}]`` in order of appearance, de-duplicated.
    """
    if not segments:
        return []
    ordered = sorted(segments, key=lambda s: float(s.get("start", 0.0)))

    citations: list[dict] = []
    seen: set[str] = set()
    for match in _TIMESTAMP_RE.finditer(answer):
        label = match.group(0).strip("[]")
        if label in seen:
            continue
        seen.add(label)

        t = _marker_to_seconds(match)
        covering = [s for s in ordered if float(s.get("start", 0.0)) <= t]
        chosen = (
            covering[-1]
            if covering
            else min(ordered, key=lambda s: abs(float(s.get("start", 0.0)) - t))
        )
        quote = (chosen.get("text") or "").strip()
        if len(quote) > 140:
            quote = quote[:140].rstrip() + "…"
        citations.append(
            {
                "timestamp": label,
                "start": float(chosen.get("start", 0.0)),
                "quote": quote,
            }
        )
    return citations
