"""Voice conversations over a WebSocket: speech in → STT → supervisor → TTS → speech out.

WebSocket rather than SSE because audio flows both ways: the browser sends recordings
(and control messages like "interrupt") while the server streams events and audio back.

Client → server
    <binary>                              one recorded utterance (webm/opus, wav, …)
    {"type": "text", "text": "..."}       typed fallback, handled exactly like speech
    {"type": "confirm", "approved": bool} answer a pending confirmation by clicking
    {"type": "interrupt"}                 barge-in: stop the current reply
Server → client
    {"type": "ready", ...}                session info (+ pending confirmation, if any)
    {"type": "transcript", "text"}        what we heard
    {"type": <chat event>, "data"}        route, delegation, sources, tool_call, token, confirm…
    {"type": "audio", "seq", "mime", "text"} followed by one <binary> audio frame
    {"type": "timing", ...}               stt_ms, first_token_ms, first_audio_ms, total_ms
    {"type": "turn_end"} | {"type": "interrupted"}
"""

import asyncio
import contextlib
import json
import logging
import time
import uuid
from contextlib import contextmanager

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from langgraph.types import Command

from app.conversation import graph_config, pending_confirmation, run_events, turn_input
from app.db.models import Business
from app.db.session import SessionLocal
from app.errors import friendly_error
from app.guardrails import check_message
from app.ratelimit import RateLimiter, chat_limits, client_ip, get_rate_limiter
from app.tracing import Turn, trace_turn
from app.voice.providers import STT, TTS, get_stt, get_tts
from app.voice.text import SentenceSplitter, speakable, spoken_decision

logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice"])

NOT_HEARD = "Sorry, I didn't catch that. Could you say it again?"
# ~5 MB ≈ several minutes of webm/opus — far beyond one spoken turn.
MAX_AUDIO_BYTES = 5 * 1024 * 1024
ASK_AGAIN = "Please say yes to confirm, or no to cancel."


def confirmation_prompt(confirmation: dict) -> str:
    """Read the pending action aloud, e.g. "Book appointment: Men's haircut, Tuesday…"."""
    parts = []
    for action in confirmation.get("actions", []):
        details = ", ".join(str(v) for v in action.get("details", {}).values() if v)
        parts.append(f"{action.get('title', 'Action')}: {details}.")
    return " ".join(parts) + " Shall I go ahead?"


class VoiceSession:
    def __init__(
        self,
        ws: WebSocket,
        graph,
        business: Business,
        thread_id: str,
        stt: STT,
        tts: TTS,
        limiter: RateLimiter,
    ):
        self.ws, self.graph, self.business = ws, graph, business
        self.thread_id, self.stt, self.tts = thread_id, stt, tts
        self.limiter = limiter
        self._turn = Turn()  # the current turn's trace (no-op outside a turn / without keys)
        self.config = graph_config(business.id, thread_id)
        self._send_lock = asyncio.Lock()
        self._seq = 0

    async def send(self, message: dict) -> None:
        async with self._send_lock:
            await self.ws.send_json(message)

    async def speak(self, text: str) -> float | None:
        """Synthesize one sentence and send it; returns when the audio was sent."""
        text = speakable(text)
        if not text:
            return None
        with self._turn.step("text-to-speech", input={"text": text, "engine": self.tts.name}):
            speech = await self.tts.synthesize(text)
        self._seq += 1
        # Metadata and its binary frame are sent under one lock so they can't interleave.
        async with self._send_lock:
            await self.ws.send_json(
                {"type": "audio", "seq": self._seq, "mime": speech.mime, "text": text}
            )
            await self.ws.send_bytes(speech.audio)
        return time.perf_counter()

    @contextmanager
    def _trace(self, *tags: str):
        """One trace per voice turn: STT, the agents' work and every TTS sentence nest in it."""
        with trace_turn(
            "voice-turn",
            session_id=self.config["configurable"]["thread_id"],
            user_id=str(self.business.id),
            tags=["voice", *tags],
        ) as turn:
            self._turn = turn
            try:
                yield turn
            finally:
                self._turn = Turn()

    async def handle_turn(self, *, audio: bytes | None = None, text: str | None = None) -> None:
        with self._trace() as turn:
            await self._handle(turn, audio=audio, text=text)

    async def _handle(self, turn: Turn, *, audio: bytes | None, text: str | None) -> None:
        started = time.perf_counter()
        timing: dict[str, float] = {}
        if turn.trace_url:
            await self.send({"type": "trace", "url": turn.trace_url})

        try:
            await self.limiter.enforce(*chat_limits(client_ip(self.ws), str(self.business.id)))
        except HTTPException as exc:
            await self.send({"type": "error", "data": {"message": exc.detail}})
            await self.speak(exc.detail)
            await self.send({"type": "turn_end"})
            return
        if audio is not None and len(audio) > MAX_AUDIO_BYTES:
            await self.speak("That was a bit long — could you say it more briefly?")
            await self.send({"type": "turn_end"})
            return

        if audio is not None:
            with turn.step(
                "speech-to-text", input={"bytes": len(audio), "engine": self.stt.name}
            ) as step:
                text = await self.stt.transcribe(audio)
                if step is not None:
                    step.update(output=text)
            timing["stt_ms"] = (time.perf_counter() - started) * 1000
        text = (text or "").strip()
        turn.input(text)
        await self.send({"type": "transcript", "text": text})
        if not text:
            await self.speak(NOT_HEARD)
            await self.send({"type": "turn_end"})
            return

        verdict = check_message(text, self.business.name)
        if not verdict.allowed:
            await self.send({"type": "guardrail", "data": {"reason": verdict.reason}})
            await self.speak(verdict.reply)
            await self.send({"type": "turn_end"})
            return

        if await pending_confirmation(self.graph, self.config):
            # The agent asked "shall I book this?" — this utterance is the answer.
            decision = spoken_decision(text)
            if decision is None:
                await self.speak(ASK_AGAIN)
                await self.send({"type": "turn_end"})
                return
            await self.send({"type": "decision", "approved": decision})
            graph_input = Command(resume={"approved": decision})
        else:
            graph_input = turn_input(self.business, text)

        await self.respond(graph_input, started, timing, turn)

    async def answer(self, approved: bool) -> None:
        """Clicked Confirm/Decline on the card — same effect as saying yes/no."""
        if not await pending_confirmation(self.graph, self.config):
            return
        with self._trace("confirm") as turn:
            turn.input({"confirmation": "approved" if approved else "declined"})
            await self.send({"type": "decision", "approved": approved})
            await self.respond(
                Command(resume={"approved": approved}), time.perf_counter(), {}, turn
            )

    async def respond(
        self, graph_input, started: float, timing: dict[str, float], turn: Turn
    ) -> None:
        """Stream the agent's reply; speak each sentence as soon as it's complete.
        A queue decouples the two: the LLM keeps generating while TTS works on the
        previous sentence, so speech starts long before the answer is finished."""
        sentences: asyncio.Queue[str | None] = asyncio.Queue()

        async def speaker() -> None:
            while (sentence := await sentences.get()) is not None:
                sent_at = await self.speak(sentence)
                if sent_at and "first_audio_ms" not in timing:
                    timing["first_audio_ms"] = (sent_at - started) * 1000

        # Created inside the turn's trace context, so its TTS spans nest under the turn.
        speaker_task = asyncio.create_task(speaker())
        splitter = SentenceSplitter()
        reply: list[str] = []
        try:
            async for event, data in run_events(
                self.graph, graph_input, turn.callbacks(self.config), self.thread_id
            ):
                await self.send({"type": event, "data": data})
                if event == "token":
                    reply.append(data["text"])
                    timing.setdefault("first_token_ms", (time.perf_counter() - started) * 1000)
                    for sentence in splitter.feed(data["text"]):
                        await sentences.put(sentence)
                elif event == "confirm":
                    for sentence in splitter.flush():
                        await sentences.put(sentence)
                    await sentences.put(confirmation_prompt(data))
                elif event == "error":
                    await sentences.put(data["message"])
            for sentence in splitter.flush():
                await sentences.put(sentence)
        finally:
            await sentences.put(None)
            # On interrupt this task is cancelled; stop speaking right away too.
            if asyncio.current_task().cancelling():
                speaker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await speaker_task

        timing["total_ms"] = (time.perf_counter() - started) * 1000
        turn.output("".join(reply))
        await self.send({"type": "timing", **{k: round(v) for k, v in timing.items()}})
        await self.send({"type": "turn_end"})


@router.websocket("/voice/{business_id}")
async def voice(
    ws: WebSocket,
    business_id: uuid.UUID,
    thread_id: str | None = None,
    stt: STT = Depends(get_stt),  # noqa: B008 — FastAPI's standard WebSocket dependency style
    tts: TTS = Depends(get_tts),  # noqa: B008
    limiter: RateLimiter = Depends(get_rate_limiter),  # noqa: B008
):
    await ws.accept()
    async with SessionLocal() as session:
        business = await session.get(Business, business_id)
    if business is None:
        await ws.close(code=4404, reason="Business not found")
        return

    session = VoiceSession(
        ws, ws.app.state.graph, business, thread_id or str(uuid.uuid4()), stt, tts, limiter
    )
    await session.send(
        {
            "type": "ready",
            "thread_id": session.thread_id,
            "stt": stt.name,
            "tts": tts.name,
            "pending_confirmation": await pending_confirmation(session.graph, session.config),
        }
    )

    current: asyncio.Task | None = None

    async def run(turn) -> None:
        try:
            await turn
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Voice turn failed")
            await session.send({"type": "error", "data": {"message": friendly_error(exc)}})
            await session.send({"type": "turn_end"})

    try:
        while True:
            message = await ws.receive()
            if message["type"] == "websocket.disconnect":
                break
            if current and not current.done():
                # A new utterance or an explicit interrupt both cut off the current reply.
                current.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await current
                await session.send({"type": "interrupted"})

            if message.get("bytes") is not None:
                current = asyncio.create_task(run(session.handle_turn(audio=message["bytes"])))
                continue

            data = json.loads(message.get("text") or "{}")
            if data.get("type") == "text":
                current = asyncio.create_task(run(session.handle_turn(text=data.get("text", ""))))
            elif data.get("type") == "confirm":
                current = asyncio.create_task(run(session.answer(bool(data.get("approved")))))
            # {"type": "interrupt"} needs nothing more: the reply was cancelled above.
    except WebSocketDisconnect:
        pass
    finally:
        if current and not current.done():
            current.cancel()
