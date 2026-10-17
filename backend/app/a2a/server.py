"""Helpers for exposing an agent as an A2A (Agent-to-Agent protocol) service."""

import uuid

from a2a.helpers.proto_helpers import new_data_part, new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import a2a_pb2 as pb
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from starlette.applications import Starlette

from app.security import BearerKeyMiddleware


def agent_card(
    *, name: str, description: str, url: str, skills: list[pb.AgentSkill]
) -> pb.AgentCard:
    """The agent's public "business card": who it is, what it can do, how to call it."""
    return pb.AgentCard(
        name=name,
        description=description,
        version="1.0.0",
        supported_interfaces=[
            pb.AgentInterface(url=f"{url}/", protocol_binding="JSONRPC", protocol_version="1.0")
        ],
        capabilities=pb.AgentCapabilities(streaming=True),
        default_input_modes=["text/plain", "application/json"],
        default_output_modes=["text/plain", "application/json"],
        skills=skills,
        security_schemes={
            "bearer": pb.SecurityScheme(
                http_auth_security_scheme=pb.HTTPAuthSecurityScheme(scheme="bearer")
            )
        },
        security_requirements=[pb.SecurityRequirement(schemes={"bearer": pb.StringList()})],
    )


def create_a2a_app(
    executor: AgentExecutor, card: pb.AgentCard, api_key: str, lifespan=None
) -> Starlette:
    """JSON-RPC A2A endpoint at `/` (bearer-key protected) + public Agent Card."""
    handler = DefaultRequestHandler(
        agent_executor=executor,
        # Task state (e.g. "input-required") lives in memory: fine for one replica.
        # A database-backed TaskStore would be needed to scale out.
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
    app = Starlette(
        routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, rpc_url="/")],
        lifespan=lifespan,
    )
    app.add_middleware(
        BearerKeyMiddleware, key=api_key, public_paths=frozenset({AGENT_CARD_WELL_KNOWN_PATH})
    )
    return app


async def start_task(context: RequestContext, queue: EventQueue) -> tuple[pb.Task, TaskUpdater]:
    """Get the task this message belongs to (creating it for a new conversation turn)."""
    task = context.current_task
    if task is None:
        task = new_task_from_user_message(context.message)
        await queue.enqueue_event(task)
    return task, TaskUpdater(queue, task.id, task.context_id)


class TextStream:
    """Streams text into one artifact. The first chunk must create the artifact
    (append=False); later chunks append to it — the SDK rejects anything else."""

    def __init__(self, updater: TaskUpdater, name: str = "answer"):
        self._updater = updater
        self._name = name
        self._id = str(uuid.uuid4())
        self._started = False
        self.text = ""

    async def write(self, chunk: str) -> None:
        if not chunk:
            return
        await self._updater.add_artifact(
            [new_text_part(chunk)], artifact_id=self._id, name=self._name, append=self._started
        )
        self._started = True
        self.text += chunk


async def emit_data(updater: TaskUpdater, name: str, data: dict | list) -> None:
    """Send structured data (sources, tool calls…) as its own named artifact."""
    await updater.add_artifact([new_data_part(data)], name=name)
