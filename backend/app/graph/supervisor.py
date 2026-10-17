"""The supervisor graph, run by the API. It owns the conversation (memory, routing,
small talk, the confirmation UI) and delegates specialist work to remote agents over A2A.

    START → route ─┬─ knowledge → [Knowledge Agent · A2A] ─────────────→ END
                   ├─ smalltalk → respond (local LLM) ─────────────────→ END
                   └─ booking ──→ [Booking Agent · A2A] ─┬─ done ───────→ END
                                                         └─ input-required
                                                            → booking_confirm ⏸ ─┐
                                                              (loops while the   │
                                                               agent asks again) ┘
"""

import logging
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.a2a.client import RemoteAgent
from app.graph.common import HISTORY_WINDOW, conversation_view
from app.graph.prompts import (
    BOOKING_UNAVAILABLE,
    KNOWLEDGE_UNAVAILABLE,
    RESPOND_PROMPT,
    ROUTER_PROMPT,
)
from app.graph.state import ChatState, Route

logger = logging.getLogger(__name__)


@dataclass
class Outcome:
    text: str = ""
    pending: dict | None = None  # {"task_id", "actions"} when the agent needs confirmation
    failed: bool = False


async def delegate(agent: RemoteAgent, fallback: str, **request) -> Outcome:
    """Send one message to a remote agent and relay its stream to the client as it arrives
    (tokens, sources, tool calls) via LangGraph's custom stream."""
    write = get_stream_writer()
    out, chunks, task_id, state = Outcome(), [], "", "failed"
    try:
        async for ev in agent.stream(**request):
            if ev.kind == "task":
                task_id = ev.task_id
                write(
                    {
                        "type": "delegation",
                        "agent": agent.name,
                        "task_id": task_id,
                        "state": "working",
                    }
                )
            elif ev.kind == "token":
                chunks.append(ev.text)
                write({"type": "token", "text": ev.text})
            elif ev.kind == "data":
                write({"type": ev.name, "data": ev.data})
            elif ev.kind == "input_required":
                state = "input-required"
                out.pending = {"task_id": ev.task_id, "actions": ev.data.get("actions", [])}
            elif ev.kind == "completed":
                state = "completed"
            elif ev.kind == "failed":
                out.failed = True
                fallback = ev.text or fallback
    except Exception:
        logger.exception("Delegation to %s failed", agent.name)
        out.failed = True

    out.text = "".join(chunks)
    if out.failed and not out.text:
        # The agent never answered: tell the customer something useful instead of nothing.
        out.text = fallback
        write({"type": "token", "text": fallback})
    write({"type": "delegation", "agent": agent.name, "task_id": task_id, "state": state})
    return out


def build_supervisor(
    *,
    router_llm: BaseChatModel,
    chat_llm: BaseChatModel,
    knowledge_agent: RemoteAgent,
    booking_agent: RemoteAgent,
    checkpointer: BaseCheckpointSaver | None = None,
):
    structured_router = router_llm.with_structured_output(Route)

    def metadata(state: ChatState) -> dict:
        """Business info sent with every A2A message (agents don't remember request metadata)."""
        return {
            "business_id": state["business_id"],
            "business_name": state["business_name"],
            "business_description": state["business_description"],
            "business_timezone": state["business_timezone"],
        }

    def context_id(config: RunnableConfig) -> str:
        # One A2A context per conversation; the thread id is already namespaced by business.
        return config["configurable"]["thread_id"]

    def finish(out: Outcome) -> dict:
        update: dict = {"pending_booking": out.pending}
        if out.text:
            update["messages"] = [AIMessage(out.text)]
        return update

    async def route(state: ChatState) -> dict:
        system = SystemMessage(ROUTER_PROMPT.format(business_name=state["business_name"]))
        decision: Route = await structured_router.ainvoke(
            [system, *conversation_view(state["messages"])[-HISTORY_WINDOW:]]
        )
        return {
            "intent": decision.intent,
            "search_query": decision.search_query,
            "pending_booking": None,
        }

    async def knowledge(state: ChatState, config: RunnableConfig) -> dict:
        out = await delegate(
            knowledge_agent,
            KNOWLEDGE_UNAVAILABLE,
            # The router already rewrote follow-ups into a standalone question.
            text=state["search_query"] or state["messages"][-1].text,
            context_id=context_id(config),
            metadata=metadata(state),
        )
        return finish(out)

    async def respond(state: ChatState) -> dict:
        """Small talk is answered locally — no need for a network hop."""
        system = SystemMessage(
            RESPOND_PROMPT.format(
                business_name=state["business_name"],
                business_description=state["business_description"],
                context="(none needed for small talk)",
            )
        )
        reply = await chat_llm.ainvoke(
            [system, *conversation_view(state["messages"])[-HISTORY_WINDOW:]]
        )
        return {"messages": [reply]}

    async def booking(state: ChatState, config: RunnableConfig) -> dict:
        out = await delegate(
            booking_agent,
            BOOKING_UNAVAILABLE,
            text=state["messages"][-1].text,
            context_id=context_id(config),
            metadata=metadata(state),
        )
        return finish(out)

    async def booking_confirm(state: ChatState, config: RunnableConfig) -> dict:
        """The booking agent is waiting (A2A input-required). Pause THIS graph so the API
        can ask the customer; on resume, send the decision back on the same A2A task.
        Nothing before interrupt() has side effects, because the node re-runs on resume."""
        pending = state["pending_booking"]
        decision = interrupt({"actions": pending["actions"]})
        out = await delegate(
            booking_agent,
            BOOKING_UNAVAILABLE,
            data={"approved": bool(decision.get("approved"))},
            task_id=pending["task_id"],
            context_id=context_id(config),
            metadata=metadata(state),
        )
        return finish(out)

    def after_route(state: ChatState) -> str:
        return {"knowledge": "knowledge", "booking": "booking"}.get(state["intent"], "respond")

    def after_booking(state: ChatState) -> str:
        return "booking_confirm" if state.get("pending_booking") else END

    graph = StateGraph(ChatState)
    graph.add_node("route", route)
    graph.add_node("knowledge", knowledge)
    graph.add_node("respond", respond)
    graph.add_node("booking", booking)
    graph.add_node("booking_confirm", booking_confirm)

    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", after_route, ["knowledge", "respond", "booking"])
    graph.add_edge("knowledge", END)
    graph.add_edge("respond", END)
    graph.add_conditional_edges("booking", after_booking, ["booking_confirm", END])
    graph.add_conditional_edges("booking_confirm", after_booking, ["booking_confirm", END])

    return graph.compile(checkpointer=checkpointer)
