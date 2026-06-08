"""Stage 5 (orchestration) unit test: full ADK pipeline with externals mocked.

The Claude call and YouTube network access are stubbed; the slide builder and
ChromaDB run for real, so this exercises the SequentialAgent + Runner wiring and
the state hand-off between every stage.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_fyp.agents import ingestion, summary
from agent_fyp.agents.orchestrator import OrchestratorService
from agent_fyp.models import Summary, VideoMetadata
from agent_fyp.tools import vectorstore


@pytest.fixture
def mocked_pipeline(monkeypatch, sample_transcript):
    monkeypatch.setattr(ingestion, "parse_video_id", lambda url: "vid_orch0001")
    monkeypatch.setattr(
        ingestion,
        "fetch_metadata",
        lambda url: VideoMetadata(
            video_id="vid_orch0001", url=url, title="Mocked Talk", duration=180.0
        ),
    )
    monkeypatch.setattr(
        ingestion, "fetch_transcript", lambda vid, lang: sample_transcript
    )

    def _fake_summary(transcript, video_type=None, run_id=None, api_key=None):
        return Summary(
            video_type=video_type or "教學",
            markdown="# Mocked Talk\n\n## 重點摘要\n- [00:00] point\n\n## 小結\nDone.",
        )

    monkeypatch.setattr(summary, "summarize_content", _fake_summary)


def test_pipeline_runs_end_to_end(mocked_pipeline):
    service = OrchestratorService()
    result = asyncio.run(
        service.process(
            "https://youtu.be/vid_orch0001",
            generate_slides=True,
            run_id="run_orch_test",
        )
    )

    assert result["video_id"] == "run_orch_test"  # internal id == run_id
    assert result["youtube_id"] == "vid_orch0001"
    assert result["video_type"] == "教學"
    assert result["summary_md"].startswith("# Mocked Talk")
    assert result["slides_path"] and result["slides_path"].endswith(".pptx")

    # Memory stage persisted the record (keyed by internal id) + indexed segments.
    record = vectorstore.get_record("run_orch_test")
    assert record is not None and record.title == "Mocked Talk"
    assert record.youtube_id == "vid_orch0001"
    assert vectorstore.query_history("python variables", top_k=3)


def test_pipeline_without_slides(mocked_pipeline):
    service = OrchestratorService()
    result = asyncio.run(
        service.process("https://youtu.be/vid_orch0001", run_id="run_no_slides")
    )

    assert result["slides_path"] is None
    assert result["summary_md"]
