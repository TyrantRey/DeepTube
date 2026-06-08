"""In-memory background-job manager for the /process pipeline.

Fine for the FYP scope (single process, ephemeral). Swap for Celery/RQ if jobs
must survive restarts or scale across workers.

Each job carries a coarse ``stage`` + ``progress`` (0..1) + ``detail`` line that
the pipeline updates via :mod:`agent_fyp.progress`, so a client polling
``GET /jobs/{video_id}`` can show the current stage (and, for long videos,
segmented progress).
"""

from __future__ import annotations

from pathlib import Path

from uuid6 import uuid7

from .. import progress
from ..agents.orchestrator import get_orchestrator
from ..llm import MissingApiKeyError
from ..logging_config import get_run_logger
from ..tools.vectorstore import find_record_by_youtube_id
from ..tools.youtube import parse_video_id


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
            "stage": "pending",
            "progress": 0.0,
            "detail": None,
            "cached": False,
            "result": None,
            "error": None,
        }
        return video_id

    def get(self, video_id: str) -> dict | None:
        return self._jobs.get(video_id)

    def _update(self, video_id: str, **fields) -> None:
        if video_id in self._jobs:
            self._jobs[video_id].update(fields)

    def set_progress(
        self,
        video_id: str,
        stage: str,
        pct: float | None = None,
        detail: str | None = None,
    ) -> None:
        """Update the live stage/percent/detail for a running job."""
        job = self._jobs.get(video_id)
        if job is None:
            return
        job["stage"] = stage
        if pct is not None:
            job["progress"] = round(max(0.0, min(1.0, pct)), 3)
        if detail is not None:
            job["detail"] = detail

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


def _cached_result(
    youtube_url: str,
    generate_slides: bool,
) -> dict | None:
    """Return a cached pipeline result for ``youtube_url`` if it was processed
    before (and slides exist when requested), else ``None``.

    Looks the video up by its YouTube id so a re-submission of the same URL hits
    memory instead of reprocessing. Returns ``None`` (re-run) when the URL cannot
    be parsed — the pipeline will then surface the proper "unresolvable" error.
    """
    try:
        youtube_id = parse_video_id(youtube_url)
    except ValueError:
        return None

    record = find_record_by_youtube_id(youtube_id)
    if record is None:
        return None

    # If slides were requested but the cached record has none on disk, reprocess.
    if generate_slides:
        if not record.slides_path or not Path(record.slides_path).exists():
            return None

    return {
        "video_id": record.video_id,
        "youtube_id": record.youtube_id,
        "video_type": record.video_type,
        "summary_md": record.summary_md,
        "slides_path": record.slides_path,
        "cached": True,
    }


async def run_job(
    store: JobStore,
    video_id: str,
    youtube_url: str,
    video_type: str | None,
    generate_slides: bool,
    language: str | None,
    api_key: str | None = None,
) -> None:
    """Background entrypoint: run the orchestrator and record the outcome.

    Before running, check memory: a previously processed URL short-circuits to
    its cached record without reprocessing. ``api_key`` is an optional per-user
    Gemini key (BYOK) threaded into the summarization step.
    """
    log = get_run_logger(video_id, name="agent_fyp.jobs")
    store._update(video_id, status="running")
    store.set_progress(video_id, "starting", 0.02, "準備中")

    # --- Memory cache: skip reprocessing a URL we've already handled. ---------
    cached = _cached_result(youtube_url, generate_slides)
    if cached is not None:
        log.info("Cache hit for %s -> video_id=%s", youtube_url, cached["video_id"])
        store._update(video_id, cached=True)
        store.set_progress(video_id, "cached", 1.0, "已從記憶快取載入")
        store._update(video_id, status="completed", result=cached)
        return

    # --- Live run: stream progress from the pipeline into this job. -----------
    progress.register(
        video_id,
        lambda stage, pct, detail: store.set_progress(video_id, stage, pct, detail),
    )
    try:
        result = await get_orchestrator().process(
            youtube_url=youtube_url,
            video_type=video_type,
            generate_slides=generate_slides,
            language=language,
            run_id=video_id,
            api_key=api_key,
        )
        store.set_progress(video_id, "completed", 1.0, "完成")
        store._update(video_id, status="completed", result=result)
    except MissingApiKeyError as exc:
        # No Gemini key (user nor server) — a user-facing, actionable failure.
        log.warning("Job %s missing API key: %s", video_id, exc)
        store.set_progress(video_id, "failed", None, "缺少 API 金鑰")
        store._update(video_id, status="failed", error=str(exc))
    except ValueError as exc:
        # Unparseable URL / bad input — a user-facing, non-exceptional failure.
        log.warning("Job %s rejected: %s", video_id, exc)
        store.set_progress(video_id, "failed", None, "無法解析此網址")
        store._update(video_id, status="failed", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface any failure to the caller
        log.exception("Job %s failed", video_id)
        store.set_progress(video_id, "failed", None, "處理失敗")
        store._update(video_id, status="failed", error=str(exc))
    finally:
        progress.unregister(video_id)
