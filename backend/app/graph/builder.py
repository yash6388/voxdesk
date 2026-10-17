import logging
import re
import uuid
from dataclasses import asdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.models import Booking, Service
from app.graph.prompts import (
    BOOKING_PROMPT,
    BOOKING_UNAVAILABLE,
    DECLINED,
    RESPOND_PROMPT,
    ROUTER_PROMPT,
)
from app.graph.state import ChatState, Route
from app.graph.tools import WRITE_TOOLS, ToolProvider
from app.rag.embeddings import Embedder
from app.rag.retrieval import hybrid_search

logger = logging.getLogger(__name__)

# How many past messages the LLM sees. Older ones stay in the checkpoint but
# aren't sent, which bounds latency and token cost on long conversations.
HISTORY_WINDOW = 10
# The booking agent sees recent turns in full (with tool results) so it can reuse
# service ids and times it already looked up instead of guessing them.
BOOKING_TURNS = 3


def conversation_view(messages: list[AnyMessage]) -> list[AnyMessage]:
    """Only what was actually said: customer messages and assistant replies with text.
    Tool calls/results are internal; dropping them also avoids sending the LLM a tool
    result whose matching call was cut off by the history window."""
    return [
        m
        for m in messages
        if m.type == "human" or (m.type == "ai" and m.text and not getattr(m, "tool_calls", None))
    ]


def recent_turns(messages: list[AnyMessage], turns: int) -> list[AnyMessage]:
    """The last `turns` turns in full, including tool calls and their results.
    Cutting at a customer message keeps every tool call paired with its result."""
    starts = [i for i, m in enumerate(messages) if m.type == "human"]
    return messages[starts[-turns] :] if len(starts) >= turns else messages


def ungrounded_customer_details(args: dict, customer_text: str) -> list[str]:
    """Guardrail: the name and phone in a write action must come from what the customer
    actually said. LLMs sometimes fill gaps with placeholders ("John Doe") even when told
    not to, so this is checked in code rather than trusted to the prompt."""
    missing = []
    phone = re.sub(r"\D", "", str(args.get("customer_phone", "")))
    if phone and phone[-10:] not in re.sub(r"\D", "", customer_text):
        missing.append("phone number")
    name = str(args.get("customer_name", ""))
    words = [w for w in re.findall(r"\w+", name.lower()) if len(w) > 1]
    if name and not all(w in customer_text.lower() for w in words):
        missing.append("name")
    return missing


def build_graph(
    *,
    chat_llm: BaseChatModel,
    router_llm: BaseChatModel,
    embedder: Embedder,
    session_factory: async_sessionmaker,
    tool_provider: ToolProvider,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """
    START → route ─┬─ knowledge → retrieve → respond → END
                   ├─ smalltalk ───────────→ respond → END
                   └─ booking → booking_agent ─┬─ no tool calls ──────────────→ END
                                    ▲          ├─ read tools ───→ tools ─┐
                                    │          └─ write tools → confirm ─┤ (⏸ asks customer)
                                    └────────────────────────────────────┘
    """
    structured_router = router_llm.with_structured_output(Route)

    async def route(state: ChatState) -> dict:
        system = SystemMessage(ROUTER_PROMPT.format(business_name=state["business_name"]))
        decision: Route = await structured_router.ainvoke(
            [system, *conversation_view(state["messages"])[-HISTORY_WINDOW:]]
        )
        # Reset per-turn fields so last turn's context doesn't leak into this one.
        return {"intent": decision.intent, "search_query": decision.search_query, "context": []}

    async def retrieve(state: ChatState) -> dict:
        query = state["search_query"] or state["messages"][-1].text
        async with session_factory() as session:
            chunks = await hybrid_search(session, embedder, uuid.UUID(state["business_id"]), query)
        return {"context": [asdict(c) for c in chunks]}

    async def respond(state: ChatState) -> dict:
        context = (
            "\n\n".join(
                f"[{i}] (from {c['filename']})\n{c['content']}"
                for i, c in enumerate(state["context"], start=1)
            )
            or "(no context retrieved)"
        )
        system = SystemMessage(
            RESPOND_PROMPT.format(
                business_name=state["business_name"],
                business_description=state["business_description"],
                context=context,
            )
        )
        history = conversation_view(state["messages"])[-HISTORY_WINDOW:]
        reply = await chat_llm.ainvoke([system, *history])
        return {"messages": [reply]}

    # ---------- Booking agent (tools come from the MCP server) ----------

    async def booking_agent(state: ChatState) -> dict:
        try:
            tools = await tool_provider.get_tools(state["business_id"])
        except Exception:
            logger.exception("Could not load booking tools")
            return {"messages": [AIMessage(BOOKING_UNAVAILABLE)]}

        now = datetime.now(ZoneInfo(state["business_timezone"]))
        system = SystemMessage(
            BOOKING_PROMPT.format(
                business_name=state["business_name"],
                now=now.strftime("%A %d %B %Y, %H:%M"),
                timezone=state["business_timezone"],
            )
        )
        reply = await chat_llm.bind_tools(tools).ainvoke(
            [system, *recent_turns(state["messages"], BOOKING_TURNS)]
        )
        return {"messages": [reply]}

    def after_booking_agent(state: ChatState) -> str:
        calls = getattr(state["messages"][-1], "tool_calls", None) or []
        if not calls:
            return END
        return "confirm" if any(c["name"] in WRITE_TOOLS for c in calls) else "tools"

    async def describe(call: dict, business_id: str, tz: ZoneInfo, customer_text: str) -> dict:
        """Human-readable summary of a write action for the confirmation card,
        or an error for the agent if the action can't be valid."""
        args = call["args"]
        if missing := ungrounded_customer_details(args, customer_text):
            return {
                "error": f"The customer hasn't given their {' and '.join(missing)} in this "
                "conversation. Ask them for it — never make it up."
            }

        def fmt_day(value: str) -> str:
            try:
                return date.fromisoformat(value).strftime("%A %d %B")
            except (TypeError, ValueError):
                return str(value)

        async with session_factory() as session:
            if call["name"] == "book_appointment":
                service = await _get(session, Service, args.get("service_id"))
                if not service or str(service.business_id) != business_id:
                    return {"error": "Unknown service_id. Call list_services to get real ids."}
                return {
                    "title": "Book appointment",
                    "details": {
                        "Service": service.name,
                        "Date": fmt_day(args.get("date")),
                        "Time": args.get("time"),
                        "Name": args.get("customer_name"),
                        "Phone": args.get("customer_phone"),
                    },
                }
            existing = await _get(
                session, Booking, args.get("booking_id"), options=[selectinload(Booking.service)]
            )
            if not existing or str(existing.business_id) != business_id:
                return {"error": "Unknown booking_id. Use find_my_bookings to look it up."}
            current = existing.start_at.astimezone(tz).strftime("%A %d %B, %H:%M")
            service_name = existing.service.name
            if call["name"] == "cancel_booking":
                return {
                    "title": "Cancel booking",
                    "details": {"Service": service_name, "When": current},
                }
            return {
                "title": "Reschedule booking",
                "details": {
                    "Service": service_name,
                    "From": current,
                    "To": f"{fmt_day(args.get('new_date'))}, {args.get('new_time')}",
                },
            }

    async def confirm(state: ChatState) -> Command:
        """Human-in-the-loop: pause the graph until the customer approves the action.
        interrupt() saves state to the checkpoint and ends this run; the graph resumes
        here — possibly in a different HTTP request — with the customer's decision."""
        last = state["messages"][-1]
        tz = ZoneInfo(state["business_timezone"])
        customer_text = " ".join(m.text for m in state["messages"] if m.type == "human")
        described = {
            c["id"]: await describe(c, state["business_id"], tz, customer_text)
            for c in last.tool_calls
            if c["name"] in WRITE_TOOLS
        }

        # Don't ask the customer to approve something that can't work (e.g. an invented id):
        # send the error back to the agent to fix first.
        if any("error" in d for d in described.values()):
            errors = [
                ToolMessage(
                    described.get(c["id"], {}).get("error", "Not run: fix the other call first."),
                    tool_call_id=c["id"],
                    name=c["name"],
                    status="error",
                )
                for c in last.tool_calls
            ]
            return Command(goto="booking_agent", update={"messages": errors})

        decision = interrupt({"actions": list(described.values())})

        if decision.get("approved"):
            return Command(goto="tools")
        declined = [
            ToolMessage(DECLINED, tool_call_id=c["id"], name=c["name"]) for c in last.tool_calls
        ]
        return Command(goto="booking_agent", update={"messages": declined})

    async def tools(state: ChatState) -> dict:
        calls = state["messages"][-1].tool_calls
        try:
            available = {t.name: t for t in await tool_provider.get_tools(state["business_id"])}
        except Exception:
            logger.exception("Could not load booking tools")
            available = {}

        results = []
        for call in calls:
            tool = available.get(call["name"])
            if tool is None:
                results.append(
                    ToolMessage(
                        "The booking system is unavailable right now.",
                        tool_call_id=call["id"],
                        name=call["name"],
                        status="error",
                    )
                )
                continue
            # Invoking with the full tool call returns a ToolMessage linked to the call id.
            results.append(await tool.ainvoke({**call, "type": "tool_call"}))
        return {"messages": results}

    def after_route(state: ChatState) -> str:
        return {"knowledge": "retrieve", "booking": "booking_agent"}.get(state["intent"], "respond")

    graph = StateGraph(ChatState)
    graph.add_node("route", route)
    graph.add_node("retrieve", retrieve)
    graph.add_node("respond", respond)
    graph.add_node("booking_agent", booking_agent)
    graph.add_node("confirm", confirm, destinations=("tools", "booking_agent"))
    graph.add_node("tools", tools)

    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", after_route, ["retrieve", "respond", "booking_agent"])
    graph.add_edge("retrieve", "respond")
    graph.add_edge("respond", END)
    graph.add_conditional_edges("booking_agent", after_booking_agent, ["confirm", "tools", END])
    graph.add_edge("tools", "booking_agent")

    return graph.compile(checkpointer=checkpointer)


async def _get(session, model, raw_id, options=None):
    try:
        return await session.get(model, uuid.UUID(str(raw_id)), options=options)
    except ValueError:
        return None
