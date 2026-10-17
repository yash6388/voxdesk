"""The real A2A protocol, end to end: each agent service runs in-process and our A2A client
talks to it over HTTP (Agent Card discovery, JSON-RPC, streaming, auth, input-required)."""

import uuid

import httpx
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.a2a.client import A2AAgent
from app.agents.booking import BookingAgentExecutor
from app.agents.booking import create_app as booking_app
from app.agents.knowledge import KnowledgeAgentExecutor
from app.agents.knowledge import create_app as knowledge_app
from app.config import get_settings
from app.db.session import SessionLocal
from app.graph.booking_graph import build_booking_graph
from tests.booking_fixtures import create_salon
from tests.fakes import FakeTools, call, replies, scripted
from tests.test_rag import SALON_DOC, create_business_with_doc

KEY = get_settings().a2a_api_key


def client_for(app, name: str, base_url: str, key: str = KEY) -> A2AAgent:
    http = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), headers={"Authorization": f"Bearer {key}"}
    )
    return A2AAgent(name, base_url, key, http=http)


async def collect(agent: A2AAgent, **request) -> list:
    return [e async for e in agent.stream(**request)]


def meta(business) -> dict:
    return {
        "business_id": str(business.id),
        "business_name": business.name,
        "business_timezone": "Asia/Kolkata",
    }


async def test_agent_card_is_public_and_describes_skills():
    app = knowledge_app(KnowledgeAgentExecutor(replies("x"), None, SessionLocal))
    agent = client_for(app, "knowledge", get_settings().knowledge_agent_url, key="wrong")

    card = await agent.card()

    assert card.name == "VoxDesk Knowledge Agent"
    assert card.capabilities.streaming
    assert [s.id for s in card.skills] == ["answer_business_question"]
    assert "bearer" in card.security_schemes


async def test_messages_without_the_api_key_are_rejected():
    app = knowledge_app(KnowledgeAgentExecutor(replies("x"), None, SessionLocal))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as http:
        response = await http.post("http://agent/", json={"jsonrpc": "2.0", "id": 1})
    assert response.status_code == 401


async def test_knowledge_agent_streams_answer_and_sources(db, fake_embedder):
    business = await create_business_with_doc("Salon", SALON_DOC, fake_embedder)
    executor = KnowledgeAgentExecutor(
        replies("Free basement parking for six cars [1]."), fake_embedder, SessionLocal
    )
    agent = client_for(knowledge_app(executor), "knowledge", get_settings().knowledge_agent_url)

    events = await collect(
        agent, text="Is there parking?", context_id=str(uuid.uuid4()), metadata=meta(business)
    )

    kinds = [e.kind for e in events]
    assert kinds[0] == "task" and kinds[-1] == "completed"
    sources = next(e for e in events if e.kind == "data" and e.name == "sources")
    assert sources.data and "filename" in sources.data[0]
    text = "".join(e.text for e in events if e.kind == "token")
    assert text == "Free basement parking for six cars [1]."


async def test_booking_agent_input_required_then_resume_on_same_task(db):
    business, haircut = await create_salon()
    tools = FakeTools()
    graph = build_booking_graph(
        chat_llm=scripted(
            call(
                "book_appointment",
                service_id=str(haircut.id),
                date="2030-01-01",
                time="15:00",
                customer_name="Asha",
                customer_phone="9876543210",
            ),
            AIMessage("You're booked for 3pm!"),
        ),
        tool_provider=tools,
        session_factory=SessionLocal,
        checkpointer=InMemorySaver(),
    )
    app = booking_app(BookingAgentExecutor(graph))
    agent = client_for(app, "booking", get_settings().booking_agent_url)
    context = str(uuid.uuid4())

    first = await collect(
        agent, text="Book 3pm, I'm Asha, 9876543210", context_id=context, metadata=meta(business)
    )

    paused = first[-1]
    assert paused.kind == "input_required"
    assert paused.data["actions"][0]["title"] == "Book appointment"
    assert any(e.kind == "data" and e.name == "tool_call" for e in first)
    assert tools.ran == []

    second = await collect(
        agent,
        data={"approved": True},
        task_id=paused.task_id,
        context_id=context,
        metadata=meta(business),
    )

    assert tools.ran == ["book_appointment"]
    assert second[-1].kind == "completed"
    assert "".join(e.text for e in second if e.kind == "token") == "You're booked for 3pm!"
