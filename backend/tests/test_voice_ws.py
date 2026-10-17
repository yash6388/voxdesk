"""The /voice WebSocket end to end, with fake speech engines and fake A2A agents
(no microphone, no models, no network)."""

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from starlette.websockets import WebSocketDisconnect

from app.a2a.client import AgentEvent
from app.api import voice
from app.graph.state import Route
from app.graph.supervisor import build_supervisor
from app.voice.providers import Speech, get_stt, get_tts
from tests.fakes import FakeAgent, FakeRouter, answer, replies

BUSINESS = SimpleNamespace(
    id=uuid.uuid4(), name="Glow Studio", description="", timezone="Asia/Kolkata"
)


class FakeSTT:
    name = "fake-stt"

    def __init__(self, *transcripts: str):
        self._transcripts = list(transcripts)

    async def transcribe(self, audio: bytes) -> str:
        return self._transcripts.pop(0)


class FakeTTS:
    name = "fake-tts"

    def __init__(self):
        self.spoken: list[str] = []

    async def synthesize(self, text: str) -> Speech:
        self.spoken.append(text)
        return Speech(b"AUDIO", "audio/wav")


class FakeSessionLocal:
    """The endpoint only needs to look up the business."""

    async def __aenter__(self):
        return SimpleNamespace(get=self._get)

    async def __aexit__(self, *exc):
        return False

    async def _get(self, model, business_id):
        return BUSINESS if business_id == BUSINESS.id else None


def make_client(monkeypatch, stt, tts, *, routes, knowledge=None, booking=None) -> TestClient:
    monkeypatch.setattr(voice, "SessionLocal", FakeSessionLocal)
    app = FastAPI()
    app.include_router(voice.router)
    app.state.graph = build_supervisor(
        router_llm=FakeRouter(*routes),
        chat_llm=replies("Hello!"),
        knowledge_agent=knowledge or FakeAgent("knowledge"),
        booking_agent=booking or FakeAgent("booking"),
        checkpointer=InMemorySaver(),
    )
    app.dependency_overrides[get_stt] = lambda: stt
    app.dependency_overrides[get_tts] = lambda: tts
    return TestClient(app)


def turn(ws) -> list[dict]:
    """Collect messages until the turn ends; audio frames are recorded as {"type": "<audio>"}."""
    messages = []
    while True:
        frame = ws.receive()
        if frame.get("bytes") is not None:
            messages.append({"type": "<audio>", "bytes": frame["bytes"]})
            continue
        message = json.loads(frame["text"])
        messages.append(message)
        if message["type"] in ("turn_end", "interrupted"):
            return messages


def types(messages: list[dict]) -> list[str]:
    return [m["type"] for m in messages]


def test_spoken_question_is_answered_with_streamed_speech(monkeypatch):
    stt, tts = FakeSTT("Is there parking?"), FakeTTS()
    knowledge = FakeAgent("knowledge", answer("Yes, free parking [1]. ", "Six cars fit. "))
    client = make_client(
        monkeypatch,
        stt,
        tts,
        routes=[Route(intent="knowledge", search_query="parking")],
        knowledge=knowledge,
    )

    with client.websocket_connect(f"/voice/{BUSINESS.id}") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["stt"] == "fake-stt"
        ws.send_bytes(b"recorded-webm")
        messages = turn(ws)

    assert messages[0] == {"type": "transcript", "text": "Is there parking?"}
    assert "delegation" in types(messages)
    # Each sentence was spoken separately, citations stripped, audio frame after its metadata.
    assert tts.spoken == ["Yes, free parking.", "Six cars fit."]
    audio_meta = [m for m in messages if m["type"] == "audio"]
    assert [m["seq"] for m in audio_meta] == [1, 2]
    assert types(messages).count("<audio>") == 2
    timing = next(m for m in messages if m["type"] == "timing")
    assert {"stt_ms", "first_token_ms", "first_audio_ms", "total_ms"} <= timing.keys()
    assert messages[-1]["type"] == "turn_end"


def test_booking_is_confirmed_by_saying_yes(monkeypatch):
    actions = [
        {"title": "Book appointment", "details": {"Service": "Men's haircut", "Time": "11:00"}}
    ]
    booking = FakeAgent(
        "booking",
        [
            AgentEvent("task", task_id="task-1"),
            AgentEvent("input_required", task_id="task-1", data={"actions": actions}),
        ],
        answer("You're booked! ", task_id="task-1"),
    )
    stt, tts = FakeSTT("Book a men's haircut at 11, I'm Yash, 9876543210", "yes please"), FakeTTS()
    client = make_client(
        monkeypatch, stt, tts, routes=[Route(intent="booking", search_query="")], booking=booking
    )

    with client.websocket_connect(f"/voice/{BUSINESS.id}") as ws:
        ws.receive_json()
        ws.send_bytes(b"utterance-1")
        first = turn(ws)
        ws.send_bytes(b"utterance-2")
        second = turn(ws)

    confirm = next(m for m in first if m["type"] == "confirm")
    assert confirm["data"] == {"actions": actions}
    assert tts.spoken[0] == "Book appointment: Men's haircut, 11:00. Shall I go ahead?"

    assert {"type": "decision", "approved": True} in second
    assert booking.requests[1]["data"] == {"approved": True}
    assert booking.requests[1]["task_id"] == "task-1"
    assert tts.spoken[-1] == "You're booked!"


def test_unclear_answer_to_confirmation_asks_again(monkeypatch):
    booking = FakeAgent(
        "booking",
        [
            AgentEvent("task", task_id="t"),
            AgentEvent("input_required", task_id="t", data={"actions": []}),
        ],
    )
    stt, tts = FakeSTT("book me in", "the blue one"), FakeTTS()
    client = make_client(
        monkeypatch, stt, tts, routes=[Route(intent="booking", search_query="")], booking=booking
    )

    with client.websocket_connect(f"/voice/{BUSINESS.id}") as ws:
        ws.receive_json()
        ws.send_bytes(b"1")
        turn(ws)
        ws.send_bytes(b"2")
        second = turn(ws)

    assert tts.spoken[-1] == voice.ASK_AGAIN
    assert len(booking.requests) == 1, "nothing may be sent to the agent on an unclear answer"
    assert "decision" not in types(second)


def test_silence_gets_a_friendly_retry_prompt(monkeypatch):
    stt, tts = FakeSTT(""), FakeTTS()
    client = make_client(monkeypatch, stt, tts, routes=[])

    with client.websocket_connect(f"/voice/{BUSINESS.id}") as ws:
        ws.receive_json()
        ws.send_bytes(b"silence")
        messages = turn(ws)

    assert messages[0] == {"type": "transcript", "text": ""}
    assert tts.spoken == [voice.NOT_HEARD]


def test_unknown_business_closes_the_socket(monkeypatch):
    client = make_client(monkeypatch, FakeSTT(), FakeTTS(), routes=[])
    with (
        pytest.raises(WebSocketDisconnect) as closed,
        client.websocket_connect(f"/voice/{uuid.uuid4()}") as ws,
    ):
        ws.receive_json()
    assert closed.value.code == 4404
