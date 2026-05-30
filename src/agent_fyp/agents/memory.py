"""Memory agent: persist the processed video + index its transcript in ChromaDB."""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event

from ..logging_config import get_run_logger
from ..models import Transcript, VideoRecord
from ..tools.vectorstore import upsert_history


class MemoryAgent(BaseAgent):
    """Upsert the VideoRecord + transcript segments into the vector store."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        log = get_run_logger(state["run_id"], name="agent_fyp.memory")

        metadata = state.get("video_metadata") or {}
        record = VideoRecord(
            video_id=state["run_id"],
            youtube_id=state.get("youtube_id", ""),
            url=state["youtube_url"],
            title=metadata.get("title", ""),
            video_type=state.get("video_type"),
            summary_md=state.get("summary_md", ""),
            slides_path=state.get("slides_path"),
        )
        transcript = Transcript(**state["transcript"])

        await asyncio.to_thread(upsert_history, record, transcript)
        log.info("Indexed video_id=%s into memory", record.video_id)

        yield Event(author=self.name)
