"""Ingestion agent: YouTube URL -> transcript (captions, Whisper fallback).

Deterministic custom ADK agent — it drives the ingestion tools directly rather
than using an LLM, then writes the transcript and metadata into session state.
"""



import asyncio
from typing import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions

from ..logging_config import get_run_logger
from ..tools.youtube import (
    TranscriptUnavailable,
    download_and_transcribe,
    fetch_metadata,
    fetch_transcript,
    parse_video_id,
)


class IngestionAgent(BaseAgent):
    """Download metadata + transcript and store them in session state."""

    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state
        url = state["youtube_url"]
        log = get_run_logger(state["run_id"], name="agent_fyp.ingestion")

        youtube_id = await asyncio.to_thread(parse_video_id, url)
        state["youtube_id"] = youtube_id
        log.info("Ingesting youtube_id=%s (video_id=%s)", youtube_id, state["run_id"])

        metadata = await asyncio.to_thread(fetch_metadata, url)

        try:
            transcript = await asyncio.to_thread(
                fetch_transcript, youtube_id, state.get("language")
            )
            log.info("Captions found (%d segments)", len(transcript.segments))
        except TranscriptUnavailable:
            log.info("No captions — falling back to Whisper")
            transcript = await asyncio.to_thread(download_and_transcribe, url)
            log.info("Whisper transcribed (%d segments)", len(transcript.segments))

        metadata.transcript_source = transcript.source
        transcript_data = transcript.model_dump()
        metadata_data = metadata.model_dump()
        state["transcript"] = transcript_data
        state["video_metadata"] = metadata_data

        yield Event(
            author=self.name,
            actions=EventActions(
                state_delta={
                    "youtube_id": youtube_id,
                    "transcript": transcript_data,
                    "video_metadata": metadata_data,
                }
            ),
        )
