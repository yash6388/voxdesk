import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from app.api.businesses import get_business_or_404
from app.api.deps import SessionDep
from app.errors import is_rate_limited
from app.schemas import ChatHistory, ChatMessage, ChatRequest, ChatResume

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Supervisor nodes whose own LLM output is streamed (small talk). Remote agents'
# output arrives through the "custom" stream instead.
STREAMED_NODES = {"respond"}
# Events relayed from remote agents (see graph/supervisor.py `delegate`).
RELAYED = {"token", "sources", "tool_call", "tool_result", "delegation"}


def sse(event: str, data: dict | list) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def graph_config(business_id: uuid.UUID, thread_id: str) -> dict:
    # Namespacing by business stops one tenant from reading another's thread.
    return {"configurable": {"thread_id": f"{business_id}:{thread_id}"}}


async def stream_run(graph, graph_input, config: dict, thread_id: str) -> AsyncIterator[str]:
    """Run the graph and translate its progress into SSE events:
    meta → route → delegation / sources / tool_call / tool_result … → token* → confirm? → done."""
    yield sse("meta", {"thread_id": thread_id})
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
                    yield sse("token", {"text": chunk.text})
            elif mode == "custom":
                kind = payload.get("type")
                if kind == "token":
                    yield sse("token", {"text": payload["text"]})
                elif kind in RELAYED:
                    yield sse(kind, payload.get("data", payload))
            else:
                for node, update in payload.items():
                    if node == "__interrupt__":
                        # The graph paused in `booking_confirm`: ask the customer to approve.
                        yield sse("confirm", update[0].value)
                    elif node == "route" and update:
                        yield sse("route", {k: update[k] for k in ("intent", "search_query")})
    except Exception as exc:
        if is_rate_limited(exc):
            logger.warning("LLM rate limit hit (thread %s)", thread_id)
            message = (
                "Our assistant is handling too many requests right now. Please try again shortly."
            )
        else:
            logger.exception("Chat stream failed (thread %s)", thread_id)
            message = "Something went wrong. Please try again."
        yield sse("error", {"message": message})
        return
    yield sse("done", {})


def streaming_response(events: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def pending_confirmation(graph, config: dict) -> dict | None:
    snapshot = await graph.aget_state(config)
    return snapshot.interrupts[0].value if snapshot.interrupts else None


@router.post("")
async def chat(body: ChatRequest, request: Request, session: SessionDep):
    """Send a customer message; the reply streams back as Server-Sent Events."""
    business = await get_business_or_404(body.business_id, session)
    thread_id = body.thread_id or str(uuid.uuid4())
    graph = request.app.state.graph
    config = graph_config(business.id, thread_id)

    if body.thread_id and await pending_confirmation(graph, config):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Please confirm or decline the pending action first."
        )

    inputs = {
        "messages": [("user", body.message)],
        "business_id": str(business.id),
        "business_name": business.name,
        "business_description": business.description,
        "business_timezone": business.timezone,
    }
    return streaming_response(stream_run(graph, inputs, config, thread_id))


@router.post("/resume")
async def resume(body: ChatResume, request: Request, session: SessionDep):
    """Approve or decline the action the agent is waiting on, and stream the outcome."""
    await get_business_or_404(body.business_id, session)
    graph = request.app.state.graph
    config = graph_config(body.business_id, body.thread_id)

    if not await pending_confirmation(graph, config):
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is waiting for confirmation.")

    command = Command(resume={"approved": body.approved})
    return streaming_response(stream_run(graph, command, config, body.thread_id))


@router.get("/{business_id}/{thread_id}", response_model=ChatHistory)
async def get_history(
    business_id: uuid.UUID,
    thread_id: str,
    request: Request,
    session: SessionDep,
):
    """Conversation so far, read back from the LangGraph checkpoint."""
    await get_business_or_404(business_id, session)
    graph = request.app.state.graph
    config = graph_config(business_id, thread_id)
    snapshot = await graph.aget_state(config)
    messages = snapshot.values.get("messages", []) if snapshot.values else []
    return ChatHistory(
        thread_id=thread_id,
        messages=[
            ChatMessage(role="user" if m.type == "human" else "assistant", content=m.text)
            for m in messages
            if m.type == "human" or (m.type == "ai" and m.text)
        ],
        pending_confirmation=snapshot.interrupts[0].value if snapshot.interrupts else None,
    )
