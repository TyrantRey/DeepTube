"""In-process progress reporting for pipeline runs.

Tools and agents call ``report(run_id, stage, progress=..., detail=...)`` as work
advances; the API layer registers a sink per ``run_id`` (wired to the JobStore)
so clients polling ``GET /jobs/{video_id}`` observe the current stage, percent,
and a human-readable detail line.

Kept deliberately decoupled from Google ADK so that deeply-nested tools (e.g. the
segmented summarizer) can report progress without threading a callback through
every layer. Reporting is best-effort and must never break the pipeline.
"""

from __future__ import annotations

from typing import Callable, Optional

# (stage, progress in 0..1 or None, detail string or None)
ProgressSink = Callable[[str, Optional[float], Optional[str]], None]

_sinks: dict[str, ProgressSink] = {}


def register(run_id: str, sink: ProgressSink) -> None:
    """Attach a progress sink for ``run_id`` (overwrites any existing)."""
    _sinks[run_id] = sink


def unregister(run_id: str) -> None:
    """Detach the sink for ``run_id`` (no-op if absent)."""
    _sinks.pop(run_id, None)


def report(
    run_id: str | None,
    stage: str,
    progress: float | None = None,
    detail: str | None = None,
) -> None:
    """Report progress for ``run_id``. Silently ignored if no sink is registered."""
    if not run_id:
        return
    sink = _sinks.get(run_id)
    if sink is None:
        return
    try:
        sink(stage, progress, detail)
    except Exception:  # noqa: BLE001 — progress must never break a run
        pass
