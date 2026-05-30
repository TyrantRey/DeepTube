"""Run the full extraction pipeline on a YouTube URL from the command line.

Usage:
    uv run python scripts/run_pipeline.py <youtube_url> [--no-slides]
"""

from __future__ import annotations

import asyncio
import json
import sys

from agent_fyp.agents.orchestrator import get_orchestrator
from agent_fyp.tools.vectorstore import query_history


async def main(url: str, generate_slides: bool) -> None:
    result = await get_orchestrator().process(url, generate_slides=generate_slides)
    print("=== Pipeline result ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("video_id"):
        print("\n=== query_history sample ===")
        hits = query_history(result["summary_md"][:80] if result["summary_md"] else url)
        for hit in hits:
            print(f"- {hit['title']} (score={hit['score']:.3f})")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    url = args[0] if args else "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    slides = "--no-slides" not in sys.argv[1:]
    asyncio.run(main(url, slides))
