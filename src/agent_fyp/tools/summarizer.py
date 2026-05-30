"""Summarization tool: transcript -> Markdown summary via Gemini (google-genai).

`summarize_content` calls Gemini with a stable system instruction and the
transcript as the user content. When no ``video_type`` is supplied, Gemini
classifies the video and adapts the summary format; a caller-supplied
``video_type`` overrides the detected one.
"""

from __future__ import annotations

import re

from google import genai
from google.genai import types

from ..config import get_settings
from ..models import Summary, Transcript

# Stable system instruction guiding the summary format.
_SYSTEM_PROMPT = """\
你是一個 YouTube 影片知識萃取助理。你會收到一段帶有時間戳記的逐字稿，\
請產出一份結構化的 Markdown 重點摘要。

規則：
1. 使用逐字稿本身的語言撰寫摘要；若無法判斷，預設使用繁體中文。
2. 先判斷影片類型（例如：教學、講座、開箱、Vlog、新聞、訪談、評論、其他）。\
若使用者已指定影片類型，務必沿用使用者指定的類型。
3. 依影片類型調整「重點摘要」區段的呈現方式：
   - 教學 / 講座 / 評論：以重點條列呈現。
   - Vlog / 開箱 / 新聞：以時間軸（依時間順序）呈現。
   - 訪談 / 問答：以 Q&A（問題與回答）呈現。
4. 每個重點都要附上來自逐字稿的真實時間戳記，格式為 [MM:SS] 或 [H:MM:SS]。\
不要捏造時間戳記。

輸出格式（務必嚴格遵守，第一行為 HTML 註解，供程式解析影片類型）：

<!-- video_type: 影片類型 -->
# 影片標題

## 影片類型
影片類型

## 重點摘要
- [MM:SS] 重點一
- [MM:SS] 重點二
（依影片類型，可改為時間軸或 Q&A 形式，但每一條仍須附時間戳記）

## 小結
以一到兩段文字總結整支影片的核心內容與價值。

除上述 Markdown 內容外，不要輸出任何其他文字。"""

_VIDEO_TYPE_RE = re.compile(r"<!--\s*video_type:\s*(.+?)\s*-->", re.IGNORECASE)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Return a cached Gemini client (reads GOOGLE_API_KEY from settings/env)."""
    global _client
    if _client is None:
        settings = get_settings()
        _client = genai.Client(api_key=settings.google_api_key or None)
    return _client


def _build_user_prompt(transcript: Transcript, video_type: str | None) -> str:
    type_line = (
        f"使用者指定的影片類型：{video_type}"
        if video_type
        else "影片類型：請你自行判斷並填入。"
    )
    return (
        f"{type_line}\n\n"
        "以下是帶有時間戳記的逐字稿：\n\n"
        f"{transcript.timestamped_text()}"
    )


def summarize_content(
    transcript: Transcript, video_type: str | None = None
) -> Summary:
    """Summarize a transcript into Markdown, returning the (detected) video type."""
    settings = get_settings()
    client = _get_client()

    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=_build_user_prompt(transcript, video_type),
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            max_output_tokens=settings.summary_max_tokens,
        ),
    )

    markdown = (response.text or "").strip()

    detected = _VIDEO_TYPE_RE.search(markdown)
    resolved_type = video_type or (detected.group(1).strip() if detected else "其他")

    # Strip the machine-readable comment so the stored Markdown is clean.
    clean_markdown = _VIDEO_TYPE_RE.sub("", markdown, count=1).lstrip()

    return Summary(video_type=resolved_type, markdown=clean_markdown)
