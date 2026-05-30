"""Mermaid tool unit tests: Gemini mocked, fence-stripping + fallback verified."""

from __future__ import annotations

from agent_fyp.tools import mermaid


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


def test_generate_mermaid_strips_fences(monkeypatch):
    fake = _FakeClient("```mermaid\nmindmap\n  root((T))\n    A\n```")
    monkeypatch.setattr(mermaid, "_get_client", lambda: fake)

    out = mermaid.generate_mermaid("# T\n## 重點摘要\n- a", title="T")

    assert out.startswith("mindmap")
    assert "```" not in out
    assert "root((T))" in out


def test_generate_mermaid_wraps_when_header_missing(monkeypatch):
    fake = _FakeClient("root((X))\n  A")  # model forgot the 'mindmap' header
    monkeypatch.setattr(mermaid, "_get_client", lambda: fake)

    out = mermaid.generate_mermaid("summary")

    assert out.startswith("mindmap")
