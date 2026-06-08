"""Stage 1 (ingestion) unit tests: video-id parsing, captions, Whisper fallback."""

import pytest

from agent_fyp.models import Transcript
from agent_fyp.tools import youtube
from agent_fyp.tools.youtube import TranscriptUnavailable, parse_video_id


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=42", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://m.youtube.com/watch?v=dQw4w9WgXcQ&list=x", "dQw4w9WgXcQ"),
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ],
)
def test_parse_video_id(url, expected):
    assert parse_video_id(url) == expected


def test_parse_video_id_rejects_garbage():
    with pytest.raises(ValueError):
        parse_video_id("https://example.com/not-a-video")


class _FakeSnippet:
    def __init__(self, start, text):
        self.start = start
        self.text = text


class _FakeFetched:
    language_code = "en"

    def __init__(self, snippets):
        self._snippets = snippets

    def __iter__(self):
        return iter(self._snippets)


def test_fetch_transcript_builds_segments(monkeypatch):
    fake = _FakeFetched([_FakeSnippet(0.0, "Hello "), _FakeSnippet(5.0, "world")])
    monkeypatch.setattr(
        youtube.YouTubeTranscriptApi, "fetch", lambda self, vid, languages: fake
    )

    transcript = youtube.fetch_transcript("abc12345678")

    assert transcript.source == "captions"
    assert [s.start for s in transcript.segments] == [0.0, 5.0]
    assert transcript.segments[1].timestamp == "00:05"


def test_fetch_transcript_unavailable(monkeypatch):
    from youtube_transcript_api._errors import YouTubeTranscriptApiException

    def _boom(self, vid, languages):
        raise YouTubeTranscriptApiException("nope")

    monkeypatch.setattr(youtube.YouTubeTranscriptApi, "fetch", _boom)
    monkeypatch.setattr(
        youtube.YouTubeTranscriptApi, "list", lambda self, vid: iter([])
    )

    with pytest.raises(TranscriptUnavailable):
        youtube.fetch_transcript("abc12345678")


def test_download_and_transcribe_isolates_and_cleans_up(monkeypatch):
    captured = {}

    def fake_download(url, dest_dir):
        dest_dir.mkdir(parents=True, exist_ok=True)
        audio = dest_dir / "abc.webm"
        audio.write_bytes(b"fake-audio")
        captured["dir"] = dest_dir
        captured["audio"] = audio
        return audio

    monkeypatch.setattr(youtube, "download_audio", fake_download)
    monkeypatch.setattr(
        youtube,
        "transcribe_audio",
        lambda path: Transcript(
            text="hi", segments=[], language="en", source="whisper"
        ),
    )

    transcript = youtube.download_and_transcribe("https://youtu.be/abc12345678")

    assert transcript.source == "whisper"
    # Each call gets its own download dir, which is removed afterwards.
    assert not captured["dir"].exists()
    assert not captured["audio"].exists()
