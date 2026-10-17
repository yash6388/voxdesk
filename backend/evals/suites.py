"""The four evaluation suites. Each returns a summary dict plus per-case rows for the report."""

import asyncio
import json
import re
import time
import uuid
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from app.db.models import Business, Service
from app.db.session import SessionLocal
from app.errors import is_rate_limited
from app.graph.booking_graph import build_booking_graph
from app.graph.state import Route
from app.graph.supervisor import classify
from app.rag.answer import answer_messages, format_context
from app.rag.retrieval import hybrid_search
from evals.judge import judge_faithfulness
from evals.metrics import first_relevant_rank, hit_at, includes_all_groups, is_refusal, mrr

TZ = "Asia/Kolkata"


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def _rate_limited(exc: Exception) -> bool:
    return is_rate_limited(exc) or "RateLimit" in type(exc).__name__


async def patiently(make_call, attempts: int = 5, wait_s: float = 20):
    """Free-tier providers cap tokens per minute. Wait and retry on rate limits so the
    eval measures the AI, not the quota. (Only rate limits are retried.)"""
    for attempt in range(attempts):
        try:
            return await make_call()
        except Exception as exc:
            if not _rate_limited(exc) or attempt == attempts - 1:
                raise
            await asyncio.sleep(wait_s)


# ---------- 1. Retrieval ----------


async def retrieval_suite(embedder, business: Business, cases: list[dict]) -> dict:
    """One hybrid query per question returns each chunk's semantic rank, keyword rank and
    fused (RRF) order — so all three strategies are compared on identical candidates."""
    ranks: dict[str, list[int | None]] = {"vector": [], "keyword": [], "hybrid": []}
    rows = []
    for case in cases:
        async with SessionLocal() as session:
            chunks = await hybrid_search(session, embedder, business.id, case["question"], 40)
        orders = {
            "hybrid": chunks,
            "vector": sorted([c for c in chunks if c.semantic_rank], key=lambda c: c.semantic_rank),
            "keyword": sorted([c for c in chunks if c.keyword_rank], key=lambda c: c.keyword_rank),
        }
        row = {"question": case["question"]}
        for mode, ordered in orders.items():
            rank = first_relevant_rank([c.content for c in ordered], case["expect_any"])
            ranks[mode].append(rank)
            row[mode] = rank
        rows.append(row)

    summary = {
        mode: {
            "hit@1": hit_at(r, 1),
            "hit@3": hit_at(r, 3),
            "hit@5": hit_at(r, 5),
            "mrr": mrr(r),
        }
        for mode, r in ranks.items()
    }
    return {"summary": summary, "rows": rows}


# ---------- 2. Routing ----------


def _messages(pairs: list[list[str]]):
    return [HumanMessage(text) if role == "user" else AIMessage(text) for role, text in pairs]


async def routing_suite(router_llm, cases: list[dict]) -> dict:
    structured = router_llm.with_structured_output(Route)
    rows, latencies = [], []
    for case in cases:
        started = time.perf_counter()
        try:
            decision = await patiently(
                lambda case=case: classify(
                    structured, "Glow Studio Salon", _messages(case["messages"])
                )
            )
            got = decision.intent
        except Exception as exc:
            got = f"error: {type(exc).__name__}"
        latencies.append(_ms(started))
        rows.append(
            {
                "message": case["messages"][-1][1],
                "expected": case["expect"],
                "got": got,
                "ok": got == case["expect"],
            }
        )
    confusion = Counter((r["expected"], r["got"]) for r in rows)
    return {
        "summary": {"accuracy": sum(r["ok"] for r in rows) / len(rows)},
        "confusion": {f"{e} → {g}": n for (e, g), n in sorted(confusion.items())},
        "rows": rows,
        "latencies_ms": latencies,
    }


# ---------- 3. Answers (facts, refusals, faithfulness) ----------


async def answer_suite(
    chat_llm, judge_llm, embedder, business: Business, cases: list[dict]
) -> dict:
    rows, latencies = [], []
    for case in cases:
        async with SessionLocal() as session:
            chunks = await hybrid_search(session, embedder, business.id, case["question"])
        started = time.perf_counter()
        try:
            messages = answer_messages(
                case["question"], chunks, business.name, business.description
            )
            reply = await patiently(lambda messages=messages: chat_llm.ainvoke(messages))
            answer = reply.text
        except Exception as exc:
            rows.append({"question": case["question"], "error": type(exc).__name__})
            continue
        latencies.append(_ms(started))

        row = {"question": case["question"], "answer": answer, "answerable": case["answerable"]}
        if case["answerable"]:
            row["facts_ok"] = includes_all_groups(answer, case["must_include"])
            try:
                context = format_context(chunks)
                judgement = await patiently(
                    lambda q=case["question"], c=context, a=answer: judge_faithfulness(
                        judge_llm, q, c, a
                    )
                )
                row["faithfulness"] = judgement.score
                row["unsupported"] = judgement.unsupported_claims
                row["judge_reason"] = judgement.reasoning
            except Exception as exc:
                row["faithfulness"] = None
                row["judge_reason"] = f"judge error: {type(exc).__name__}"
            row["ok"] = row["facts_ok"] and (row["faithfulness"] or 0) >= 4
        else:
            # Unanswerable from the documents: the right behaviour is to say so.
            row["refused"] = is_refusal(answer)
            row["ok"] = row["refused"]
        rows.append(row)

    answerable = [r for r in rows if r.get("answerable")]
    unanswerable = [r for r in rows if r.get("answerable") is False]
    errors = sum(1 for r in rows if "error" in r)
    scores = [r["faithfulness"] for r in answerable if r.get("faithfulness")]
    return {
        "summary": {
            "fact_accuracy": sum(r.get("facts_ok", False) for r in answerable) / len(answerable)
            if answerable
            else 0,
            "mean_faithfulness": sum(scores) / len(scores) if scores else 0,
            "faithful_rate (≥4)": sum(s >= 4 for s in scores) / len(scores) if scores else 0,
            "correct_refusals": sum(r.get("refused", False) for r in unanswerable)
            / len(unanswerable)
            if unanswerable
            else 0,
            "errors": errors,
        },
        "rows": rows,
        "latencies_ms": latencies,
    }


# ---------- 4. Booking agent (real LLM, fake tools — nothing is really booked) ----------


def _next_weekday(weekday: int) -> date:
    today = datetime.now(ZoneInfo(TZ)).date()
    return today + timedelta(days=(weekday - today.weekday() - 1) % 7 + 1)  # strictly after today


def booking_placeholders() -> dict[str, str]:
    values = {}
    for name, weekday in [("monday", 0), ("wednesday", 2), ("thursday", 3)]:
        day = _next_weekday(weekday)
        values[name] = day.strftime("%A %d %B")  # e.g. "Wednesday 21 October"
        values[f"{name}_iso"] = day.isoformat()
    return values


class EvalTools:
    """Stand-ins for the MCP booking tools with fixed availability: Monday closed, and
    14:00 is never free. Records every call; book_appointment never runs before the
    confirmation step, so nothing is written."""

    def __init__(self, services: list[Service]):
        self.calls: list[tuple[str, dict]] = []
        catalogue = [
            {"service_id": str(s.id), "name": s.name, "duration_minutes": s.duration_minutes}
            for s in services
        ]

        @tool
        def list_services() -> str:
            """List bookable services with their service_id, duration and price."""
            self.calls.append(("list_services", {}))
            return json.dumps(catalogue)

        @tool
        def check_availability(service_id: str, date: str) -> str:
            """List free start times (HH:MM) for a service on a date (YYYY-MM-DD)."""
            self.calls.append(("check_availability", {"service_id": service_id, "date": date}))
            closed = datetime.fromisoformat(date).weekday() == 0
            times = [] if closed else ["10:00", "11:00", "15:00", "16:00"]
            return json.dumps({"date": date, "available_times": times})

        @tool
        def book_appointment(
            service_id: str, date: str, time: str, customer_name: str, customer_phone: str
        ) -> str:
            """Book a service at a date (YYYY-MM-DD) and start time (HH:MM) for a customer."""
            self.calls.append(("book_appointment", {"date": date, "time": time}))
            return json.dumps({"status": "confirmed", "reference": "EVAL01"})

        self._tools = [list_services, check_availability, book_appointment]

    async def get_tools(self, business_id: str):
        return self._tools


async def booking_suite(
    chat_llm, business: Business, services: list[Service], cases: list[dict]
) -> dict:
    values = booking_placeholders()
    rows, latencies = [], []
    for case in cases:
        tools = EvalTools(services)
        graph = build_booking_graph(
            chat_llm=chat_llm,
            tool_provider=tools,
            session_factory=SessionLocal,
            checkpointer=InMemorySaver(),
        )
        config = {"configurable": {"thread_id": str(uuid.uuid4())}}
        message = case["message"].format(**values)
        expect = {
            k: v.format(**values) if isinstance(v, str) else v for k, v in case["expect"].items()
        }
        started = time.perf_counter()
        try:
            graph_input = {
                "messages": [("user", message)],
                "business_id": str(business.id),
                "business_name": business.name,
                "business_timezone": TZ,
            }
            state = await patiently(
                lambda graph=graph, graph_input=graph_input, config=config: graph.ainvoke(
                    graph_input, config
                )
            )
        except Exception as exc:
            rows.append({"case": case["name"], "error": type(exc).__name__})
            continue
        latencies.append(_ms(started))

        # A booking "happened" if the graph paused for confirmation with a book action.
        snapshot = await graph.aget_state(config)
        pending = snapshot.interrupts[0].value["actions"] if snapshot.interrupts else []
        booked = next((a for a in pending if a.get("title") == "Book appointment"), None)
        call = next(
            (
                c["args"]
                for m in reversed(state["messages"])
                for c in (getattr(m, "tool_calls", None) or [])
                if c["name"] == "book_appointment"
            ),
            None,
        )

        checks = {"books": bool(booked) == expect["books"]}
        if expect["books"] and booked and call:
            checks["service"] = booked["details"].get("Service") == expect["service"]
            checks["date"] = call.get("date") == expect["date"]
            checks["time"] = call.get("time") == expect["time"]
            checks["name"] = (
                expect["name_contains"].lower() in str(call.get("customer_name", "")).lower()
            )
            checks["phone"] = (
                re.sub(r"\D", "", str(call.get("customer_phone", "")))[-10:]
                == expect["phone_digits"]
            )
        last_text = next(
            (m.text for m in reversed(state["messages"]) if m.type == "ai" and m.text), ""
        )
        rows.append(
            {
                "case": case["name"],
                "message": message,
                "tools_called": [name for name, _ in tools.calls],
                "booked": bool(booked),
                "checks": checks,
                "ok": all(checks.values()),
                "reply": last_text[:200],
            }
        )

    done = [r for r in rows if "error" not in r]
    return {
        "summary": {
            "task_success": sum(r["ok"] for r in done) / len(done) if done else 0,
            "errors": len(rows) - len(done),
        },
        "rows": rows,
        "latencies_ms": latencies,
    }
