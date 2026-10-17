import uuid
from dataclasses import asdict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.graph.prompts import BOOKING_UNAVAILABLE, RESPOND_PROMPT, ROUTER_PROMPT
from app.graph.state import ChatState, Route
from app.rag.embeddings import Embedder
from app.rag.retrieval import hybrid_search

# How many past messages the LLM sees. Older ones stay in the checkpoint but
# aren't sent, which bounds latency and token cost on long conversations.
HISTORY_WINDOW = 10


def build_graph(
    *,
    chat_llm: BaseChatModel,
    router_llm: BaseChatModel,
    embedder: Embedder,
    session_factory: async_sessionmaker,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """
    START → route ─┬─ knowledge → retrieve → respond → END
                   ├─ smalltalk ───────────→ respond → END
                   └─ booking → booking ────────────→ END
    """
    structured_router = router_llm.with_structured_output(Route)

    async def route(state: ChatState) -> dict:
        system = SystemMessage(ROUTER_PROMPT.format(business_name=state["business_name"]))
        decision: Route = await structured_router.ainvoke(
            [system, *state["messages"][-HISTORY_WINDOW:]]
        )
        # Reset per-turn fields so last turn's context doesn't leak into this one.
        return {"intent": decision.intent, "search_query": decision.search_query, "context": []}

    async def retrieve(state: ChatState) -> dict:
        query = state["search_query"] or state["messages"][-1].content
        async with session_factory() as session:
            chunks = await hybrid_search(session, embedder, uuid.UUID(state["business_id"]), query)
        return {"context": [asdict(c) for c in chunks]}

    async def respond(state: ChatState) -> dict:
        context = (
            "\n\n".join(
                f"[{i}] (from {c['filename']})\n{c['content']}"
                for i, c in enumerate(state["context"], start=1)
            )
            or "(no context retrieved)"
        )
        system = SystemMessage(
            RESPOND_PROMPT.format(
                business_name=state["business_name"],
                business_description=state["business_description"],
                context=context,
            )
        )
        reply = await chat_llm.ainvoke([system, *state["messages"][-HISTORY_WINDOW:]])
        return {"messages": [reply]}

    async def booking(state: ChatState) -> dict:
        # Placeholder until Phase 2 wires in the MCP booking tools.
        return {"messages": [AIMessage(BOOKING_UNAVAILABLE)]}

    def after_route(state: ChatState) -> str:
        return {"knowledge": "retrieve", "booking": "booking"}.get(state["intent"], "respond")

    graph = StateGraph(ChatState)
    graph.add_node("route", route)
    graph.add_node("retrieve", retrieve)
    graph.add_node("respond", respond)
    graph.add_node("booking", booking)

    graph.add_edge(START, "route")
    graph.add_conditional_edges("route", after_route, ["retrieve", "respond", "booking"])
    graph.add_edge("retrieve", "respond")
    graph.add_edge("respond", END)
    graph.add_edge("booking", END)

    return graph.compile(checkpointer=checkpointer)
