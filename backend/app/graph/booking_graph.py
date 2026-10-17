"""The booking agent's graph: an LLM with MCP booking tools, plus a human-in-the-loop
confirmation step before anything that changes data. Runs inside the booking A2A service.

    START → booking_agent ─┬─ no tool calls ──────────────→ END
                 ▲         ├─ read tools ───→ tools ─┐
                 │         └─ write tools → confirm ─┤  (⏸ interrupt: ask the customer)
                 └───────────────────────────────────┘
"""

import logging
import re
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from app.db.models import Booking, Service
from app.graph.common import recent_turns
from app.graph.prompts import BOOKING_PROMPT, BOOKING_UNAVAILABLE, DECLINED
from app.graph.tools import WRITE_TOOLS, ToolProvider

logger = logging.getLogger(__name__)

# The booking agent sees recent turns in full (with tool results) so it can reuse
# service ids and times it already looked up instead of guessing them.
BOOKING_TURNS = 3


class BookingState(MessagesState):
    business_id: str
    business_name: str
    business_timezone: str


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


def build_booking_graph(
    *,
    chat_llm: BaseChatModel,
    tool_provider: ToolProvider,
    session_factory: async_sessionmaker,
    checkpointer: BaseCheckpointSaver | None = None,
):
    async def booking_agent(state: BookingState) -> dict:
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

    def after_booking_agent(state: BookingState) -> str:
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

    async def confirm(state: BookingState) -> Command:
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

    async def tools(state: BookingState) -> dict:
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

    graph = StateGraph(BookingState)
    graph.add_node("booking_agent", booking_agent)
    graph.add_node("confirm", confirm, destinations=("tools", "booking_agent"))
    graph.add_node("tools", tools)

    graph.add_edge(START, "booking_agent")
    graph.add_conditional_edges("booking_agent", after_booking_agent, ["confirm", "tools", END])
    graph.add_edge("tools", "booking_agent")

    return graph.compile(checkpointer=checkpointer)


async def _get(session, model, raw_id, options=None):
    try:
        return await session.get(model, uuid.UUID(str(raw_id)), options=options)
    except ValueError:
        return None
