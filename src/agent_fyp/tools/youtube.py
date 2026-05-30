"""YouTube ingestion tools: video-id parsing, metadata, captions, and Whisper.

Two transcript paths:
  * ``fetch_transcript`` — fast path using YouTube's built-in captions.
  * ``download_and_transcribe`` — fallback that downloads audio with yt-dlp and
    transcribes it locally with faster-whisper (decodes audio via PyAV, so no
    ffmpeg binary is required for the transcription step itself).
"""

import re
import shutil
import threading
import uuid
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yt_dlp
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import YouTubeTranscriptApiException

from ..config import get_settings
from ..models import Segment, Transcript, VideoMetadata

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")


class TranscriptUnavailable(Exception):
    """Raised when no built-in captions can be retrieved for a video."""


def parse_video_id(url: str) -> str:
    """Extract the 11-character video id from any common YouTube URL form."""
    url = url.strip()
    if _VIDEO_ID_RE.match(url):
        return url

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")

    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/")[0]
        if _VIDEO_ID_RE.match(candidate):
            return candidate

    if host in {"youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            values = parse_qs(parsed.query).get("v", [])
            if values and _VIDEO_ID_RE.match(values[0]):
                return values[0]
        # /shorts/<id>, /embed/<id>, /v/<id>, /live/<id>
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2 and parts[0] in {"shorts", "embed", "v", "live"}:
            if _VIDEO_ID_RE.match(parts[1]):
                return parts[1]

    raise ValueError(f"Could not parse a YouTube video id from: {url!r}")


def _language_preferences(language: str | None) -> list[str]:
    """Build an ordered language preference list, de-duplicated."""
    settings = get_settings()
    prefs = [
        language,
        settings.default_transcript_language,
        "zh-Hant",
        "zh-Hans",
        "zh",
        "en",
    ]
    seen: set[str] = set()
    ordered: list[str] = []
    for lang in prefs:
        if lang and lang not in seen:
            seen.add(lang)
            ordered.append(lang)
    return ordered


def fetch_transcript(video_id: str, language: str | None = None) -> Transcript:
    """Fetch built-in captions. Raises ``TranscriptUnavailable`` if there are none."""
    api = YouTubeTranscriptApi()
    languages = _language_preferences(language)
    try:
        fetched = api.fetch(video_id, languages=languages)
    except YouTubeTranscriptApiException:
        # Preferred languages missing — try whatever transcript exists.
        try:
            transcript_list = api.list(video_id)
            transcript = next(iter(transcript_list))
            fetched = transcript.fetch()
        except (YouTubeTranscriptApiException, StopIteration) as exc:
            raise TranscriptUnavailable(str(exc)) from exc
    except Exception as exc:  # network / parsing failures
        raise TranscriptUnavailable(str(exc)) from exc

    segments = [Segment(start=float(s.start), text=s.text.strip()) for s in fetched]
    segments = [s for s in segments if s.text]
    if not segments:
        raise TranscriptUnavailable("Captions were empty")

    return Transcript(
        text=" ".join(s.text for s in segments),
        segments=segments,
        language=getattr(fetched, "language_code", None),
        source="captions",
    )


def fetch_metadata(youtube_url: str) -> VideoMetadata:
    """Extract title/channel/duration without downloading the media."""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(youtube_url, download=False)
    return VideoMetadata(
        video_id=info.get("id") or parse_video_id(youtube_url),
        url=info.get("webpage_url") or youtube_url,
        title=info.get("title") or "",
        channel=info.get("uploader") or info.get("channel"),
        duration=info.get("duration"),
    )


def download_audio(youtube_url: str, dest_dir: Path | None = None) -> Path:
    """Download the best audio-only stream into ``dest_dir`` and return its path.

    ``dest_dir`` should be unique per call so concurrent downloads of the same
    video do not collide on a shared filename.
    """
    settings = get_settings()
    base = dest_dir or settings.downloads_dir
    base.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": "bestaudio/best",
        "outtmpl": str(base / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        path = Path(ydl.prepare_filename(info))
    if not path.exists():
        # Fall back to whatever file landed in this (unique) directory.
        matches = list(base.glob(f"{info.get('id')}.*"))
        if not matches:
            raise FileNotFoundError(
                f"Audio download produced no file for {youtube_url}"
            )
        path = matches[0]
    return path


@lru_cache(maxsize=1)
def _whisper_model():
    """Lazily load and cache the faster-whisper model (expensive to construct)."""
    from faster_whisper import WhisperModel

    settings = get_settings()
    return WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute_type,
    )


# Serialize transcription: a single cached model instance is not safe to drive
# from multiple threads at once (concurrent jobs would otherwise race on it).
_whisper_lock = threading.Lock()


def transcribe_audio(audio_path: Path) -> Transcript:
    """Transcribe a local audio file with faster-whisper (auto language detect)."""
    model = _whisper_model()
    with _whisper_lock:
        whisper_segments, info = model.transcribe(str(audio_path))
        segments = [
            Segment(start=float(seg.start), text=seg.text.strip())
            for seg in whisper_segments
            if seg.text and seg.text.strip()
        ]
    return Transcript(
        text=" ".join(s.text for s in segments),
        segments=segments,
        language=getattr(info, "language", None),
        source="whisper",
    )


def download_and_transcribe(youtube_url: str) -> Transcript:
    """Fallback path: download audio then transcribe it locally.

    Each call uses its own download directory so concurrent jobs for the same
    video never overwrite or delete each other's audio file.
    """
    settings = get_settings()
    workdir = settings.downloads_dir / uuid.uuid4().hex
    try:
        audio_path = download_audio(youtube_url, workdir)
        return transcribe_audio(audio_path)
    finally:
        if not settings.keep_audio:
            shutil.rmtree(workdir, ignore_errors=True)
