"""Tests for GET /transcript/{id} and chat citation extraction."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_fyp.api import app as app_module
from agent_fyp.models import VideoRecord
from agent_fyp.tools.chat import extract_citations
from agent_fyp.tools.vectorstore import save_record, upsert_history

client = TestClient(app_module.app)


# ── extract_citations (pure) ─────────────────────────────────────────────────

_SEGMENTS = [
    {"start": 0.0, "timestamp": "00:00", "text": "Intro to Python."},
    {"start": 65.0, "timestamp": "01:05", "text": "Variables and types."},
    {"start": 130.0, "timestamp": "02:10", "text": "Functions and loops."},
]


def test_extract_citations_maps_markers_to_segments():
    answer = "It covers variables [01:05] and then loops [02:10]."
    cites = extract_citations(answer, _SEGMENTS)
    assert len(cites) == 2
    assert cites[0] == {"timestamp": "01:05", "start": 65.0, "quote": "Variables and types."}
    assert cites[1] == {"timestamp": "02:10", "start": 130.0, "quote": "Functions and loops."}


def test_extract_citations_dedupes_and_handles_no_match():
    # Repeated marker -> one citation; no markers / no segments -> empty.
    assert len(extract_citations("see [01:05] and again [01:05]", _SEGMENTS)) == 1
    assert extract_citations("no timestamps here", _SEGMENTS) == []
    assert extract_citations("at [01:05]", []) == []


def test_extract_citations_handles_hour_timestamps():
    segs = [{"start": 3600.0, "timestamp": "1:00:00", "text": "hour mark"}]
    cites = extract_citations("jump to [1:00:00] for the point", segs)
    assert cites == [{"timestamp": "1:00:00", "start": 3600.0, "quote": "hour mark"}]


# ── GET /transcript/{id} ─────────────────────────────────────────────────────


def test_transcript_endpoint_returns_segments(sample_transcript):
    record = VideoRecord(
        video_id="tvid", youtube_id="y", url="https://youtu.be/y", title="T",
        summary_md="#",
    )
    upsert_history(record, sample_transcript)

    resp = client.get("/transcript/tvid")
    assert resp.status_code == 200
    segs = resp.json()["segments"]
    assert segs and all({"start", "timestamp", "text"} <= set(s) for s in segs)


def test_transcript_endpoint_404s(sample_transcript):
    # Unknown video.
    assert client.get("/transcript/missing").status_code == 404
    # Record exists but no indexed transcript -> 404.
    save_record(
        VideoRecord(video_id="notx", youtube_id="y", url="u", title="T", summary_md="#")
    )
    assert client.get("/transcript/notx").status_code == 404


def test_chat_endpoint_returns_citations(monkeypatch, sample_transcript):
    record = VideoRecord(
        video_id="cite-vid", youtube_id="y", url="https://youtu.be/y", title="T",
        summary_md="#",
    )
    upsert_history(record, sample_transcript)
    monkeypatch.setattr(
        app_module,
        "chat_with_transcript",
        lambda transcript_text, message, history: "The key idea is at [01:05].",
    )

    resp = client.post("/chat/cite-vid", json={"message": "summarize"})
    assert resp.status_code == 200
    cites = resp.json()["citations"]
    assert len(cites) == 1
    assert cites[0]["timestamp"] == "01:05"
    assert "start" in cites[0] and "quote" in cites[0]
