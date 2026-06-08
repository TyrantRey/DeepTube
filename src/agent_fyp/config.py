"""Application configuration, loaded from environment / .env via pydantic-settings."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. The only required secret is ANTHROPIC_API_KEY."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Secrets / models -------------------------------------------------
    google_api_key: str = Field(
        default="", description="Google AI Studio (Gemini) API key"
    )
    gemini_model: str = "gemini-3.1-flash-lite"

    # --- Transcription ----------------------------------------------------
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    default_transcript_language: str = "zh-Hant"

    # --- Storage paths ----------------------------------------------------
    data_dir: Path = Path("data")

    # --- API / CORS -------------------------------------------------------
    # Comma-separated list of allowed browser origins for the frontend.
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173"
    )

    # --- Behaviour toggles ------------------------------------------------
    keep_audio: bool = False
    summary_max_tokens: int = 4096
    chat_max_tokens: int = 1024
    mermaid_max_tokens: int = 1024
    history_top_k: int = 5

    # --- Long-video segmentation -----------------------------------------
    # Transcripts whose timestamped text exceeds this many characters are
    # summarized in chunks and then merged (see tools/summarizer.py).
    summary_segment_char_threshold: int = 9000
    # Target size (characters of timestamped text) per summarization chunk.
    summary_segment_chunk_chars: int = 6000

    @property
    def allowed_origins(self) -> list[str]:
        """Parsed CORS origins. ``*`` (anywhere in the list) allows all."""
        origins = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        return ["*"] if "*" in origins else origins

    @property
    def downloads_dir(self) -> Path:
        return self.data_dir / "downloads"

    @property
    def slides_dir(self) -> Path:
        return self.data_dir / "slides"

    @property
    def chroma_dir(self) -> Path:
        return self.data_dir / "chroma"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        """Create the data sub-directories if they do not exist."""
        for path in (
            self.downloads_dir,
            self.slides_dir,
            self.chroma_dir,
            self.logs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance with data directories ensured."""
    settings = Settings()
    settings.ensure_dirs()
    return settings
