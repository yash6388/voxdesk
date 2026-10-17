import json
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from app.analytics import TurnRecorder
from app.api.businesses import get_business_or_404
from app.api.deps import SessionDep
from app.conversation import graph_config, pending_confirmation, run_events, turn_input
from app.guardrails import Verdict, check_message
from app.ratelimit import LimiterDep, chat_limits, client_ip
from app.schemas import ChatHistory, ChatMessage, ChatRequest, ChatResume
from app.tracing import trace_turn

router = APIRouter(prefix="/chat", tags=["chat"])


def sse(event: str, data: dict | list) -> str:
    """Format one Server-Sent Event frame."""
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def stream_run(
    graph,
    graph_input,
    config: dict,
    thread_id: str,
    *,
    business_id: str,
    trace_input,
    recorder: TurnRecorder,
) -> AsyncIterator[str]:
    """One traced, recorded turn: the whole run (router, agents, tools, LLM calls) is one
    trace, and its outcome is saved for the Inbox/Analytics when it ends."""
    started, first_token = time.perf_counter(), None
    with trace_turn(
        "chat-turn",
        session_id=config["configurable"]["thread_id"],
        user_id=business_id,
        tags=["chat"],
        input=trace_input,
    ) as turn:
        if turn.trace_url:
            yield sse("trace", {"url": turn.trace_url})
        async for event, data in run_events(graph, graph_input, turn.callbacks(config), thread_id):
            if event == "token" and first_token is None:
                first_token = (time.perf_counter() - started) * 1000
            recorder.observe(event, data)
            yield sse(event, data)
        turn.output(recorder.reply)
    await recorder.save(first_token, (time.perf_counter() - started) * 1000)


async def blocked_reply(
    thread_id: str, verdict: Verdict, recorder: TurnRecorder
) -> AsyncIterator[str]:
    """A guardrail stopped the message before any LLM saw it: answer politely instead."""
    yield sse("meta", {"thread_id": thread_id})
    for event, data in [
        ("guardrail", {"reason": verdict.reason}),
        ("token", {"text": verdict.reply}),
    ]:
        recorder.observe(event, data)
        yield sse(event, data)
    yield sse("done", {})
    await recorder.save()


def streaming_response(events: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("")
async def chat(body: ChatRequest, request: Request, session: SessionDep, limiter: LimiterDep):
    """Send a customer message; the reply streams back as Server-Sent Events."""
    await limiter.enforce(*chat_limits(client_ip(request), str(body.business_id)))
    business = await get_business_or_404(body.business_id, session)
    thread_id = body.thread_id or str(uuid.uuid4())

    # Before any graph/checkpoint work: a blocked message should cost nothing.
    verdict = check_message(body.message, business.name)
    if not verdict.allowed:
        recorder = TurnRecorder(business.id, thread_id, "chat", body.message)
        return streaming_response(blocked_reply(thread_id, verdict, recorder))

    graph = request.app.state.graph
    config = graph_config(business.id, thread_id)
    if body.thread_id and await pending_confirmation(graph, config):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Please confirm or decline the pending action first."
        )

    inputs = turn_input(business, body.message)
    return streaming_response(
        stream_run(
            graph,
            inputs,
            config,
            thread_id,
            business_id=str(business.id),
            trace_input=body.message,
            recorder=TurnRecorder(business.id, thread_id, "chat", body.message),
        )
    )


@router.post("/resume")
async def resume(body: ChatResume, request: Request, session: SessionDep, limiter: LimiterDep):
    """Approve or decline the action the agent is waiting on, and stream the outcome."""
    await limiter.enforce(*chat_limits(client_ip(request), str(body.business_id)))
    await get_business_or_404(body.business_id, session)
    graph = request.app.state.graph
    config = graph_config(body.business_id, body.thread_id)

    if not await pending_confirmation(graph, config):
        raise HTTPException(status.HTTP_409_CONFLICT, "Nothing is waiting for confirmation.")

    command = Command(resume={"approved": body.approved})
    return streaming_response(
        stream_run(
            graph,
            command,
            config,
            body.thread_id,
            business_id=str(body.business_id),
            trace_input={"confirmation": "approved" if body.approved else "declined"},
            recorder=TurnRecorder(
                body.business_id,
                body.thread_id,
                "chat",
                "(confirmed)" if body.approved else "(declined)",
                declined=not body.approved,
            ),
        )
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
