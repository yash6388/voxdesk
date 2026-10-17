"""Running one conversation turn through the supervisor graph, independent of transport.
Text chat wraps these events as Server-Sent Events; voice sends them over a WebSocket."""

import logging
import uuid
from collections.abc import AsyncIterator

from app.db.models import Business
from app.errors import is_rate_limited

logger = logging.getLogger(__name__)

# Supervisor nodes whose own LLM output is streamed (small talk). Remote agents'
# output arrives through the "custom" stream instead.
STREAMED_NODES = {"respond"}
# Events relayed from remote agents (see graph/supervisor.py `delegate`).
RELAYED = {"token", "sources", "tool_call", "tool_result", "delegation"}

Event = tuple[str, dict | list]


def graph_config(business_id: uuid.UUID, thread_id: str) -> dict:
    # Namespacing by business stops one tenant from reading another's thread.
    return {"configurable": {"thread_id": f"{business_id}:{thread_id}"}}


def turn_input(business: Business, message: str) -> dict:
    return {
        "messages": [("user", message)],
        "business_id": str(business.id),
        "business_name": business.name,
        "business_description": business.description,
        "business_timezone": business.timezone,
    }


async def pending_confirmation(graph, config: dict) -> dict | None:
    snapshot = await graph.aget_state(config)
    return snapshot.interrupts[0].value if snapshot.interrupts else None


async def run_events(graph, graph_input, config: dict, thread_id: str) -> AsyncIterator[Event]:
    """Run the graph and translate its progress into (event, data) pairs:
    meta → route → delegation / sources / tool_call / tool_result … → token* → confirm? → done."""
    yield "meta", {"thread_id": thread_id}
    try:
        # "messages": LLM tokens from the supervisor itself (small talk);
        # "custom":   events relayed from the A2A agents (tokens, sources, tool calls…);
        # "updates":  each node's output when it finishes (routing, interrupts).
        async for mode, payload in graph.astream(
            graph_input, config, stream_mode=["messages", "custom", "updates"]
        ):
            if mode == "messages":
                chunk, metadata = payload
                if metadata.get("langgraph_node") in STREAMED_NODES and chunk.text:
                    yield "token", {"text": chunk.text}
            elif mode == "custom":
                kind = payload.get("type")
                if kind == "token":
                    yield "token", {"text": payload["text"]}
                elif kind in RELAYED:
                    yield kind, payload.get("data", payload)
            else:
                for node, update in payload.items():
                    if node == "__interrupt__":
                        # The graph paused in `booking_confirm`: ask the customer to approve.
                        yield "confirm", update[0].value
                    elif node == "route" and update:
                        yield "route", {k: update[k] for k in ("intent", "search_query")}
    except Exception as exc:
        if is_rate_limited(exc):
            logger.warning("LLM rate limit hit (thread %s)", thread_id)
            message = (
                "Our assistant is handling too many requests right now. Please try again shortly."
            )
        else:
            logger.exception("Conversation turn failed (thread %s)", thread_id)
            message = "Something went wrong. Please try again."
        yield "error", {"message": message}
        return
    yield "done", {}
