"""Centralised logging: console + rotating file, with a run_id on every record.

Use ``get_run_logger(run_id)`` inside a pipeline run to get a LoggerAdapter that
stamps each line with the run id, so all stages of one request correlate. Call
``append_run_summary(...)`` at the end of a run to record a one-line JSON summary
in ``data/logs/runs.jsonl`` for traceability.
"""

import json
import logging
from logging.handlers import RotatingFileHandler
from typing import Any

from .config import get_settings

_CONFIGURED = False
_LOG_FORMAT = "%(asctime)s %(levelname)-7s [run=%(run_id)s] %(name)s: %(message)s"


class _DefaultRunIdFilter(logging.Filter):
    """Ensure every record has a ``run_id`` attribute so the format never breaks."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = "-"
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Idempotently configure the root logger with console + rotating file handlers."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    formatter = logging.Formatter(_LOG_FORMAT)
    run_filter = _DefaultRunIdFilter()

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.addFilter(run_filter)

    file_handler = RotatingFileHandler(
        settings.logs_dir / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(run_filter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console)
    root.addHandler(file_handler)

    # yt-dlp / httpx / chromadb are noisy at INFO.
    for noisy in ("httpx", "httpcore", "yt_dlp", "chromadb", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_run_logger(run_id: str, name: str = "agent_fyp") -> logging.LoggerAdapter:
    """Return a LoggerAdapter that stamps every record with ``run_id``."""
    configure_logging()
    return logging.LoggerAdapter(logging.getLogger(name), {"run_id": run_id})


def append_run_summary(summary: dict[str, Any]) -> None:
    """Append a per-run summary dict as one JSON line to runs.jsonl."""
    settings = get_settings()
    path = settings.logs_dir / "runs.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(summary, ensure_ascii=False) + "\n")
