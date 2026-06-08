"""Tests for the memory cache-hit path and the /history list endpoint."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from agent_fyp.api import app as app_module
from agent_fyp.api import jobs as jobs_module
from agent_fyp.api.jobs import JobStore, _cached_result, run_job
from agent_fyp.models import VideoRecord
from agent_fyp.tools.vectorstore import (
    find_record_by_youtube_id,
    upsert_history,
)

client = TestClient(app_module.app)

_URL = "https://youtu.be/abcdefghijk"
_YID = "abcdefghijk"


def _seed(video_id: str, transcript, slides_path=None) -> VideoRecord:
    record = VideoRecord(
        video_id=video_id,
        youtube_id=_YID,
        url=_URL,
        title="Cached Talk",
        video_type="教學",
        summary_md="# Cached Talk\n\n## 重點摘要\n- [00:00] x",
        slides_path=slides_path,
    )
    upsert_history(record, transcript)
    return record


def test_find_record_by_youtube_id(sample_transcript):
    _seed("vid-1", sample_transcript)
    found = find_record_by_youtube_id(_YID)
    assert found is not None and found.video_id == "vid-1"
    assert find_record_by_youtube_id("zzzzzzzzzzz") is None
    assert find_record_by_youtube_id("") is None


def test_cached_result_logic(sample_transcript):
    _seed("vid-1", sample_transcript)  # no slides on disk
    # No slides requested -> cache hit regardless of slides.
    assert _cached_result(_URL, generate_slides=False) is not None
    # Slides requested but cached record has none -> reprocess (None).
    assert _cached_result(_URL, generate_slides=True) is None
    # Unparseable URL -> None (let the pipeline surface the proper error).
    assert _cached_result("not even a url", generate_slides=False) is None
    # Unknown video -> None.
    assert _cached_result("https://youtu.be/zzzzzzzzzzz", generate_slides=False) is None


def test_run_job_cache_hit_skips_orchestrator(monkeypatch, sample_transcript):
    store = JobStore()
    _seed("cached-vid", sample_transcript)

    def boom():  # pragma: no cover - must never be called on a cache hit
        raise AssertionError("orchestrator must not run on a cache hit")

    monkeypatch.setattr(jobs_module, "get_orchestrator", boom)

    job_id = store.create()
    asyncio.run(run_job(store, job_id, _URL, None, False, None))

    job = store.get(job_id)
    assert job["status"] == "completed"
    assert job["cached"] is True
    assert job["stage"] == "cached"
    assert job["result"]["video_id"] == "cached-vid"
    assert job["result"]["cached"] is True


def test_history_list_endpoint(sample_transcript):
    _seed("vid-a", sample_transcript)
    _seed("vid-b", sample_transcript)

    resp = client.get("/history")
    assert resp.status_code == 200
    items = resp.json()["items"]
    ids = [i["video_id"] for i in items]
    assert "vid-a" in ids and "vid-b" in ids
    # Newest first (vid-b seeded last).
    assert ids.index("vid-b") < ids.index("vid-a")
    assert items[0]["title"] == "Cached Talk"
