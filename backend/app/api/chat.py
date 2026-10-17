import json
import logging
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.api.businesses import get_business_or_404
from app.api.deps import SessionDep
from app.schemas import ChatHistory, ChatMessage, ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def sse(event: str, data: dict | list) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def graph_config(business_id: uuid.UUID, thread_id: str) -> dict:
    # Namespacing by business stops one tenant from reading another's thread.
    return {"configurable": {"thread_id": f"{business_id}:{thread_id}"}}


@router.post("")
async def chat(body: ChatRequest, request: Request, session: SessionDep):
    """Streams the reply as Server-Sent Events:
    `meta` (thread_id) → `route` (intent) → `sources` → `token`* → `done` (or `error`)."""
    business = await get_business_or_404(body.business_id, session)
    thread_id = body.thread_id or str(uuid.uuid4())
    graph = request.app.state.graph

    inputs = {
        "messages": [("user", body.message)],
        "business_id": str(business.id),
        "business_name": business.name,
        "business_description": business.description,
    }

    async def events() -> AsyncIterator[str]:
        yield sse("meta", {"thread_id": thread_id})
        try:
            # "messages" mode yields LLM tokens as they're generated;
            # "updates" mode yields each node's output when the node finishes.
            async for mode, payload in graph.astream(
                inputs, graph_config(business.id, thread_id), stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    chunk, metadata = payload
                    # Only stream the user-facing node, not the router's structured output.
                    if metadata.get("langgraph_node") == "respond" and chunk.text:
                        yield sse("token", {"text": chunk.text})
                    continue

                for node, update in payload.items():
                    if node == "route":
                        yield sse("route", {k: update[k] for k in ("intent", "search_query")})
                    elif node == "retrieve":
                        yield sse(
                            "sources",
                            [
                                {k: c[k] for k in ("filename", "chunk_index", "content", "score")}
                                for c in update["context"]
                            ],
                        )
                    elif node == "booking":
                        yield sse("token", {"text": update["messages"][-1].text})
        except Exception:
            logger.exception("Chat stream failed (thread %s)", thread_id)
            yield sse("error", {"message": "Something went wrong. Please try again."})
            return
        yield sse("done", {})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{business_id}/{thread_id}", response_model=ChatHistory)
async def get_history(
    business_id: uuid.UUID,
    thread_id: str,
    request: Request,
    session: SessionDep,
):
    """Conversation so far, read back from the LangGraph checkpoint."""
    await get_business_or_404(business_id, session)
    snapshot = await request.app.state.graph.aget_state(graph_config(business_id, thread_id))
    messages = snapshot.values.get("messages", []) if snapshot.values else []
    return ChatHistory(
        thread_id=thread_id,
        messages=[
            ChatMessage(role="user" if m.type == "human" else "assistant", content=m.text)
            for m in messages
            if m.type in ("human", "ai")
        ],
    )
