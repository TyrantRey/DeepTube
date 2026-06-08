# AI YouTube 影片知識萃取助理 — 知識無人島

A full-stack app that turns a YouTube URL into structured knowledge: it fetches
the transcript (built-in captions, else Whisper), summarizes it into timestamped
key points, optionally generates a `.pptx` slide deck, draws a Mermaid knowledge
map, and remembers every processed video so you can find related ones by keyword
and chat with each video's transcript.

- **Backend** (`src/agent_fyp/`) — a multi-agent pipeline built with **Google ADK**
  and exposed over **FastAPI**. The LLM calls (summary / chat / Mermaid) use
  **Gemini 3.1 Flash Lite**; everything else (transcription, embeddings, slides)
  runs locally.
- **Frontend** (`frontend/`) — a **React 19 + Vite** single-page app styled with
  the *Animal Island* (動物之森 / 知識無人島) UI kit. It drives the async job
  pipeline, shows live stage/progress, renders the summary + Mermaid map, lets you
  download slides, and chats with the video.

```text
repo/
├── src/agent_fyp/   FastAPI backend + ADK agents + tools
├── frontend/        React + Vite UI  (pnpm dev → http://localhost:5173)
├── tests/           pytest suite (network/LLM mocked)
└── docker-compose.yml   api + frontend
```

## Architecture

```text
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

**Re-submission** of an already-processed URL is a cache hit: the API looks the
video up by its YouTube id and returns the stored record without reprocessing.
**Long videos** (transcripts past a character threshold) are summarized in
segments and merged. Each job reports a coarse `stage` + `progress` so the UI can
show the current step (and segmented progress for long videos).

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/). `ffmpeg` is optional
(yt-dlp downloads single-stream audio; faster-whisper decodes it via PyAV).

```bash
uv sync
cp .env.example .env   # then set GOOGLE_API_KEY
```

`GOOGLE_API_KEY` (Google AI Studio / Gemini) is the only required secret.

## Run

### Backend

```bash
# API server (http://127.0.0.1:8000, docs at /docs)
uv run agentfyp
# or: uv run python -m agent_fyp.main   (HOST / PORT env vars)

# One-shot pipeline from the CLI
uv run python scripts/run_pipeline.py "https://www.youtube.com/watch?v=<id>"
```

### Frontend

Requires Node ≥ 20 and [pnpm](https://pnpm.io/) (the toolchain is Vite 6 +
React 19). The pnpm version is pinned via `packageManager` in
`frontend/package.json`, so `corepack enable` will use the right one
(`npm i -g pnpm` also works).

```bash
cd frontend
pnpm install
cp .env.example .env          # VITE_API_URL defaults to http://localhost:8000
pnpm dev                       # http://localhost:5173
```

Start the backend first, then the frontend; the SPA talks to the API at
`VITE_API_URL`. The backend's CORS allow-list already includes `:5173` (override
with the `CORS_ORIGINS` env var, comma-separated, or `*`).

### Docker

```bash
cp .env.example .env   # set GOOGLE_API_KEY
docker compose up --build      # API :8000, frontend :5173
```

`docker compose` builds two services — `api` (FastAPI, port 8000) and `frontend`
(Vite dev server, port 5173). The api mounts two volumes: `./data` (downloads,
slides, ChromaDB, logs, `records.json`) and a named `model-cache` volume (the
faster-whisper and Chroma ONNX models, downloaded on first use). `GOOGLE_API_KEY`
is read from `.env`.

## Endpoints

`POST /process` mints one internal **`video_id` (uuid7)** that is the single id
for everything else — the job, the record, and the slides all share it. The
original YouTube id is returned separately as `youtube_id`.

| Method | Path                            | Purpose                                                                                    |
| ------ | ------------------------------- | ------------------------------------------------------------------------------------------ |
| `POST` | `/process`                      | Enqueue a video; body `{youtube_url, video_type?, generate_slides}` → `{video_id, status}` |
| `GET`  | `/list/process`                 | Current videos grouped: `{processing: [...], finished: [...]}`                             |
| `GET`  | `/history`                      | All processed videos (newest first) for the history sidebar                                |
| `GET`  | `/jobs/{video_id}`              | Job status + `stage`/`progress`/`detail` + pipeline result (`cached` on a cache hit)       |
| `GET`  | `/video/{video_id}`             | Stored `VideoRecord` (`video_id`, `youtube_id`, url, summary…)                             |
| `GET`  | `/ppt/{video_id}`               | Download the generated `.pptx`                                                             |
| `POST` | `/chat/{video_id}`              | Chat with the video's transcript; body `{message, history?}` → `{video_id, answer}`        |
| `GET`  | `/mermaid/{video_id}`           | Mermaid mindmap of the video (from its summary, cached) → `{video_id, mermaid}`            |
| `GET`  | `/history/search?q=...&top_k=5` | Semantic search → related videos + segments                                                |
| `GET`  | `/health`                       | Liveness check                                                                             |

## Tests

```bash
uv run pytest        # one unit test per stage (network/LLM mocked)
```

Generated data (downloads, slides, ChromaDB, logs, records) lives under `data/`
and is git-ignored.

## Contribution

- <https://github.com/LUKEYAU/yt_extractor>
