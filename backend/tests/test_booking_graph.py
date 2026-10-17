"""The booking agent's graph (runs inside the Booking Agent A2A service)."""

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.db.session import SessionLocal
from app.graph.booking_graph import build_booking_graph, ungrounded_customer_details
from app.graph.prompts import BOOKING_UNAVAILABLE
from tests.booking_fixtures import create_salon
from tests.fakes import BrokenTools, FakeTools, call, replies, scripted

CONFIG = {"configurable": {"thread_id": "t"}}


def make_graph(chat_llm=None, tool_provider=None):
    return build_booking_graph(
        chat_llm=chat_llm or replies("ok"),
        tool_provider=tool_provider or FakeTools(),
        session_factory=SessionLocal,
        checkpointer=InMemorySaver(),
    )


def turn(business, message: str) -> dict:
    return {
        "messages": [("user", message)],
        "business_id": str(business.id),
        "business_name": business.name,
        "business_timezone": "Asia/Kolkata",
    }


def book_call(service_id, name="Asha Rao", phone="9876543210", time="15:00") -> AIMessage:
    return call(
        "book_appointment",
        service_id=str(service_id),
        date="2030-01-01",
        time=time,
        customer_name=name,
        customer_phone=phone,
    )


async def test_read_tool_runs_without_confirmation(db):
    business, haircut = await create_salon()
    tools = FakeTools()
    llm = scripted(
        call("check_availability", service_id=str(haircut.id), date="2030-01-01"),
        AIMessage("We have 3pm or 4pm."),
    )
    graph = make_graph(llm, tools)

    state = await graph.ainvoke(turn(business, "Any slots tomorrow?"), CONFIG)

    assert tools.ran == ["check_availability"]
    assert state["messages"][-1].text == "We have 3pm or 4pm."
    assert not (await graph.aget_state(CONFIG)).interrupts


async def test_write_tool_pauses_for_confirmation_then_runs_when_approved(db):
    business, haircut = await create_salon()
    tools = FakeTools()
    graph = make_graph(scripted(book_call(haircut.id), AIMessage("You're booked!")), tools)

    await graph.ainvoke(turn(business, "Book a haircut at 3pm, I'm Asha Rao, 98765 43210"), CONFIG)

    [pending] = (await graph.aget_state(CONFIG)).interrupts
    action = pending.value["actions"][0]
    assert action["title"] == "Book appointment"
    assert action["details"]["Service"] == "Haircut"
    assert tools.ran == [], "nothing may be booked before the customer confirms"

    state = await graph.ainvoke(Command(resume={"approved": True}), CONFIG)

    assert tools.ran == ["book_appointment"]
    assert state["messages"][-1].text == "You're booked!"


async def test_declined_action_is_not_executed(db):
    business, haircut = await create_salon()
    tools = FakeTools()
    llm = scripted(book_call(haircut.id, name="Asha"), AIMessage("No problem — anything else?"))
    graph = make_graph(llm, tools)

    await graph.ainvoke(turn(business, "Book 3pm. Asha, 9876543210"), CONFIG)
    state = await graph.ainvoke(Command(resume={"approved": False}), CONFIG)

    assert tools.ran == []
    assert state["messages"][-1].text == "No problem — anything else?"


async def test_invented_customer_details_go_back_to_the_agent(db):
    business, haircut = await create_salon()
    tools = FakeTools()
    llm = scripted(
        # The model invents a name and phone the customer never gave…
        book_call(haircut.id, name="John Doe", phone="+919999999999", time="16:00"),
        # …so the guardrail sends it back and the agent asks instead.
        AIMessage("Could I have your name and phone number?"),
    )
    graph = make_graph(llm, tools)

    state = await graph.ainvoke(turn(business, "4pm works"), CONFIG)

    assert not (await graph.aget_state(CONFIG)).interrupts, "customer must not be asked to confirm"
    assert tools.ran == []
    assert state["messages"][-1].text == "Could I have your name and phone number?"


async def test_unavailable_booking_system_degrades_gracefully(db):
    business, _ = await create_salon()
    graph = make_graph(tool_provider=BrokenTools())

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
