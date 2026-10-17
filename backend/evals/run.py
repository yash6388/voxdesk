"""Run the VoxDesk evaluation suite.

    uv run python -m evals.run                         # everything
    uv run python -m evals.run --suites retrieval      # one suite (no LLM calls at all)
    uv run python -m evals.run --chunk-sizes 500,1000  # retrieval chunk-size experiment

Uses a temporary business built from samples/*.md (deleted afterwards) and the same
models as production (Gemini with fallback, per LLM_PRIMARY). Writes
evals/reports/latest.md (+ .json) and a timestamped copy.
"""

import argparse
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.db.session import engine
from app.llm import FallbackChatModel, chat_llm, router_llm
from app.rag.embeddings import get_embedder
from evals.report import render
from evals.setup import eval_business
from evals.suites import answer_suite, booking_suite, retrieval_suite, routing_suite

GOLDEN = Path(__file__).parent / "data" / "golden.json"
REPORTS = Path(__file__).parent / "reports"
ALL_SUITES = ["retrieval", "routing", "answers", "booking"]


def judge_llm():
    """A different model from the one being judged where possible (the fallback provider)."""
    s = get_settings()
    if s.fallback_api_key:
        return FallbackChatModel(
            model=s.fallback_model,
            base_url=s.fallback_base_url,
            api_key=s.fallback_api_key,
            temperature=0,
            max_retries=6,  # evals can wait out rate limits
        )
    return chat_llm()


def describe_models() -> str:
    s = get_settings()
    order = (
        f"{s.fallback_model} → {s.chat_model}"
        if s.llm_primary == "fallback" and s.fallback_api_key
        else f"{s.chat_model} → {s.fallback_model if s.fallback_api_key else 'no fallback'}"
    )
    judge = s.fallback_model if s.fallback_api_key else s.chat_model
    return (
        f"answers/agent: {order} · router: {s.router_model} (+fallback) · "
        f"judge: {judge} · embeddings: {s.embedding_model}"
    )


async def main(suites: list[str], chunk_sizes: list[int]) -> None:
    golden = json.loads(GOLDEN.read_text())
    embedder = get_embedder()
    started_at, t0 = datetime.now().isoformat(timespec="seconds"), time.perf_counter()
    results: dict = {}

    if "retrieval" in suites:
        results["retrieval"] = {}
        for size in chunk_sizes:
            print(f"▶ retrieval @ chunk size {size}…")
            async with eval_business(golden["documents"], embedder, chunk_size=size) as (biz, _):
                results["retrieval"][size] = await retrieval_suite(
                    embedder, biz, golden["retrieval"]
                )

    needs_business = {"answers", "booking"} & set(suites)
    if "routing" in suites:
        print("▶ routing…")
        results["routing"] = await routing_suite(router_llm(), golden["routing"])
    if needs_business:
        async with eval_business(golden["documents"], embedder) as (biz, services):
            if "answers" in suites:
                print("▶ answers (+ LLM judge)…")
                results["answers"] = await answer_suite(
                    chat_llm(), judge_llm(), embedder, biz, golden["answers"]
                )
            if "booking" in suites:
                print("▶ booking agent…")
                results["booking"] = await booking_suite(
                    chat_llm(), biz, services, golden["booking"]
                )

    meta = {
        "started": started_at,
        "duration_s": time.perf_counter() - t0,
        "models": describe_models(),
        "notes": "Latency on free-tier providers includes rate-limit waits (Groq's per-minute "
        "token cap); measured single-call model latency is ~0.3 s.",
        "corpus": f"{len(golden['documents'])} sample documents · "
        f"{len(golden['retrieval'])} retrieval, "
        f"{len(golden['routing'])} routing, {len(golden['answers'])} answer, "
        f"{len(golden['booking'])} booking cases",
    }
    REPORTS.mkdir(exist_ok=True)
    markdown = render(results, meta)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    for name in ("latest", f"eval-{stamp}"):
        (REPORTS / f"{name}.md").write_text(markdown)
    (REPORTS / "latest.json").write_text(
        json.dumps({"meta": meta, "results": results}, indent=2, default=str)
    )
    print("\n" + markdown)
    print(f"\nReport: {REPORTS / 'latest.md'}")
    await engine.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description="Run the VoxDesk evaluation suite")
    parser.add_argument("--suites", default=",".join(ALL_SUITES))
    parser.add_argument("--chunk-sizes", default="500,1000")
    args = parser.parse_args()
    asyncio.run(
        main(
            [s.strip() for s in args.suites.split(",") if s.strip()],
            [int(x) for x in args.chunk_sizes.split(",")],
        )
    )
