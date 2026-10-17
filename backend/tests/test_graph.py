from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.db.session import SessionLocal
from app.graph.builder import build_graph, ungrounded_customer_details
from app.graph.prompts import BOOKING_UNAVAILABLE
from app.graph.state import Route
from tests.booking_fixtures import create_salon
from tests.test_rag import SALON_DOC, create_business_with_doc

BOOKING = Route(intent="booking", search_query="")


class FakeRouter:
    """Stands in for the router LLM: returns pre-scripted routing decisions."""

    def __init__(self, *routes: Route):
        self._routes = iter(routes)

    def with_structured_output(self, schema):
        return RunnableLambda(lambda _: next(self._routes))


class FakeToolLLM(GenericFakeChatModel):
    """Scripted chat model that also accepts bind_tools (the real one sends tool schemas)."""

    def bind_tools(self, tools, **kwargs):
        return self


def scripted(*replies: AIMessage) -> FakeToolLLM:
    return FakeToolLLM(messages=iter(replies))


def call(name: str, call_id: str = "c1", **args) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": call_id}])


class FakeTools:
    """Local stand-ins for the MCP booking tools, recording what actually ran."""

    def __init__(self):
        self.ran: list[str] = []

        @tool
        def check_availability(service_id: str, date: str) -> str:
            """Free times."""
            self.ran.append("check_availability")
            return '{"available_times": ["15:00", "16:00"]}'

        @tool
        def book_appointment(
            service_id: str, date: str, time: str, customer_name: str, customer_phone: str
        ) -> str:
            """Book."""
            self.ran.append("book_appointment")
            return '{"status": "confirmed"}'

        self._tools = [check_availability, book_appointment]

    async def get_tools(self, business_id: str):
        return self._tools


class BrokenTools:
    async def get_tools(self, business_id: str):
        raise ConnectionError("MCP server down")


def make_graph(router, embedder, chat_llm=None, tool_provider=None, reply="Fake answer [1]."):
    return build_graph(
        # A fresh message per reply: LangGraph de-duplicates messages by id.
        chat_llm=chat_llm or GenericFakeChatModel(messages=(AIMessage(reply) for _ in range(100))),
        router_llm=router,
        embedder=embedder,
        session_factory=SessionLocal,
        tool_provider=tool_provider or FakeTools(),
        checkpointer=InMemorySaver(),
    )


def turn(business, message: str) -> dict:
    return {
        "messages": [("user", message)],
        "business_id": str(business.id),
        "business_name": business.name,
        "business_description": "",
        "business_timezone": "Asia/Kolkata",
    }


CONFIG = {"configurable": {"thread_id": "t"}}


# ---------- Routing, RAG, memory ----------


async def test_knowledge_question_retrieves_context_then_answers(db, fake_embedder):
    business = await create_business_with_doc("Salon", SALON_DOC, fake_embedder)
    graph = make_graph(FakeRouter(Route(intent="knowledge", search_query="parking")), fake_embedder)

    state = await graph.ainvoke(turn(business, "Can I park?"), CONFIG)

    assert state["context"], "retrieve node should have filled context"
    assert state["messages"][-1].text == "Fake answer [1]."


async def test_conversation_memory_persists_across_turns(db, fake_embedder):
    business = await create_business_with_doc("Salon", SALON_DOC, fake_embedder)
    smalltalk = Route(intent="smalltalk", search_query="")
    graph = make_graph(FakeRouter(smalltalk, smalltalk), fake_embedder, reply="Hello!")

    await graph.ainvoke(turn(business, "Hi"), CONFIG)
    state = await graph.ainvoke(turn(business, "Hi again"), CONFIG)

    assert [m.type for m in state["messages"]] == ["human", "ai", "human", "ai"]


# ---------- Booking agent ----------


async def test_read_tool_runs_without_confirmation(db, fake_embedder):
    business, haircut = await create_salon()
    tools = FakeTools()
    llm = scripted(
        call("check_availability", service_id=str(haircut.id), date="2030-01-01"),
        AIMessage("We have 3pm or 4pm."),
    )
    graph = make_graph(FakeRouter(BOOKING), fake_embedder, llm, tools)

    state = await graph.ainvoke(turn(business, "Any slots tomorrow?"), CONFIG)

    assert tools.ran == ["check_availability"]
    assert state["messages"][-1].text == "We have 3pm or 4pm."
    assert not (await graph.aget_state(CONFIG)).interrupts


async def test_write_tool_pauses_for_confirmation_then_runs_when_approved(db, fake_embedder):
    business, haircut = await create_salon()
    tools = FakeTools()
    llm = scripted(
        call(
            "book_appointment",
            service_id=str(haircut.id),
            date="2030-01-01",
            time="15:00",
            customer_name="Asha Rao",
            customer_phone="9876543210",
        ),
        AIMessage("You're booked!"),
    )
    graph = make_graph(FakeRouter(BOOKING), fake_embedder, llm, tools)

    await graph.ainvoke(turn(business, "Book a haircut at 3pm, I'm Asha Rao, 98765 43210"), CONFIG)

    snapshot = await graph.aget_state(CONFIG)
    [pending] = snapshot.interrupts
    action = pending.value["actions"][0]
    assert action["title"] == "Book appointment"
    assert action["details"]["Service"] == "Haircut"
    assert tools.ran == [], "nothing may be booked before the customer confirms"

    state = await graph.ainvoke(Command(resume={"approved": True}), CONFIG)

    assert tools.ran == ["book_appointment"]
    assert state["messages"][-1].text == "You're booked!"


async def test_declined_action_is_not_executed(db, fake_embedder):
    business, haircut = await create_salon()
    tools = FakeTools()
    llm = scripted(
        call(
            "book_appointment",
            service_id=str(haircut.id),
            date="2030-01-01",
            time="15:00",
            customer_name="Asha",
            customer_phone="9876543210",
        ),
        AIMessage("No problem — anything else?"),
    )
    graph = make_graph(FakeRouter(BOOKING), fake_embedder, llm, tools)

    await graph.ainvoke(turn(business, "Book 3pm. Asha, 9876543210"), CONFIG)
    state = await graph.ainvoke(Command(resume={"approved": False}), CONFIG)

    assert tools.ran == []
    assert state["messages"][-1].text == "No problem — anything else?"


async def test_invented_customer_details_go_back_to_the_agent(db, fake_embedder):
    business, haircut = await create_salon()
    tools = FakeTools()
    llm = scripted(
        # The model invents a name and phone the customer never gave…
        call(
            "book_appointment",
            service_id=str(haircut.id),
            date="2030-01-01",
            time="16:00",
            customer_name="John Doe",
            customer_phone="+919999999999",
        ),
        # …so the guardrail sends it back and the agent asks instead.
        AIMessage("Could I have your name and phone number?"),
    )
    graph = make_graph(FakeRouter(BOOKING), fake_embedder, llm, tools)

    state = await graph.ainvoke(turn(business, "4pm works"), CONFIG)

    assert not (await graph.aget_state(CONFIG)).interrupts, "customer must not be asked to confirm"
    assert tools.ran == []
    assert state["messages"][-1].text == "Could I have your name and phone number?"


async def test_unavailable_booking_system_degrades_gracefully(db, fake_embedder):
    business, _ = await create_salon()
    graph = make_graph(FakeRouter(BOOKING), fake_embedder, tool_provider=BrokenTools())

    state = await graph.ainvoke(turn(business, "Book me in"), CONFIG)

    assert state["messages"][-1].text == BOOKING_UNAVAILABLE


def test_grounding_guardrail():
    said = "I'm Yash Singh, my number is 98765 43210"
    assert (
        ungrounded_customer_details(
            {"customer_name": "Yash Singh", "customer_phone": "+91 9876543210"}, said
        )
        == []
    )
    assert ungrounded_customer_details(
        {"customer_name": "John Doe", "customer_phone": "1112223334"}, said
    ) == ["phone number", "name"]
