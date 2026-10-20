"""Turn recording, handoff, Inbox and Analytics."""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import select

from app.analytics import TurnRecorder
from app.db.models import Conversation, ConversationStatus, Turn
from app.db.session import SessionLocal
from app.graph.prompts import HANDOFF_REPLY
from app.graph.state import Route
from app.graph.supervisor import build_supervisor
from app.main import app
from tests.fakes import FakeAgent, FakeRouter, replies

# ---------- outcomes derived from the event stream ----------


@pytest.mark.parametrize(
    ("events", "outcome"),
    [
        ([("route", {"intent": "knowledge"}), ("token", {"text": "Yes."})], "answered"),
        ([("route", {"intent": "booking"}), ("confirm", {"actions": []})], "booking_pending"),
        (
            [("tool_result", {"name": "book_appointment", "status": "success", "content": "{}"})],
            "booked",
        ),
        ([("decision", {"approved": False})], "booking_declined"),
        ([("handoff", {"reason": "speak to a person"})], "handoff"),
        ([("guardrail", {"reason": "prompt_injection"})], "guardrail"),
        ([("token", {"text": "x"}), ("error", {"message": "boom"})], "error"),
    ],
)
def test_outcome_is_derived_from_events(events, outcome):
    recorder = TurnRecorder("00000000-0000-0000-0000-000000000001", "t", "chat", "hi")
    for event, data in events:
        recorder.observe(event, data)
    assert recorder.outcome == outcome


def test_confirmation_turns_count_as_booking_intent():
    # Resume turns never pass through the router; they must not show up as "not routed".
    recorder = TurnRecorder(
        "00000000-0000-0000-0000-000000000001", "t", "chat", "(confirmed)", intent="booking"
    )
    recorder.observe("tool_result", {"name": "book_appointment", "status": "success"})
    assert (recorder.intent, recorder.outcome) == ("booking", "booked")


# ---------- persistence ----------


async def make_business():
    from app.db.models import Business

    async with SessionLocal() as session:
        business = Business(name="Salon")
        session.add(business)
        await session.commit()
        return business


async def test_save_upserts_conversation_and_flags_handoff(db):
    business = await make_business()

    first = TurnRecorder(business.id, "thread-1", "chat", "Do you have parking?")
    first.observe("route", {"intent": "knowledge"})
    first.observe("token", {"text": "Yes, six cars."})
    await first.save(first_token_ms=420, total_ms=900)

    second = TurnRecorder(business.id, "thread-1", "chat", "Can I talk to a human?")
    second.observe("route", {"intent": "handoff"})
    second.observe("handoff", {"reason": "Can I talk to a human?"})
    await second.save()

    async with SessionLocal() as session:
        [conversation] = list(await session.scalars(select(Conversation)))
        turns = list(await session.scalars(select(Turn).order_by(Turn.created_at)))
    assert conversation.turn_count == 2
    assert conversation.status == ConversationStatus.NEEDS_HUMAN
    assert conversation.handoff_reason == "Can I talk to a human?"
    assert [t.outcome for t in turns] == ["answered", "handoff"]
    assert turns[0].first_token_ms == 420 and turns[0].reply_text == "Yes, six cars."


# ---------- handoff route in the supervisor ----------


async def test_handoff_intent_flags_and_replies_without_delegating():
    knowledge, booking = FakeAgent("knowledge"), FakeAgent("booking")
    graph = build_supervisor(
        router_llm=FakeRouter(Route(intent="handoff", search_query="")),
        chat_llm=replies("x"),
        knowledge_agent=knowledge,
        booking_agent=booking,
        checkpointer=InMemorySaver(),
    )
    events = []
    async for _mode, payload in graph.astream(
        {
            "messages": [("user", "I want to speak to the manager")],
            "business_id": "b1",
            "business_name": "Glow Studio",
            "business_description": "",
            "business_timezone": "Asia/Kolkata",
        },
        {"configurable": {"thread_id": "b1:t1"}},
        stream_mode=["custom"],
    ):
        events.append(payload)
    assert {"type": "handoff", "reason": "I want to speak to the manager"} in events
    assert {"type": "token", "text": HANDOFF_REPLY.format(business_name="Glow Studio")} in events
    assert knowledge.requests == [] and booking.requests == []


async def test_reply_to_a_handoff_is_answered_not_flagged_again():
    graph = build_supervisor(
        # The router (wrongly) says "handoff" both times; the graph must not repeat itself.
        router_llm=FakeRouter(*[Route(intent="handoff", search_query="")] * 2),
        chat_llm=replies("Thanks Priya, the team will call you."),
        knowledge_agent=FakeAgent("knowledge"),
        booking_agent=FakeAgent("booking"),
        checkpointer=InMemorySaver(),
    )
    state = {
        "business_id": "b1",
        "business_name": "Glow Studio",
        "business_description": "",
        "business_timezone": "Asia/Kolkata",
    }
    config = {"configurable": {"thread_id": "b1:t2"}}
    await graph.ainvoke({**state, "messages": [("user", "Get me a person")]}, config)

    events = []
    async for _mode, payload in graph.astream(
        {**state, "messages": [("user", "I'm Priya, 98765 43210")]},
        config,
        stream_mode=["custom"],
    ):
        events.append(payload)
    assert not any(e.get("type") == "handoff" for e in events)
    final = await graph.aget_state(config)
    assert final.values["intent"] == "smalltalk"
    assert final.values["messages"][-1].text == "Thanks Priya, the team will call you."


# ---------- owner API ----------


class StubGraph:
    async def aget_state(self, config):
        return SimpleNamespace(
            values={"messages": [HumanMessage("Hi"), AIMessage("Hello! How can I help?")]}
        )


@pytest.fixture
async def owner(db):
    app.state.graph = StubGraph()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/auth/signup",
            json={"email": "owner@example.com", "password": "correct-horse", "name": "Owner"},
        )
        business = (await client.post("/businesses", json={"name": "Salon"})).json()
        yield client, business
    del app.state.graph


async def record(business_id, thread, outcome_events, first_token_ms=None, channel="chat"):
    recorder = TurnRecorder(business_id, thread, channel, "question")
    for event, data in outcome_events:
        recorder.observe(event, data)
    await recorder.save(first_token_ms=first_token_ms)


async def test_analytics_aggregates_turns(owner):
    client, business = owner
    bid = business["id"]
    await record(bid, "a", [("route", {"intent": "knowledge"})], first_token_ms=300)
    await record(bid, "a", [("route", {"intent": "knowledge"})], first_token_ms=500)
    await record(
        bid,
        "b",
        [
            ("route", {"intent": "booking"}),
            ("tool_result", {"name": "book_appointment", "status": "success"}),
        ],
        first_token_ms=700,
        channel="voice",
    )
    await record(bid, "c", [("handoff", {"reason": "human please"})])
    await record(bid, "d", [("guardrail", {"reason": "prompt_injection"})])

    data = (await client.get(f"/businesses/{bid}/analytics?days=7")).json()
    assert data["turns"] == 5 and data["conversations"] == 4
    assert data["bookings"] == 1 and data["handoffs"] == 1 and data["guardrail_blocks"] == 1
    assert data["needs_human_open"] == 1
    assert data["intents"]["knowledge"] == 2
    assert data["channels"] == {"chat": 3, "voice": 1}
    assert data["first_token_p50_ms"] == 500
    assert len(data["daily"]) == 7 and data["daily"][-1]["turns"] == 5


async def test_inbox_lists_resolves_and_shows_transcript(owner):
    client, business = owner
    bid = business["id"]
    await record(bid, "needs-help", [("handoff", {"reason": "talk to a person"})])
    await record(bid, "fine", [("route", {"intent": "knowledge"})])

    inbox = (await client.get(f"/businesses/{bid}/conversations?status=needs_human")).json()
    assert [c["thread_id"] for c in inbox] == ["needs-help"]
    assert inbox[0]["handoff_reason"] == "talk to a person"
    assert inbox[0]["last_message"] == "question"

    detail = (await client.get(f"/businesses/{bid}/conversations/{inbox[0]['id']}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]

    resolved = await client.post(f"/businesses/{bid}/conversations/{inbox[0]['id']}/resolve")
    assert resolved.json()["status"] == "resolved"
    assert (await client.get(f"/businesses/{bid}/conversations?status=needs_human")).json() == []


async def test_other_owners_cannot_read_insights(owner):
    _, business = owner
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
        await other.post(
            "/auth/signup",
            json={"email": "other@example.com", "password": "correct-horse", "name": "Other"},
        )
        assert (await other.get(f"/businesses/{business['id']}/analytics")).status_code == 404
        assert (await other.get(f"/businesses/{business['id']}/conversations")).status_code == 404
