"""FastAPI application exposing the YouTube knowledge-extraction pipeline."""

from __future__ import annotations

from pathlib import Path

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from ..config import get_settings
from ..llm import MissingApiKeyError, server_has_api_key
from ..logging_config import configure_logging
from ..tools.chat import chat_with_transcript, extract_citations
from ..tools.mermaid import generate_mermaid
from ..tools.vectorstore import (
    get_record,
    get_transcript_segments,
    query_history,
    list_records,
    save_record,
)
from .jobs import JobStore, run_job
from .schemas import (
    ChatRequest,
    ChatResponse,
    ConfigResponse,
    HistoryItem,
    HistoryListResponse,
    HistorySearchResponse,
    JobCreated,
    JobStatus,
    MermaidResponse,
    ProcessListResponse,
    ProcessRequest,
    TranscriptResponse,
    VideoRecordResponse,
)


def gemini_api_key(
    x_gemini_api_key: str | None = Header(default=None),
) -> str | None:
    """Extract the optional per-user Gemini key (BYOK) from the request header."""
    return (x_gemini_api_key or "").strip() or None

configure_logging()

app = FastAPI(
    title="AI YouTube 影片知識萃取助理",
    description="Backend pipeline: download → summarize → slides → memory.",
    version="0.1.0",
)

# Allow the Vite frontend (default :5173) to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_store = JobStore()


@app.exception_handler(MissingApiKeyError)
async def _missing_api_key_handler(_request, exc: MissingApiKeyError) -> JSONResponse:
    """Surface a missing Gemini key as an actionable 400 (not a generic 500)."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/config", response_model=ConfigResponse)
def config() -> ConfigResponse:
    """Public client config: does the user need to bring their own Gemini key?"""
    return ConfigResponse(
        requires_api_key=not server_has_api_key(),
        gemini_model=get_settings().gemini_model,
    )


@app.post("/process", response_model=JobCreated, status_code=202)
async def process(
    req: ProcessRequest,
    background: BackgroundTasks,
    api_key: str | None = Depends(gemini_api_key),
) -> JobCreated:
    """Enqueue a video for processing.

    Returns the internal ``video_id`` (a uuid7) — the single id used to look up
    the job, the video record, and the slides. An optional ``X-Gemini-Api-Key``
    header lets the caller process with their own Gemini key.
    """
    video_id = _store.create()
    background.add_task(
        run_job,
        _store,
        video_id,
        req.youtube_url,
        req.video_type,
        req.generate_slides,
        req.language,
        api_key,
    )
    return JobCreated(video_id=video_id, status="pending")


@app.get("/list/process", response_model=ProcessListResponse)
def list_process() -> ProcessListResponse:
    """List current videos grouped by job state: processing vs finished."""
    return ProcessListResponse(**_store.grouped())


@app.get("/history", response_model=HistoryListResponse)
def history_list() -> HistoryListResponse:
    """List all processed videos (newest first) for the frontend history sidebar."""
    items = [
        HistoryItem(
            video_id=r.video_id,
            youtube_id=r.youtube_id,
            url=r.url,
            title=r.title,
            video_type=r.video_type,
            summary_md=r.summary_md,
            has_slides=bool(r.slides_path),
            has_mermaid=bool(r.mermaid),
        )
        for r in list_records()
    ]
    return HistoryListResponse(items=items)


@app.get("/jobs/{video_id}", response_model=JobStatus)
def job_status(video_id: str) -> JobStatus:
    job = _store.get(video_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatus(**job)


@app.get("/video/{video_id}", response_model=VideoRecordResponse)
def get_video(video_id: str) -> VideoRecordResponse:
    record = get_record(video_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return VideoRecordResponse(**record.model_dump())


@app.get("/ppt/{video_id}")
def get_ppt(video_id: str) -> FileResponse:
    record = get_record(video_id)
    if record is None or not record.slides_path:
        raise HTTPException(status_code=404, detail="No slides for this video")
    path = Path(record.slides_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Slides file missing on disk")
    return FileResponse(
        path,
        media_type=(
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        ),
        filename=path.name,
    )


@app.get("/transcript/{video_id}", response_model=TranscriptResponse)
def get_transcript(video_id: str) -> TranscriptResponse:
    """Return the video's full timestamped transcript (for the transcript viewer)."""
    if get_record(video_id) is None:
        raise HTTPException(status_code=404, detail="Video not found")
    segments = get_transcript_segments(video_id)
    if not segments:
        raise HTTPException(status_code=404, detail="No transcript for this video")
    return TranscriptResponse(video_id=video_id, segments=segments)


@app.post("/chat/{video_id}", response_model=ChatResponse)
def chat(
    video_id: str,
    req: ChatRequest,
    api_key: str | None = Depends(gemini_api_key),
) -> ChatResponse:
    """Chat with a processed video, grounded in its transcript (+ timestamp citations)."""
    if get_record(video_id) is None:
        raise HTTPException(status_code=404, detail="Video not found")
    segments = get_transcript_segments(video_id)
    if not segments:
        raise HTTPException(status_code=404, detail="No transcript for this video")
    transcript_text = "\n".join(f"[{s['timestamp']}] {s['text']}" for s in segments)

    answer = chat_with_transcript(
        transcript_text,
        req.message,
        [turn.model_dump() for turn in req.history],
        api_key=api_key,
    )
    citations = extract_citations(answer, segments)
    return ChatResponse(video_id=video_id, answer=answer, citations=citations)


@app.get("/mermaid/{video_id}", response_model=MermaidResponse)
def get_mermaid(
    video_id: str,
    api_key: str | None = Depends(gemini_api_key),
) -> MermaidResponse:
    """Return a Mermaid mindmap of the video (generated from its summary, cached)."""
    record = get_record(video_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Video not found")
    if record.mermaid:
        return MermaidResponse(video_id=video_id, mermaid=record.mermaid)
    if not record.summary_md:
        raise HTTPException(status_code=404, detail="No summary to map")

    record.mermaid = generate_mermaid(record.summary_md, record.title, api_key=api_key)
    save_record(record)
    return MermaidResponse(video_id=video_id, mermaid=record.mermaid)


@app.get("/history/search", response_model=HistorySearchResponse)
def history_search(
    q: str = Query(min_length=1, description="Search query / keywords"),
    top_k: int = Query(default=5, ge=1, le=50),
) -> HistorySearchResponse:
    results = query_history(q, top_k=top_k)
    return HistorySearchResponse(query=q, results=results)
