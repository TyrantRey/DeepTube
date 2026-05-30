"""Shared pytest fixtures: isolate each test in its own DATA_DIR and clear caches."""



import pytest

from agent_fyp import config
from agent_fyp.models import Segment, Transcript, VideoMetadata, VideoRecord


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Point DATA_DIR at a temp dir and reset cached singletons per test."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    config.get_settings.cache_clear()

    # Reset module-level caches that close over get_settings().
    from agent_fyp.tools import summarizer, vectorstore, youtube

    vectorstore._collection.cache_clear()
    youtube._whisper_model.cache_clear()
    summarizer._client = None

    yield

    config.get_settings.cache_clear()
    vectorstore._collection.cache_clear()


@pytest.fixture
def sample_transcript() -> Transcript:
    return Transcript(
        text="Intro to Python. Variables and types. Functions and loops.",
        segments=[
            Segment(start=0.0, text="Intro to Python."),
            Segment(start=65.0, text="Variables and types."),
            Segment(start=130.0, text="Functions and loops."),
        ],
        language="en",
        source="captions",
    )


@pytest.fixture
def sample_metadata() -> VideoMetadata:
    return VideoMetadata(
        video_id="abc12345678",
        url="https://youtu.be/abc12345678",
        title="Python Basics",
        channel="Teacher",
        duration=180.0,
        transcript_source="captions",
    )


@pytest.fixture
def sample_record() -> VideoRecord:
    return VideoRecord(
        video_id="0190000a-0000-7000-8000-00000000abcd",  # internal uuid7
        youtube_id="abc12345678",
        url="https://youtu.be/abc12345678",
        title="Python Basics",
        video_type="教學",
        summary_md="# Python Basics\n\n## 重點摘要\n- [00:00] Intro",
        slides_path=None,
    )


@pytest.fixture
def sample_summary_md() -> str:
    return (
        "<!-- video_type: 教學 -->\n"
        "# Python 入門教學\n\n"
        "## 影片類型\n教學\n\n"
        "## 重點摘要\n"
        "- [00:00] 介紹 Python 與課程目標\n"
        "- [01:05] 變數與資料型別\n"
        "- [02:10] 函式與迴圈\n\n"
        "## 小結\n"
        "本影片帶你快速認識 Python 的基礎語法。"
    )
