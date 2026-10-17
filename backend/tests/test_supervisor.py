"""The API's supervisor graph, with the remote A2A agents replaced by scripted fakes."""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.a2a.client import AgentEvent
from app.graph.prompts import BOOKING_UNAVAILABLE, KNOWLEDGE_UNAVAILABLE
from app.graph.state import Route
from app.graph.supervisor import build_supervisor
from tests.fakes import FakeAgent, FakeRouter, answer, replies

CONFIG = {"configurable": {"thread_id": "biz-1:thread-1"}}
KNOWLEDGE = Route(intent="knowledge", search_query="keratin treatment price")
BOOKING = Route(intent="booking", search_query="")
SMALLTALK = Route(intent="smalltalk", search_query="")


def make(router, knowledge=None, booking=None, chat_reply="Hello!"):
    return build_supervisor(
        router_llm=router,
        chat_llm=replies(chat_reply),
        knowledge_agent=knowledge or FakeAgent("knowledge"),
        booking_agent=booking or FakeAgent("booking"),
        checkpointer=InMemorySaver(),
    )


def turn(message: str) -> dict:
    return {
        "messages": [("user", message)],
        "business_id": "biz-1",
        "business_name": "Glow Studio",
        "business_description": "",
        "business_timezone": "Asia/Kolkata",
    }


async def run(graph, graph_input) -> list[dict]:
    """Collect the custom events the supervisor relays to the client."""
    events = []
    async for mode, payload in graph.astream(graph_input, CONFIG, stream_mode=["custom", "values"]):
        if mode == "custom":
            events.append(payload)
    return events


async def test_knowledge_question_is_delegated_with_the_rewritten_query(db):
    knowledge = FakeAgent("knowledge", answer("It costs ", "₹6,500 [1]."))
    graph = make(FakeRouter(KNOWLEDGE), knowledge=knowledge)

    events = await run(graph, turn("and how much is it?"))

    [request] = knowledge.requests
    assert request["text"] == "keratin treatment price"  # standalone query, not the raw follow-up
    assert request["context_id"] == "biz-1:thread-1"
    assert request["metadata"]["business_id"] == "biz-1"
    assert [e["text"] for e in events if e["type"] == "token"] == ["It costs ", "₹6,500 [1]."]
    assert events[-1] == {
        "type": "delegation",
        "agent": "knowledge",
        "task_id": "t-1",
        "state": "completed",
    }
    state = await graph.aget_state(CONFIG)
    assert state.values["messages"][-1].text == "It costs ₹6,500 [1]."


async def test_sources_from_the_agent_are_relayed(db):
    sources = [{"filename": "faq.md", "chunk_index": 0, "content": "…", "score": 0.03}]
    knowledge = FakeAgent(
        "knowledge",
        [AgentEvent("data", name="sources", data=sources), *answer("Yes [1].")],
    )
    events = await run(make(FakeRouter(KNOWLEDGE), knowledge=knowledge), turn("parking?"))
    assert {"type": "sources", "data": sources} in events


async def test_small_talk_is_answered_locally_without_delegating(db):
    knowledge, booking = FakeAgent("knowledge"), FakeAgent("booking")
    graph = make(FakeRouter(SMALLTALK, SMALLTALK), knowledge, booking)

    await run(graph, turn("Hi"))
    await run(graph, turn("Thanks!"))

    assert knowledge.requests == [] and booking.requests == []
    messages = (await graph.aget_state(CONFIG)).values["messages"]
    assert [m.type for m in messages] == ["human", "ai", "human", "ai"]


async def test_booking_confirmation_round_trip_over_a2a(db):
    actions = [{"title": "Book appointment", "details": {"Service": "Haircut"}}]
    booking = FakeAgent(
        "booking",
        [
            AgentEvent("task", task_id="task-9"),
            AgentEvent("input_required", task_id="task-9", data={"actions": actions}),
        ],
        answer("You're booked!", task_id="task-9"),
    )
    graph = make(FakeRouter(BOOKING), booking=booking)

    await run(graph, turn("Book a haircut at 3pm, I'm Asha, 9876543210"))

    # The supervisor paused with the agent's actions — the UI shows the confirm card.
    [pending] = (await graph.aget_state(CONFIG)).interrupts
    assert pending.value == {"actions": actions}

    await run(graph, Command(resume={"approved": True}))

    # The decision went back to the SAME A2A task, as data.
    resume_request = booking.requests[1]
    assert resume_request["task_id"] == "task-9"
    assert resume_request["data"] == {"approved": True}
    state = await graph.aget_state(CONFIG)
    assert not state.interrupts
    assert state.values["messages"][-1].text == "You're booked!"
    assert state.values["pending_booking"] is None


async def test_unreachable_agent_gets_a_helpful_fallback(db):
    knowledge = FakeAgent("knowledge", ConnectionError("agent down"))
    events = await run(make(FakeRouter(KNOWLEDGE), knowledge=knowledge), turn("hours?"))

    assert {"type": "token", "text": KNOWLEDGE_UNAVAILABLE} in events
    assert events[-1]["state"] == "failed"


async def test_failed_agent_message_is_shown_to_the_customer(db):
    busy = "Our assistant is handling too many requests right now. Please try again shortly."
    booking = FakeAgent(
        "booking", [AgentEvent("task", task_id="t"), AgentEvent("failed", text=busy)]
    )
    graph = make(FakeRouter(BOOKING), booking=booking)

    await run(graph, turn("book me in"))

    messages = (await graph.aget_state(CONFIG)).values["messages"]
    assert messages[-1].text == busy
    assert busy != BOOKING_UNAVAILABLE
