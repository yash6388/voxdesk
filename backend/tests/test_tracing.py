from langgraph.checkpoint.memory import InMemorySaver

from app.graph import supervisor
from app.graph.state import Route
from app.tracing import PARENT_SPAN_KEY, TRACE_ID_KEY, parent_context, trace_metadata, trace_turn
from tests.fakes import FakeAgent, FakeRouter, answer, replies


def test_tracing_is_a_no_op_without_keys():
    with trace_turn("chat-turn", session_id="s", user_id="u", tags=["chat"]) as turn:
        assert turn.handler is None and turn.trace_url is None
        assert turn.callbacks({"configurable": {"thread_id": "t"}}) == {
            "configurable": {"thread_id": "t"}
        }
        turn.output("ignored")  # must not fail
        with turn.step("speech-to-text") as step:
            assert step is None
    assert trace_metadata() == {}


def test_parent_context_continues_the_callers_trace():
    assert parent_context(None) is None
    assert parent_context({"business_id": "b"}) is None
    assert parent_context({TRACE_ID_KEY: "t1"}) == {"trace_id": "t1"}
    assert parent_context({TRACE_ID_KEY: "t1", PARENT_SPAN_KEY: "s1"}) == {
        "trace_id": "t1",
        "parent_span_id": "s1",
    }


async def test_supervisor_sends_trace_ids_to_the_remote_agent(monkeypatch):
    monkeypatch.setattr(
        supervisor, "trace_metadata", lambda: {TRACE_ID_KEY: "trace-1", PARENT_SPAN_KEY: "span-1"}
    )
    knowledge = FakeAgent("knowledge", answer("Yes."))
    graph = supervisor.build_supervisor(
        router_llm=FakeRouter(Route(intent="knowledge", search_query="parking")),
        chat_llm=replies("x"),
        knowledge_agent=knowledge,
        booking_agent=FakeAgent("booking"),
        checkpointer=InMemorySaver(),
    )
    await graph.ainvoke(
        {
            "messages": [("user", "parking?")],
            "business_id": "b1",
            "business_name": "Glow",
            "business_description": "",
            "business_timezone": "Asia/Kolkata",
        },
        {"configurable": {"thread_id": "b1:t1"}},
    )
    metadata = knowledge.requests[0]["metadata"]
    assert metadata[TRACE_ID_KEY] == "trace-1" and metadata[PARENT_SPAN_KEY] == "span-1"
    assert metadata["business_id"] == "b1"  # business info still there
