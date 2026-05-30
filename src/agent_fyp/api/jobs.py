"""In-memory background-job manager for the /process pipeline.

Fine for the FYP scope (single process, ephemeral). Swap for Celery/RQ if jobs
must survive restarts or scale across workers.
"""

from __future__ import annotations

from uuid6 import uuid7

from ..agents.orchestrator import get_orchestrator
from ..logging_config import get_run_logger


class JobStore:
    """Tracks pipeline jobs keyed by the internal uuid7 video_id."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}

    def create(self) -> str:
        """Mint a new uuid7 video_id and register a pending job under it."""
        video_id = str(uuid7())
        self._jobs[video_id] = {
            "video_id": video_id,
            "status": "pending",
            "result": None,
            "error": None,
        }
        return video_id

    def get(self, video_id: str) -> dict | None:
        return self._jobs.get(video_id)

    def _update(self, video_id: str, **fields) -> None:
        if video_id in self._jobs:
            self._jobs[video_id].update(fields)

    def grouped(self) -> dict[str, list[str]]:
        """Group job ids: 'processing' (pending/running) vs 'finished' (completed)."""
        processing: list[str] = []
        finished: list[str] = []
        for video_id, job in self._jobs.items():
            if job["status"] in ("pending", "running"):
                processing.append(video_id)
            elif job["status"] == "completed":
                finished.append(video_id)
        return {"processing": processing, "finished": finished}


async def run_job(
    store: JobStore,
    video_id: str,
    youtube_url: str,
    video_type: str | None,
    generate_slides: bool,
    language: str | None,
) -> None:
    """Background entrypoint: run the orchestrator and record the outcome."""
    log = get_run_logger(video_id, name="agent_fyp.jobs")
    store._update(video_id, status="running")
    try:
        result = await get_orchestrator().process(
            youtube_url=youtube_url,
            video_type=video_type,
            generate_slides=generate_slides,
            language=language,
            run_id=video_id,
        )
        store._update(video_id, status="completed", result=result)
    except Exception as exc:  # noqa: BLE001 — surface any failure to the caller
        log.exception("Job %s failed", video_id)
        store._update(video_id, status="failed", error=str(exc))
