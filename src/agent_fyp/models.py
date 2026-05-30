"""Shared pydantic data models passed between tools and agents."""


from pydantic import BaseModel, Field


class Segment(BaseModel):
    """A single timed transcript segment."""

    start: float = Field(description="Start time in seconds")
    text: str

    @property
    def timestamp(self) -> str:
        """Return the start time formatted as MM:SS (or HH:MM:SS past an hour)."""
        total = int(self.start)
        hours, rem = divmod(total, 3600)
        minutes, seconds = divmod(rem, 60)
        if hours:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"


class Transcript(BaseModel):
    """A full transcript: flattened text plus timed segments."""

    text: str
    segments: list[Segment] = Field(default_factory=list)
    language: str | None = None
    source: str = Field(description='"captions" or "whisper"')

    def timestamped_text(self) -> str:
        """Render segments as "[MM:SS] text" lines for the summarizer prompt."""
        if not self.segments:
            return self.text
        return "\n".join(f"[{s.timestamp}] {s.text}" for s in self.segments)


class VideoMetadata(BaseModel):
    """Metadata about the source video."""

    video_id: str
    url: str
    title: str = ""
    channel: str | None = None
    duration: float | None = None
    transcript_source: str = ""


class Summary(BaseModel):
    """The Claude-produced summary plus the (possibly detected) video type."""

    video_type: str
    markdown: str


class VideoRecord(BaseModel):
    """The canonical record persisted to ChromaDB and returned by the API.

    ``video_id`` is the internal uuid7 (the primary key for every endpoint);
    ``youtube_id`` is the original YouTube video id.
    """

    video_id: str
    youtube_id: str = ""
    url: str
    title: str = ""
    video_type: str | None = None
    summary_md: str = ""
    slides_path: str | None = None
    mermaid: str | None = None  # cached Mermaid mindmap (generated on demand)
