"""Summarization tool: transcript -> Markdown summary via Gemini (google-genai).

`summarize_content` calls Gemini with a stable system instruction and the
transcript as the user content. When no ``video_type`` is supplied, Gemini
classifies the video and adapts the summary format; a caller-supplied
``video_type`` overrides the detected one.

Long videos (transcripts whose timestamped text exceeds
``summary_segment_char_threshold``) are summarized in segments and then merged
into a single structured summary, with per-segment progress reported through
:mod:`agent_fyp.progress`.
"""

from __future__ import annotations

import re

from google import genai
from google.genai import types

from .. import progress
from ..config import get_settings
from ..models import Segment, Summary, Transcript

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

# Per-segment extraction prompt for long videos.
_PARTIAL_SYSTEM_PROMPT = """\
你是一個影片知識萃取助理。以下是一支長影片「其中一個片段」的帶時間戳記逐字稿。\
請只萃取這個片段的重點，以條列方式輸出，每一點開頭附上來自逐字稿的真實時間戳記\
（格式 [MM:SS] 或 [H:MM:SS]），不要捏造時間戳記。只輸出條列重點，不要任何其他文字。"""

# Final merge prompt: combine per-segment bullet lists into one structured summary.
_MERGE_SYSTEM_PROMPT = """\
你是一個 YouTube 影片知識萃取助理。你會收到同一支長影片「各個片段」的重點條列\
（已依時間順序排列，每點都帶有真實時間戳記）。請將它們整合成一份結構化、不重複的\
Markdown 重點摘要。

規則：
1. 使用重點本身的語言撰寫；若無法判斷，預設使用繁體中文。
2. 先判斷影片類型（教學、講座、開箱、Vlog、新聞、訪談、評論、其他）。\
若使用者已指定影片類型，務必沿用使用者指定的類型。
3. 依影片類型調整「重點摘要」呈現方式（條列 / 時間軸 / Q&A），合併重複內容，\
保留涵蓋整支影片的重點，並沿用原有的真實時間戳記，不要捏造。
4. 重點數量精簡到能代表整支影片的程度即可（建議 6 至 12 點）。

輸出格式（務必嚴格遵守，第一行為 HTML 註解，供程式解析影片類型）：

<!-- video_type: 影片類型 -->
# 影片標題

## 影片類型
影片類型

## 重點摘要
- [MM:SS] 重點一
- [MM:SS] 重點二

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


def _parse_summary(markdown: str, video_type: str | None) -> Summary:
    """Pull the video type out of the model output and clean the Markdown."""
    markdown = (markdown or "").strip()
    detected = _VIDEO_TYPE_RE.search(markdown)
    resolved_type = video_type or (detected.group(1).strip() if detected else "其他")
    # Strip the machine-readable comment so the stored Markdown is clean.
    clean_markdown = _VIDEO_TYPE_RE.sub("", markdown, count=1).lstrip()
    return Summary(video_type=resolved_type, markdown=clean_markdown)


def _summarize_single(transcript: Transcript, video_type: str | None) -> Summary:
    """Single-call summarization (the fast path for normal-length videos)."""
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
    return _parse_summary(response.text or "", video_type)


def _chunk_segments_by_chars(
    segments: list[Segment], limit: int
) -> list[list[Segment]]:
    """Split segments into consecutive groups whose rendered text stays ≤ limit."""
    chunks: list[list[Segment]] = []
    current: list[Segment] = []
    size = 0
    for seg in segments:
        seg_len = len(seg.text) + 9  # rough "[MM:SS] " + newline overhead
        if current and size + seg_len > limit:
            chunks.append(current)
            current, size = [], 0
        current.append(seg)
        size += seg_len
    if current:
        chunks.append(current)
    return chunks


def _summarize_segmented(
    transcript: Transcript, video_type: str | None, run_id: str | None
) -> Summary:
    """Segment a long transcript, summarize each part, then merge the parts."""
    settings = get_settings()
    client = _get_client()

    chunks = _chunk_segments_by_chars(
        transcript.segments, settings.summary_segment_chunk_chars
    )
    total = len(chunks)
    progress.report(
        run_id, "summarizing", 0.4, f"長影片分段處理：共 {total} 段"
    )

    partials: list[str] = []
    for i, chunk in enumerate(chunks, start=1):
        part_transcript = Transcript(
            text=" ".join(s.text for s in chunk),
            segments=chunk,
            language=transcript.language,
            source=transcript.source,
        )
        # Spread segment work across 40%–80% of the bar.
        pct = 0.4 + 0.4 * (i - 1) / max(total, 1)
        progress.report(run_id, "summarizing", pct, f"摘要段落 {i}/{total}")

        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=(
                f"這是第 {i}/{total} 段（時間順序）的逐字稿：\n\n"
                f"{part_transcript.timestamped_text()}"
            ),
            config=types.GenerateContentConfig(
                system_instruction=_PARTIAL_SYSTEM_PROMPT,
                max_output_tokens=settings.summary_max_tokens,
            ),
        )
        text = (response.text or "").strip()
        if text:
            partials.append(f"# 片段 {i}\n{text}")

    # Final merge into the canonical structured summary.
    progress.report(run_id, "summarizing", 0.82, "整合各段摘要")
    type_line = (
        f"使用者指定的影片類型：{video_type}"
        if video_type
        else "影片類型：請你自行判斷並填入。"
    )
    merge_prompt = (
        f"{type_line}\n\n"
        "以下是這支影片各片段的重點條列（已依時間順序排列）：\n\n"
        + "\n\n".join(partials)
    )
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=merge_prompt,
        config=types.GenerateContentConfig(
            system_instruction=_MERGE_SYSTEM_PROMPT,
            max_output_tokens=settings.summary_max_tokens,
        ),
    )
    return _parse_summary(response.text or "", video_type)


def summarize_content(
    transcript: Transcript,
    video_type: str | None = None,
    run_id: str | None = None,
) -> Summary:
    """Summarize a transcript into Markdown, returning the (detected) video type.

    Short transcripts take a single Gemini call; long ones are segmented and
    merged so a 30-minute-plus video stays within model limits and reports
    segmented progress.
    """
    settings = get_settings()
    rendered = transcript.timestamped_text()
    if (
        len(rendered) <= settings.summary_segment_char_threshold
        or len(transcript.segments) <= 1
    ):
        return _summarize_single(transcript, video_type)
    return _summarize_segmented(transcript, video_type, run_id)
