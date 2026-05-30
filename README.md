# AI YouTube 影片知識萃取助理 (Backend)

A backend service that turns a YouTube URL into structured knowledge: it
downloads the transcript, summarizes it into timestamped key points, optionally
generates a `.pptx` slide deck, and remembers every processed video so you can
later find related videos by keyword.

Built as a multi-agent pipeline with **Google ADK** and exposed over **FastAPI**.
The only LLM call (summarization) uses **Gemini 3.1 Flash Lite**; everything else
(transcription, embeddings, slides) runs locally.

## Architecture

```
POST /process { youtube_url, video_type?, generate_slides }
   → OrchestratorService (ADK Runner + SequentialAgent)
       1. IngestionAgent  fetch_transcript → captions, else download_and_transcribe (Whisper)
       2. SummaryAgent     summarize_content → Gemini → Markdown (keypoints + timestamps)
       3. SlideAgent       generate_learning_path → .pptx   (only if generate_slides)
       4. MemoryAgent      upsert_history → ChromaDB (local ONNX embeddings)
   → { run_id, video_id, video_type, summary_md, slides_path }

GET /history/search?q=...   query_history → related videos + relevant segments
```

The 5 tools: `fetch_transcript`, `download_and_transcribe`, `summarize_content`,
`generate_learning_path`, `query_history` (in `src/agent_fyp/tools/`).

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/). `ffmpeg` is optional
(yt-dlp downloads single-stream audio; faster-whisper decodes it via PyAV).

```bash
uv sync
cp .env.example .env   # then set GOOGLE_API_KEY
```

`GOOGLE_API_KEY` (Google AI Studio / Gemini) is the only required secret.

## Run

```bash
# API server (http://127.0.0.1:8000, docs at /docs)
uv run agentfyp
# or: uv run python -m agent_fyp.main   (HOST / PORT env vars)

# One-shot pipeline from the CLI
uv run python scripts/run_pipeline.py "https://www.youtube.com/watch?v=<id>"
```

## Endpoints

`POST /process` mints one internal **`video_id` (uuid7)** that is the single id
for everything else — the job, the record, and the slides all share it. The
original YouTube id is returned separately as `youtube_id`.

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/process` | Enqueue a video; body `{youtube_url, video_type?, generate_slides}` → `{video_id, status}` |
| `GET`  | `/list/process` | Current videos grouped: `{processing: [...], finished: [...]}` |
| `GET`  | `/jobs/{video_id}` | Job status + pipeline result |
| `GET`  | `/video/{video_id}` | Stored `VideoRecord` (`video_id`, `youtube_id`, url, summary…) |
| `GET`  | `/ppt/{video_id}` | Download the generated `.pptx` |
| `POST` | `/chat/{video_id}` | Chat with the video's transcript; body `{message, history?}` → `{video_id, answer}` |
| `GET`  | `/mermaid/{video_id}` | Mermaid mindmap of the video (from its summary, cached) → `{video_id, mermaid}` |
| `GET`  | `/history/search?q=...&top_k=5` | Semantic search → related videos + segments |
| `GET`  | `/health` | Liveness check |

## Tests

```bash
uv run pytest        # one unit test per stage (network/LLM mocked)
```

Generated data (downloads, slides, ChromaDB, logs, records) lives under `data/`
and is git-ignored.
