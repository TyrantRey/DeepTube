"""Stage 2 (summary) unit tests: Claude call mocked, parsing + override verified."""

from agent_fyp.tools import summarizer


class _Response:
    def __init__(self, text):
        self.text = text


class _Models:
    def __init__(self, outer):
        self._outer = outer

    def generate_content(self, **kwargs):
        self._outer.captured = kwargs
        return _Response(self._outer._text)


class _FakeClient:
    def __init__(self, text):
        self._text = text
        self.captured = {}
        self.models = _Models(self)


def _patch_client(monkeypatch, text):
    client = _FakeClient(text)
    monkeypatch.setattr(summarizer, "_get_client", lambda: client)
    return client


def test_summarize_detects_video_type(monkeypatch, sample_transcript):
    md = "<!-- video_type: 教學 -->\n# Title\n\n## 重點摘要\n- [00:00] x"
    _patch_client(monkeypatch, md)

    summary = summarizer.summarize_content(sample_transcript)

    assert summary.video_type == "教學"
    assert "<!-- video_type" not in summary.markdown
    assert summary.markdown.startswith("# Title")


def test_caller_video_type_overrides_detection(monkeypatch, sample_transcript):
    md = "<!-- video_type: 教學 -->\n# Title\n\n## 重點摘要\n- [00:00] x"
    _patch_client(monkeypatch, md)

    summary = summarizer.summarize_content(sample_transcript, video_type="訪談")

    assert summary.video_type == "訪談"


def test_user_prompt_includes_timestamped_transcript(monkeypatch, sample_transcript):
    client = _patch_client(monkeypatch, "# T\n\n## 重點摘要\n- [00:00] x")

    summarizer.summarize_content(sample_transcript)

    user_content = client.captured["contents"]
    assert "[01:05]" in user_content  # 65s segment rendered with a timestamp
    # The stable system instruction is passed via the Gemini config.
    assert summarizer._SYSTEM_PROMPT == client.captured["config"].system_instruction


def test_long_transcript_is_segmented_and_merged(monkeypatch):
    """A long transcript takes the segmented path: N partial calls + 1 merge."""
    from agent_fyp import config
    from agent_fyp.models import Segment, Transcript

    # Force the segmented path with tiny thresholds.
    monkeypatch.setenv("SUMMARY_SEGMENT_CHAR_THRESHOLD", "40")
    monkeypatch.setenv("SUMMARY_SEGMENT_CHUNK_CHARS", "30")
    config.get_settings.cache_clear()

    segments = [
        Segment(start=float(i * 10), text=f"重點 {i} 的內容描述與細節")
        for i in range(8)
    ]
    transcript = Transcript(
        text=" ".join(s.text for s in segments),
        segments=segments,
        language="zh",
        source="captions",
    )

    calls = {"partial": 0, "merge": 0}
    merged_md = (
        "<!-- video_type: 教學 -->\n# 合併後標題\n\n"
        "## 重點摘要\n- [00:00] 重點\n\n## 小結\n結語"
    )

    class _Models:
        def generate_content(self, **kwargs):
            sys = kwargs["config"].system_instruction
            if sys == summarizer._MERGE_SYSTEM_PROMPT:
                calls["merge"] += 1
                return _Response(merged_md)
            calls["partial"] += 1
            return _Response("- [00:00] 片段重點")

    class _Client:
        def __init__(self):
            self.models = _Models()

    monkeypatch.setattr(summarizer, "_get_client", lambda: _Client())

    summary = summarizer.summarize_content(transcript, run_id="seg-test")

    assert calls["partial"] >= 2  # multiple segments summarized
    assert calls["merge"] == 1  # merged exactly once
    assert summary.video_type == "教學"
    assert summary.markdown.startswith("# 合併後標題")
    assert "<!-- video_type" not in summary.markdown
