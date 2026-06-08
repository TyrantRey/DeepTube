"""Orchestrator: a SequentialAgent pipeline driven by an ADK Runner.

`OrchestratorService` seeds session state from the request, runs
ingestion -> summary -> slide -> memory in order, and reads the final state back
out as a result dict.
"""

from __future__ import annotations

import time

from google.adk.agents import SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from uuid6 import uuid7

from ..logging_config import append_run_summary, get_run_logger
from .ingestion import IngestionAgent
from .memory import MemoryAgent
from .slide import SlideAgent
from .summary import SummaryAgent

_APP_NAME = "agentfyp"
_USER_ID = "api"


class OrchestratorService:
    """Builds the ADK pipeline once and runs it per request."""

    def __init__(self) -> None:
        self.session_service = InMemorySessionService()
        self.agent = SequentialAgent(
            name="orchestrator",
            sub_agents=[
                IngestionAgent(name="ingestion"),
                SummaryAgent(name="summary"),
                SlideAgent(name="slide"),
                MemoryAgent(name="memory"),
            ],
        )
        self.runner = Runner(
            app_name=_APP_NAME,
            agent=self.agent,
            session_service=self.session_service,
        )

    async def process(
        self,
        youtube_url: str,
        video_type: str | None = None,
        generate_slides: bool = False,
        language: str | None = None,
        run_id: str | None = None,
        api_key: str | None = None,
    ) -> dict:
        """Run the full pipeline and return a result dict.

        ``run_id`` is the internal uuid7 used as the canonical ``video_id``.
        ``api_key`` is an optional per-user Gemini key (BYOK); when omitted the
        server's ``GOOGLE_API_KEY`` is used.
        """
        run_id = run_id or str(uuid7())
        log = get_run_logger(run_id, name="agent_fyp.orchestrator")
        started = time.monotonic()

        initial_state = {
            "youtube_url": youtube_url,
            "video_type": video_type,
            "generate_slides": generate_slides,
            "language": language,
            "run_id": run_id,
            "api_key": api_key,
        }

        await self.session_service.create_session(
            app_name=_APP_NAME,
            user_id=_USER_ID,
            session_id=run_id,
            state=initial_state,
        )

        log.info("Pipeline start: %s (slides=%s)", youtube_url, generate_slides)
        message = types.Content(role="user", parts=[types.Part(text=youtube_url)])

        status = "ok"
        try:
            async for _event in self.runner.run_async(
                user_id=_USER_ID, session_id=run_id, new_message=message
            ):
                pass
        except Exception:
            status = "error"
            log.exception("Pipeline failed")
            raise
        finally:
            elapsed = round(time.monotonic() - started, 2)
            append_run_summary(
                {
                    "run_id": run_id,
                    "youtube_url": youtube_url,
                    "status": status,
                    "elapsed_s": elapsed,
                }
            )

        session = await self.session_service.get_session(
            app_name=_APP_NAME, user_id=_USER_ID, session_id=run_id
        )
        state = session.state
        log.info("Pipeline done in %ss", round(time.monotonic() - started, 2))

        return {
            "video_id": run_id,
            "youtube_id": state.get("youtube_id"),
            "video_type": state.get("video_type"),
            "summary_md": state.get("summary_md"),
            "slides_path": state.get("slides_path"),
        }


_service: OrchestratorService | None = None


def get_orchestrator() -> OrchestratorService:
    """Return a process-wide OrchestratorService singleton."""
    global _service
    if _service is None:
        _service = OrchestratorService()
    return _service
