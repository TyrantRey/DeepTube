"""Memory tools: persist video records and semantically search transcripts.

Backed by ChromaDB with its local default ONNX embeddings (no API key). The
transcript is indexed at a merged-segment granularity so `query_history` can
return both the related videos and the relevant segments within them. A small
JSON file holds the authoritative `VideoRecord` for each processed video.
"""



import json
from functools import lru_cache

import chromadb

from ..config import get_settings
from ..models import Segment, Transcript, VideoRecord

_COLLECTION = "transcript_segments"
_CHUNK_CHAR_LIMIT = 240


@lru_cache(maxsize=1)
def _collection():
    """Return the persistent Chroma collection (default ONNX embeddings)."""
    settings = get_settings()
    client = chromadb.PersistentClient(path=str(settings.chroma_dir))
    return client.get_or_create_collection(name=_COLLECTION)


def _records_path():
    return get_settings().data_dir / "records.json"


def _load_records() -> dict[str, dict]:
    path = _records_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_records(records: dict[str, dict]) -> None:
    _records_path().write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def save_record(record: VideoRecord) -> None:
    """Persist (or replace) a VideoRecord in the JSON store."""
    records = _load_records()
    records[record.video_id] = record.model_dump()
    _save_records(records)


def get_record(video_id: str) -> VideoRecord | None:
    """Fetch a stored VideoRecord by id, or None if absent."""
    record = _load_records().get(video_id)
    return VideoRecord(**record) if record else None


def list_records() -> list[VideoRecord]:
    """Return all stored VideoRecords (newest-first by insertion order)."""
    return [VideoRecord(**r) for r in reversed(list(_load_records().values()))]


def find_record_by_youtube_id(youtube_id: str) -> VideoRecord | None:
    """Return the most-recently stored record for a YouTube id, or None.

    Used by the API to short-circuit re-processing of a URL already in memory.
    """
    if not youtube_id:
        return None
    match: dict | None = None
    for record in _load_records().values():
        if record.get("youtube_id") == youtube_id:
            match = record  # keep scanning so the last (newest) one wins
    return VideoRecord(**match) if match else None


def _chunk_segments(segments: list[Segment]) -> list[Segment]:
    """Merge consecutive segments into ~sentence-sized chunks for embedding."""
    chunks: list[Segment] = []
    buffer: list[str] = []
    start: float | None = None
    for seg in segments:
        if start is None:
            start = seg.start
        buffer.append(seg.text)
        if sum(len(t) for t in buffer) >= _CHUNK_CHAR_LIMIT:
            chunks.append(Segment(start=start, text=" ".join(buffer)))
            buffer, start = [], None
    if buffer and start is not None:
        chunks.append(Segment(start=start, text=" ".join(buffer)))
    return chunks


def upsert_history(record: VideoRecord, transcript: Transcript) -> None:
    """Store the record and index its transcript segments for semantic search."""
    save_record(record)

    collection = _collection()
    # Replace any existing vectors for this video (re-processing).
    collection.delete(where={"video_id": record.video_id})

    chunks = _chunk_segments(transcript.segments) or (
        [Segment(start=0.0, text=transcript.text)] if transcript.text else []
    )
    if not chunks:
        return

    collection.add(
        ids=[f"{record.video_id}:{i}" for i in range(len(chunks))],
        documents=[c.text for c in chunks],
        metadatas=[
            {
                "video_id": record.video_id,
                "youtube_id": record.youtube_id,
                "title": record.title,
                "url": record.url,
                "video_type": record.video_type or "",
                "start": c.start,
            }
            for c in chunks
        ],
    )


def get_transcript_text(video_id: str) -> str:
    """Rebuild a video's timestamped transcript from its stored segments."""
    collection = _collection()
    data = collection.get(where={"video_id": video_id})
    documents = data.get("documents") or []
    metadatas = data.get("metadatas") or []

    pairs = sorted(
        zip(metadatas, documents), key=lambda pm: float(pm[0].get("start", 0.0))
    )
    lines = []
    for meta, doc in pairs:
        seg = Segment(start=float(meta.get("start", 0.0)), text=doc)
        lines.append(f"[{seg.timestamp}] {seg.text}")
    return "\n".join(lines)


def query_history(query: str, top_k: int | None = None) -> list[dict]:
    """Semantic search over stored transcripts.

    Returns related videos, each with the matching segments:
    ``[{video_id, title, url, video_type, score, segments: [{start, timestamp, text}]}]``.
    """
    settings = get_settings()
    top_k = top_k or settings.history_top_k

    collection = _collection()
    if collection.count() == 0:
        return []

    result = collection.query(query_texts=[query], n_results=top_k * 3)
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]

    grouped: dict[str, dict] = {}
    for doc, meta, dist in zip(documents, metadatas, distances):
        video_id = meta["video_id"]
        seg = Segment(start=float(meta.get("start", 0.0)), text=doc)
        entry = grouped.setdefault(
            video_id,
            {
                "video_id": video_id,
                "youtube_id": meta.get("youtube_id", ""),
                "title": meta.get("title", ""),
                "url": meta.get("url", ""),
                "video_type": meta.get("video_type", ""),
                "score": 1.0 - float(dist),  # cosine distance -> rough similarity
                "segments": [],
            },
        )
        entry["score"] = max(entry["score"], 1.0 - float(dist))
        entry["segments"].append(
            {"start": seg.start, "timestamp": seg.timestamp, "text": seg.text}
        )

    ranked = sorted(grouped.values(), key=lambda e: e["score"], reverse=True)
    return ranked[:top_k]
