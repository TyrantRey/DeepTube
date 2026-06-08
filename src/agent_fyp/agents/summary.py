"""Summary agent: transcript -> Markdown summary (keypoints + timestamps) via Claude."""



import asyncio
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from .. import progress
from ..logging_config import get_run_logger
from ..models import Transcript
from ..tools.summarizer import summarize_content


class SummaryAgent(BaseAgent):
    """Read the transcript from state and write a Markdown summary back."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        run_id = state["run_id"]
        log = get_run_logger(run_id, name="agent_fyp.summary")

        progress.report(run_id, "summarizing", 0.4, "產生結構化摘要")
        transcript = Transcript(**state["transcript"])
        summary = await asyncio.to_thread(
            summarize_content, transcript, state.get("video_type"), run_id=run_id
        )

        state["summary_md"] = summary.markdown
        state["video_type"] = summary.video_type
        log.info("Summary produced (video_type=%s)", summary.video_type)

        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "summary_md": summary.markdown,
                    "video_type": summary.video_type,
                }
            ),
        )
