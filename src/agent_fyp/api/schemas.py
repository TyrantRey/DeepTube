"""Request/response models for the FastAPI layer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ProcessRequest(BaseModel):
    youtube_url: str = Field(description="YouTube video URL or 11-char video id")
    video_type: str | None = Field(
        default=None, description="Override the auto-detected 影片類型"
    )
    generate_slides: bool = Field(
        default=False, description="Also produce a .pptx deck"
    )
    language: str | None = Field(
        default=None, description="Preferred caption language code"
    )


class JobCreated(BaseModel):
    video_id: str
    status: str


class PipelineResult(BaseModel):
    video_id: str
    youtube_id: str | None = None
    video_type: str | None = None
    summary_md: str | None = None
    slides_path: str | None = None


class JobStatus(BaseModel):
    video_id: str
    status: Literal["pending", "running", "completed", "failed"]
    result: PipelineResult | None = None
    error: str | None = None


class ProcessListResponse(BaseModel):
    processing: list[str]
    finished: list[str]


class ChatTurn(BaseModel):
    role: Literal["user", "model", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, description="The user's question")
    history: list[ChatTurn] = Field(
        default_factory=list, description="Prior turns for multi-turn chat"
    )


class ChatResponse(BaseModel):
    video_id: str
    answer: str


class SegmentHit(BaseModel):
    start: float
    timestamp: str
    text: str


class HistoryHit(BaseModel):
    video_id: str
    youtube_id: str = ""
    title: str
    url: str
    video_type: str
    score: float
    segments: list[SegmentHit]


class HistorySearchResponse(BaseModel):
    query: str
    results: list[HistoryHit]


class VideoRecordResponse(BaseModel):
    video_id: str
    youtube_id: str = ""
    url: str
    title: str
    video_type: str | None = None
    summary_md: str = ""
    slides_path: str | None = None
    mermaid: str | None = None


class MermaidResponse(BaseModel):
    video_id: str
    mermaid: str


def to_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump()
