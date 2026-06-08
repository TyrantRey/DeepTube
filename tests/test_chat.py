"""Chat tool unit tests: Gemini mocked, grounding + history mapping verified."""

from __future__ import annotations

from agent_fyp.tools import chat


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


def test_chat_grounds_on_transcript(monkeypatch):
    fake = _FakeClient("答案在 [00:05]。")
    monkeypatch.setattr(chat, "_get_client", lambda api_key=None: fake)

    answer = chat.chat_with_transcript(
        "[00:05] hello world",
        "什麼是重點？",
        history=[{"role": "assistant", "content": "hi"}],
    )

    assert answer == "答案在 [00:05]。"
    # The transcript is embedded in the system instruction.
    assert "hello world" in fake.captured["config"].system_instruction
    # History role 'assistant' maps to 'model'; the new message is the last user turn.
    contents = fake.captured["contents"]
    assert contents[0]["role"] == "model"
    assert contents[-1]["role"] == "user"
    assert contents[-1]["parts"][0]["text"] == "什麼是重點？"
