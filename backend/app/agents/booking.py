"""Booking Agent — an independent A2A service that books, reschedules and cancels
appointments using the VoxDesk MCP server's tools.

    uv run python -m app.agents.booking        # http://127.0.0.1:8102

Human-in-the-loop maps onto A2A natively: when the booking graph pauses for confirmation,
the task goes to INPUT_REQUIRED with the actions as data. The caller replies on the SAME
task with {"approved": true|false} and the graph resumes where it paused.

The agent keeps its own conversation memory (LangGraph checkpoint), keyed by the A2A
context id, so a booking can span several messages.
"""

import logging
from contextlib import asynccontextmanager

import uvicorn
from a2a.helpers.proto_helpers import get_data_parts, new_data_part, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import a2a_pb2 as pb
from langgraph.types import Command

from app.a2a.server import TextStream, agent_card, create_a2a_app, emit_data, start_task
from app.config import get_settings
from app.errors import friendly_error
from app.tracing import Turn, trace_turn

logger = logging.getLogger(__name__)


class BookingAgentExecutor(AgentExecutor):
    def __init__(self, graph=None):
        # Set at startup (needs the DB pool) or injected directly in tests.
        self.graph = graph

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task, updater = await start_task(context, event_queue)
        meta = context.metadata or {}
        if not meta.get("business_id"):
            await updater.reject(
                updater.new_agent_message([new_text_part("business_id is required.")])
            )
            return

        config = {"configurable": {"thread_id": f"booking:{context.context_id}"}}
        data = get_data_parts(context.message.parts)
        if task.status.state == pb.TASK_STATE_INPUT_REQUIRED and data and "approved" in data[0]:
            # The customer answered our confirmation: continue the paused graph.
            graph_input = Command(resume={"approved": bool(data[0]["approved"])})
        else:
            graph_input = {
                "messages": [("user", context.get_user_input())],
                "business_id": meta["business_id"],
                "business_name": meta.get("business_name", ""),
                "business_timezone": meta.get("business_timezone", "UTC"),
            }

        with trace_turn(
            "booking-agent",
            session_id=context.context_id,
            user_id=meta["business_id"],
            tags=["a2a", "booking"],
            input=context.get_user_input() or data,
            parent=meta,  # continue the supervisor's trace
        ) as turn:
            await self._run(graph_input, turn.callbacks(config), updater, turn)

    async def _run(self, graph_input, config: dict, updater, turn: Turn) -> None:
        try:
            await updater.start_work()
            answer = TextStream(updater)
            pending = None
            async for mode, payload in self.graph.astream(
                graph_input, config, stream_mode=["messages", "updates"]
            ):
                if mode == "messages":
                    chunk, metadata = payload
                    if metadata.get("langgraph_node") == "booking_agent":
                        await answer.write(chunk.text)
                    continue
                for node, update in payload.items():
                    if node == "__interrupt__":
                        pending = update[0].value
                    elif node == "booking_agent" and update:
                        for call in getattr(update["messages"][-1], "tool_calls", None) or []:
                            await emit_data(
                                updater, "tool_call", {"name": call["name"], "args": call["args"]}
                            )
                    elif node == "tools" and update:
                        for m in update["messages"]:
                            await emit_data(
                                updater,
                                "tool_result",
                                {"name": m.name, "status": m.status, "content": m.text[:500]},
                            )

            if pending:
                await updater.requires_input(updater.new_agent_message([new_data_part(pending)]))
            else:
                turn.output(answer.text)
                await updater.complete(updater.new_agent_message([new_text_part(answer.text)]))
        except Exception as exc:
            logger.exception("Booking agent failed")
            await updater.failed(updater.new_agent_message([new_text_part(friendly_error(exc))]))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError("Cancel a booking by asking the agent instead.")


def booking_card(url: str) -> pb.AgentCard:
    return agent_card(
        name="VoxDesk Booking Agent",
        description=(
            "Books, reschedules and cancels appointments for a business, "
            "with customer confirmation."
        ),
        url=url,
        skills=[
            pb.AgentSkill(
                id="manage_appointments",
                name="Manage appointments",
                description=(
                    "Checks real availability and books, finds, reschedules or cancels "
                    "appointments via the VoxDesk MCP server. Before any change it returns "
                    "INPUT_REQUIRED with the action details; reply on the same task with "
                    'data {"approved": true|false}. '
                    "Requires metadata: business_id, business_name, business_timezone."
                ),
                tags=["booking", "appointments", "calendar", "mcp"],
                examples=["Book a men's haircut tomorrow at 4pm", "Cancel my booking"],
            )
        ],
    )


def create_app(executor: BookingAgentExecutor | None = None):
    s = get_settings()

    @asynccontextmanager
    async def lifespan(app):
        if executor.graph is None:
            from app.db.session import SessionLocal
            from app.graph.booking_graph import build_booking_graph
            from app.graph.checkpoint import postgres_checkpointer
            from app.graph.tools import MCPToolProvider
            from app.llm import chat_llm

            async with postgres_checkpointer() as checkpointer:
                executor.graph = build_booking_graph(
                    chat_llm=chat_llm(),
                    tool_provider=MCPToolProvider(s.mcp_url, s.mcp_api_key),
                    session_factory=SessionLocal,
                    checkpointer=checkpointer,
                )
                yield
        else:
            yield

    executor = executor or BookingAgentExecutor()
    return create_a2a_app(
        executor, booking_card(s.booking_agent_url), s.a2a_api_key, lifespan=lifespan
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    s = get_settings()
    uvicorn.run(create_app(), host=s.agents_host, port=s.booking_agent_port)
