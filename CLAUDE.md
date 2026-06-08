# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

A full-stack app that turns a YouTube URL into structured knowledge: transcript →
timestamped Markdown summary → optional `.pptx` → Mermaid map → searchable memory +
per-video chat. Python/FastAPI backend (`src/agent_fyp/`) + React/Vite frontend
(`frontend/`). The README has a fuller feature/endpoint walkthrough; this file covers
what spans multiple files and the non-obvious conventions.

## Commands

Backend (run from repo root; needs Python 3.13 + [uv](https://docs.astral.sh/uv/)):

```bash
uv sync                                   # install deps
uv run agentfyp                           # API on http://127.0.0.1:8000 (docs at /docs)
uv run python -m agent_fyp.main           # same, honors HOST / PORT env vars
uv run python scripts/run_pipeline.py <url>   # one-shot CLI pipeline, no server

uv run pytest                             # full suite (network + LLM are mocked)
uv run pytest tests/test_summarizer.py::test_name   # single test
```

Frontend (run from `frontend/`; needs Node ≥ 20):

```bash
npm install
npm run dev        # http://localhost:5173 (proxies to VITE_API_URL, default :8000)
npm run build      # tsc -b && vite build
npm run lint       # eslint
```

Lint/format is driven by **Trunk** (`.trunk/trunk.yaml`) — `trunk check` / `trunk fmt`
run ruff + black + isort (Python) and prettier (frontend), among others. There is no
separate Python unit-lint command beyond Trunk.

## Required configuration

`GOOGLE_API_KEY` (Google AI Studio / Gemini) is the **only** required secret — set it in
`.env` (copy `.env.example`). All other settings have defaults in `src/agent_fyp/config.py`
(`Settings`, loaded via pydantic-settings). Generated data (`data/`) is git-ignored.

## Architecture

### The pipeline is an ADK SequentialAgent with deterministic sub-agents

`POST /process` runs `OrchestratorService` (`agents/orchestrator.py`), a Google ADK
`Runner` over a `SequentialAgent` of four sub-agents that always run in order:

```
IngestionAgent → SummaryAgent → SlideAgent → MemoryAgent
```

Key point: these sub-agents are **custom deterministic `BaseAgent`s, not LLM-driven
agents**. Each `_run_async_impl` reads from `ctx.session.state`, calls plain tools in
`tools/`, and writes results back via an `Event(state_delta=...)`. ADK is used purely as
a sequencing/session-state harness here — the LLM is only invoked inside the summary,
chat, and mermaid tools. The orchestrator seeds initial session state from the request,
runs the chain, then reads the final `state` dict back out as the result.

The 5 tools (`tools/`): `youtube.py` (`fetch_transcript`, `download_and_transcribe`),
`summarizer.py` (`summarize_content`), `pptx_builder.py` (`generate_learning_path`),
`vectorstore.py` (`query_history` + record persistence). `chat.py` and `mermaid.py` back
their own endpoints (not part of the sequential pipeline).

### `video_id` (uuid7) is the primary key, not the YouTube id

`POST /process` mints one internal **uuid7 `video_id`** that is the single id for the job,
the stored `VideoRecord`, and the slides. The original YouTube id is carried separately as
`youtube_id`. Every endpoint (`/jobs/{id}`, `/video/{id}`, `/ppt/{id}`, `/chat/{id}`, …)
keys on the uuid7. Don't conflate the two.

### Two-store persistence (both under `data/`, both git-ignored)

`tools/vectorstore.py` holds both stores:
- **`data/records.json`** — the authoritative `VideoRecord` per video (plain JSON dict
  keyed by `video_id`). This is the source of truth for summaries, titles, slide paths,
  cached mermaid.
- **ChromaDB** (`data/chroma/`) — transcript segments embedded with Chroma's **local
  default ONNX embeddings (no API key)**, chunked to ~240 chars, used by `query_history`
  semantic search and to reconstruct transcripts for chat. Models download on first use.

`upsert_history` writes both. Re-processing deletes a video's old vectors first.

### Caching: re-submitting a URL short-circuits

Before running the pipeline, `api/jobs.py::_cached_result` looks the URL up by parsed
YouTube id (`find_record_by_youtube_id`). A hit returns the stored record immediately
(`cached: true`) without reprocessing — unless slides were requested and the cached file
is missing on disk.

### Background jobs + decoupled progress

`POST /process` is fire-and-forget: it returns `202` with a `video_id` and runs the
pipeline in a FastAPI `BackgroundTask`. `JobStore` (`api/jobs.py`) is an **in-memory,
single-process** dict of job state — it does not survive restarts (intentional for FYP
scope; swap for Celery/RQ to persist). Clients poll `GET /jobs/{video_id}` for
`stage`/`progress`/`detail`.

Progress flows through `agent_fyp/progress.py`, a module-level `run_id → sink` registry
kept **deliberately decoupled from ADK** so deeply-nested code (e.g. the segmented
summarizer) can call `progress.report(run_id, stage, pct, detail)` without threading a
callback through every layer. The job wires a sink to `JobStore.set_progress`; reporting
is best-effort and never raises into the pipeline.

### Long-video segmentation

`summarize_content` (`tools/summarizer.py`) has two paths: short transcripts get one
Gemini call; transcripts whose rendered timestamped text exceeds
`summary_segment_char_threshold` (default 9000 chars) are split into chunks, summarized
per-segment, then merged by a final Gemini call — reporting per-segment progress across
the 40–80% band of the bar.

## Important gotcha: the LLM is Gemini, not Claude

Despite several stale docstrings/comments referencing "Claude"/"Anthropic" (e.g.
`agents/summary.py`, `models.py::Summary`, the `Settings` docstring in `config.py`), this
project uses **Gemini (`gemini-3.1-flash-lite`) via the `google-genai` SDK** for all LLM
calls (summary, chat, mermaid). There is no Anthropic dependency. The required key is
`GOOGLE_API_KEY`. Treat those Claude/Anthropic mentions as leftover comments to ignore (or
fix), not as a second code path.

## Frontend

Single-page React 19 + Vite app. `frontend/src/api.ts` is the typed client and documents
the full flow: `startProcess` → `pollJob` (polls `/jobs/{id}` every 1.5s, surfacing
stage/progress, until terminal) → `getVideo`. `Mermaid.tsx` and `YouTubePlayer.tsx` are
the notable custom components; the rest is `App.tsx`. Styling uses the `animal-island-ui`
kit + Tailwind 4.

**Keep Vite pinned to 6** — the local Node toolchain breaks on Vite 8/rolldown. The
backend's CORS allow-list already includes `:5173` / `:4173` (override via `CORS_ORIGINS`,
comma-separated, or `*`).

## Tests

`tests/conftest.py` has an autouse `isolated_data_dir` fixture that points `DATA_DIR` at a
fresh `tmp_path`, sets a dummy `GOOGLE_API_KEY`, and **clears the cached singletons**
(`get_settings`, the Chroma collection, the Whisper model, the summarizer client) before
and after every test. If you add a new module-level cache that closes over settings,
reset it there too or tests will leak state across each other. Network and LLM calls are
mocked — one focused test per pipeline stage.
