"""Test doubles for LLMs, MCP tools and remote A2A agents."""

import json

from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.outputs import ChatGenerationChunk
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_core.tools import tool

from app.a2a.client import AgentEvent
from app.graph.state import Route


class FakeRouter:
    """Stands in for the router LLM: returns pre-scripted routing decisions."""

    def __init__(self, *routes: Route):
        self._routes = iter(routes)

    def with_structured_output(self, schema):
        return RunnableLambda(lambda _: next(self._routes))


class FakeToolLLM(GenericFakeChatModel):
    """Scripted chat model that also accepts bind_tools (the real one sends tool schemas)
    and streams tool calls — the base fake streams nothing for a tool-call-only message."""

    def bind_tools(self, tools, **kwargs) -> Runnable:
        return self

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        message = next(self.messages)
        chunk = AIMessageChunk(
            content=message.content,
            tool_call_chunks=[
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(message.tool_calls)
            ],
        )
        if run_manager and chunk.content:
            run_manager.on_llm_new_token(chunk.content, chunk=ChatGenerationChunk(message=chunk))
        yield ChatGenerationChunk(message=chunk)


def scripted(*replies: AIMessage) -> FakeToolLLM:
    return FakeToolLLM(messages=iter(replies))


def replies(text: str) -> GenericFakeChatModel:
    # A fresh message per reply: LangGraph de-duplicates messages by id.
    return GenericFakeChatModel(messages=(AIMessage(text) for _ in range(100)))


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


class FakeAgent:
    """A scripted remote agent. Each call to stream() plays the next script and records
    the request, so tests can assert exactly what the supervisor sent over A2A."""

    def __init__(self, name: str, *scripts: list[AgentEvent] | Exception):
        self.name = name
        self._scripts = list(scripts)
        self.requests: list[dict] = []

    async def stream(self, **request):
        self.requests.append(request)
        script = self._scripts.pop(0)
        if isinstance(script, Exception):
            raise script
        for event in script:
            yield event


def answer(*tokens: str, task_id: str = "t-1") -> list[AgentEvent]:
    return [
        AgentEvent("task", task_id=task_id),
        *[AgentEvent("token", task_id=task_id, text=t) for t in tokens],
        AgentEvent("completed", task_id=task_id),
    ]
