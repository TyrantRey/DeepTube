"""Mermaid tool: turn a video summary into a Mermaid mindmap for the frontend."""

from __future__ import annotations

import re

from google import genai
from google.genai import types

from ..config import get_settings
from ..llm import get_genai_client

_SYSTEM_PROMPT = """\
你是一個知識圖譜助理。根據使用者提供的影片摘要，產生一張 Mermaid「mindmap」\
心智圖，呈現影片的核心主題與重點結構。

規則：
1. 只輸出有效的 Mermaid mindmap 語法，第一行必須是 `mindmap`。
2. 不要輸出任何說明文字，也不要使用 ``` 程式碼圍欄。
3. 根節點使用影片標題，格式為 root((標題))。
4. 節點文字要簡短（盡量在 12 個字以內），且不要在節點文字中使用 ()、[]、{}、" 等特殊符號。
5. 依摘要的重點建立 2 至 3 層的分支結構。
"""

_FENCE_RE = re.compile(r"```(?:mermaid)?\s*(.*?)```", re.DOTALL)

def _get_client(api_key: str | None = None) -> genai.Client:
    """Return a Gemini client, preferring the caller's key over the server key."""
    return get_genai_client(api_key)


def _strip_fences(text: str) -> str:
    """Remove any ``` fences the model may add, returning bare Mermaid source."""
    match = _FENCE_RE.search(text)
    if match:
        text = match.group(1)
    return text.strip()


def generate_mermaid(
    summary_md: str, title: str | None = None, api_key: str | None = None
) -> str:
    """Generate Mermaid mindmap syntax from the video summary."""
    settings = get_settings()
    client = _get_client(api_key)

    prompt = summary_md
    if title:
        prompt = f"影片標題：{title}\n\n{summary_md}"

    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            max_output_tokens=settings.mermaid_max_tokens,
        ),
    )
    mermaid = _strip_fences(response.text or "")
    if not mermaid.startswith("mindmap"):
        # Guarantee a parseable diagram even if the model drifts.
        mermaid = "mindmap\n  root((影片摘要))\n" + "\n".join(
            f"    {line.strip()}" for line in mermaid.splitlines() if line.strip()
        )
    return mermaid
