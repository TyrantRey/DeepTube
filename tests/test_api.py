"""Stage 5 (API) unit tests: endpoints with the orchestrator mocked.

Starlette's TestClient runs BackgroundTasks synchronously, so a POST /process
followed by GET /jobs/{id} observes the completed job in one test.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent_fyp.api import app as app_module
from agent_fyp.api import jobs as jobs_module
from agent_fyp.models import VideoRecord
from agent_fyp.tools.vectorstore import upsert_history

client = TestClient(app_module.app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_process_flow_and_lookups(monkeypatch, sample_transcript):
    async def fake_process(
        youtube_url, video_type=None, generate_slides=False, language=None, run_id=None
    ):
        record = VideoRecord(
            video_id=run_id,  # internal uuid7 minted by /process
            youtube_id="abc12345678",
            url="https://youtu.be/abc12345678",
            title="Python Basics",
            video_type="教學",
            summary_md="# Python Basics",
        )
        upsert_history(record, sample_transcript)
        return {
            "video_id": run_id,
            "youtube_id": "abc12345678",
            "video_type": "教學",
            "summary_md": record.summary_md,
            "slides_path": None,
        }

    class FakeOrchestrator:
        process = staticmethod(fake_process)

    monkeypatch.setattr(jobs_module, "get_orchestrator", lambda: FakeOrchestrator())

    created = client.post(
        "/process", json={"youtube_url": "https://youtu.be/abc12345678"}
    )
    assert created.status_code == 202
    video_id = created.json()["video_id"]  # uuid7 — the one id for everything

    status = client.get(f"/jobs/{video_id}").json()
    assert status["status"] == "completed"
    assert status["video_id"] == video_id
    assert status["result"]["video_id"] == video_id
    assert status["result"]["youtube_id"] == "abc12345678"

    video = client.get(f"/video/{video_id}")
    assert video.status_code == 200
    assert video.json()["youtube_id"] == "abc12345678"
    assert video.json()["title"] == "Python Basics"

    search = client.get("/history/search", params={"q": "Intro to Python"})
    assert search.status_code == 200
    assert search.json()["results"]


def test_list_process_groups_by_status():
    pending_id = app_module._store.create()
    done_id = app_module._store.create()
    app_module._store._update(done_id, status="completed")

    listing = client.get("/list/process").json()

    assert pending_id in listing["processing"]
    assert done_id in listing["finished"]
    assert done_id not in listing["processing"]


def test_chat_endpoint(monkeypatch, sample_transcript):
    record = VideoRecord(
        video_id="chatvid",
        youtube_id="y",
        url="https://youtu.be/y",
        title="T",
        summary_md="#",
    )
    upsert_history(record, sample_transcript)
    monkeypatch.setattr(
        app_module,
        "chat_with_transcript",
        lambda transcript_text, message, history: f"echo:{message}",
    )

    resp = client.post("/chat/chatvid", json={"message": "what is this about?"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["video_id"] == "chatvid"
    assert data["answer"] == "echo:what is this about?"
    assert data["citations"] == []  # answer has no [MM:SS] markers

    assert client.post("/chat/missing", json={"message": "x"}).status_code == 404


def test_mermaid_endpoint_generates_and_caches(monkeypatch, sample_transcript):
    record = VideoRecord(
        video_id="mapvid",
        youtube_id="y",
        url="https://youtu.be/y",
        title="T",
        summary_md="# T\n## 重點摘要\n- a",
    )
    upsert_history(record, sample_transcript)

    calls = {"n": 0}

    def fake_gen(summary_md, title=None):
        calls["n"] += 1
        return "mindmap\n  root((T))\n    A"

    monkeypatch.setattr(app_module, "generate_mermaid", fake_gen)

    first = client.get("/mermaid/mapvid")
    assert first.status_code == 200
    assert first.json()["mermaid"].startswith("mindmap")

    second = client.get("/mermaid/mapvid")
    assert second.status_code == 200
    assert calls["n"] == 1  # cached on the record, not regenerated

    assert client.get("/mermaid/missing").status_code == 404


def test_unknown_job_and_video_return_404():
    assert client.get("/jobs/does-not-exist").status_code == 404
    assert client.get("/video/does-not-exist").status_code == 404
