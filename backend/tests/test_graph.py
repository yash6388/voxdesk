from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langgraph.checkpoint.memory import InMemorySaver

from app.db.session import SessionLocal
from app.graph.builder import build_graph
from app.graph.prompts import BOOKING_UNAVAILABLE
from app.graph.state import Route
from tests.test_rag import SALON_DOC, create_business_with_doc


class FakeRouter:
    """Stands in for the router LLM: returns pre-scripted routing decisions."""

    def __init__(self, *routes: Route):
        self._routes = iter(routes)

    def with_structured_output(self, schema):
        return RunnableLambda(lambda _: next(self._routes))


def make_graph(router: FakeRouter, embedder, reply: str = "Fake answer [1]."):
    return build_graph(
        # A fresh message per reply: LangGraph de-duplicates messages by id.
        chat_llm=GenericFakeChatModel(messages=(AIMessage(reply) for _ in range(100))),
        router_llm=router,
        embedder=embedder,
        session_factory=SessionLocal,
        checkpointer=InMemorySaver(),
    )


def turn(business, message: str) -> dict:
    return {
        "messages": [("user", message)],
        "business_id": str(business.id),
        "business_name": business.name,
        "business_description": "",
    }


async def test_knowledge_question_retrieves_context_then_answers(db, fake_embedder):
    business = await create_business_with_doc("Salon", SALON_DOC, fake_embedder)
    graph = make_graph(FakeRouter(Route(intent="knowledge", search_query="parking")), fake_embedder)

    state = await graph.ainvoke(turn(business, "Can I park?"), {"configurable": {"thread_id": "t"}})

    assert state["context"], "retrieve node should have filled context"
    assert state["messages"][-1].text == "Fake answer [1]."


async def test_booking_request_skips_llm_and_returns_placeholder(db, fake_embedder):
    business = await create_business_with_doc("Salon", SALON_DOC, fake_embedder)
    graph = make_graph(FakeRouter(Route(intent="booking", search_query="")), fake_embedder)

    state = await graph.ainvoke(turn(business, "Book me in"), {"configurable": {"thread_id": "t"}})

    assert state["messages"][-1].text == BOOKING_UNAVAILABLE
    assert state["context"] == []


async def test_conversation_memory_persists_across_turns(db, fake_embedder):
    business = await create_business_with_doc("Salon", SALON_DOC, fake_embedder)
    graph = make_graph(
        FakeRouter(
            Route(intent="smalltalk", search_query=""),
            Route(intent="smalltalk", search_query=""),
        ),
        fake_embedder,
        reply="Hello!",
    )
    config = {"configurable": {"thread_id": "same-thread"}}

    await graph.ainvoke(turn(business, "Hi"), config)
    state = await graph.ainvoke(turn(business, "Hi again"), config)

    assert [m.type for m in state["messages"]] == ["human", "ai", "human", "ai"]
