"""The supervisor's side of A2A: discover a remote agent from its Agent Card,
send it a message, and turn its streamed task updates into simple events."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
from a2a.client import A2ACardResolver, Client, ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import (
    get_data_parts,
    get_message_text,
    get_text_parts,
    new_data_part,
    new_message,
    new_text_part,
)
from a2a.types import a2a_pb2 as pb


@dataclass
class AgentEvent:
    kind: Literal["task", "token", "data", "input_required", "completed", "failed"]
    task_id: str = ""
    text: str = ""
    name: str = ""  # artifact name for "data" events, e.g. "sources" or "tool_call"
    data: Any = field(default=None)


class RemoteAgent(Protocol):
    """Anything the supervisor can delegate to. Tests use in-process fakes."""

    name: str

    def stream(
        self,
        *,
        context_id: str,
        metadata: dict,
        text: str | None = None,
        data: dict | None = None,
        task_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]: ...


class A2AAgent:
    """A remote agent reached over A2A (JSON-RPC over HTTP, streaming)."""

    def __init__(
        self, name: str, base_url: str, api_key: str, http: httpx.AsyncClient | None = None
    ):
        self.name = name
        self._base_url = base_url
        self._http = http or httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"}, timeout=httpx.Timeout(60, read=120)
        )
        self._client: Client | None = None
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def card(self) -> pb.AgentCard:
        return await A2ACardResolver(self._http, self._base_url).get_agent_card()

    async def _get_client(self) -> Client:
        # Discover the agent once (reads /.well-known/agent-card.json), then reuse the client.
        async with self._lock:
            if self._client is None:
                factory = ClientFactory(ClientConfig(streaming=True, httpx_client=self._http))
                self._client = factory.create(await self.card())
            return self._client

    async def stream(
        self,
        *,
        context_id: str,
        metadata: dict,
        text: str | None = None,
        data: dict | None = None,
        task_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        parts = [new_text_part(text)] if text else []
        if data is not None:
            parts.append(new_data_part(data))
        message = new_message(parts, context_id=context_id, task_id=task_id, role=pb.ROLE_USER)
        request = pb.SendMessageRequest(message=message, metadata=metadata)

        client = await self._get_client()
        async for response in client.send_message(request):
            for event in _to_events(response):
                yield event


def _to_events(r: pb.StreamResponse) -> list[AgentEvent]:
    if r.HasField("task"):
        return [AgentEvent("task", task_id=r.task.id)]
    if r.HasField("artifact_update"):
        update = r.artifact_update
        artifact = update.artifact
        texts = get_text_parts(artifact.parts)
        datas = get_data_parts(artifact.parts)
        events = [AgentEvent("token", task_id=update.task_id, text=t) for t in texts if t]
        events += [
            AgentEvent("data", task_id=update.task_id, name=artifact.name, data=d) for d in datas
        ]
        return events
    if r.HasField("status_update"):
        update = r.status_update
        state, message = update.status.state, update.status.message
        if state == pb.TASK_STATE_INPUT_REQUIRED:
            datas = get_data_parts(message.parts)
            return [
                AgentEvent("input_required", task_id=update.task_id, data=datas[0] if datas else {})
            ]
        if state == pb.TASK_STATE_COMPLETED:
            return [AgentEvent("completed", task_id=update.task_id, text=get_message_text(message))]
        if state in (pb.TASK_STATE_FAILED, pb.TASK_STATE_REJECTED, pb.TASK_STATE_CANCELED):
            return [AgentEvent("failed", task_id=update.task_id, text=get_message_text(message))]
    if r.HasField("message"):
        return [AgentEvent("completed", text=get_message_text(r.message))]
    return []
