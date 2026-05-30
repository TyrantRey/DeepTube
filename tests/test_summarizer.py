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
