"""Slide agent: Markdown summary -> .pptx (only when the caller opted in)."""



import asyncio
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from .. import progress
from ..config import get_settings
from ..logging_config import get_run_logger
from ..tools.pptx_builder import generate_learning_path


class SlideAgent(BaseAgent):
    """Generate a slide deck from the summary when ``generate_slides`` is set."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        run_id = state["run_id"]
        log = get_run_logger(run_id, name="agent_fyp.slide")

        if not state.get("generate_slides"):
            log.info("Slides not requested — skipping")
            yield Event(author=self.name)
            return

        progress.report(run_id, "generating_slides", 0.85, "製作投影片 (.pptx)")
        settings = get_settings()
        out_path = settings.slides_dir / f"{run_id}.pptx"
        metadata = state.get("video_metadata") or {}

        path = await asyncio.to_thread(
            generate_learning_path,
            state["summary_md"],
            out_path,
            metadata.get("title"),
        )
        state["slides_path"] = path
        log.info("Slides written to %s", path)

        yield Event(
            author=self.name,
            actions=EventActions(state_delta={"slides_path": path}),
        )
