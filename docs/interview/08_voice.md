# 08 — Voice: Speech In, Speech Out

> Phase 4. Customers can talk to the agent: the browser records speech, the backend transcribes
> it, runs the same supervisor + A2A agents, and speaks the answer back — sentence by sentence.

---

## 1. Plain English first

```
🎤 Browser (hold to talk)
   └─ recording (webm/opus) ──WebSocket──► API /voice
                                             1. STT  speech → text      (faster-whisper, local)
                                             2. Supervisor + A2A agents (unchanged from Phase 3)
                                             3. TTS  text → speech      (Kokoro, local) — per sentence
🔊 Browser plays each sentence as it arrives ◄──WebSocket──┘
```

The "brain" didn't change at all. Voice is a new **transport + two converters** around the same
agents — which is exactly how it should be designed.

---

## 2. Key decisions

### Local open-source by default, ElevenLabs by config
| | Local (default) | ElevenLabs |
|---|---|---|
| STT | **faster-whisper** (`base.en`, int8 on CPU) | Scribe API |
| TTS | **Kokoro** (82M-param model, int8 ONNX, ~88 MB) | `eleven_flash_v2_5` (lowest latency) |
| Cost / quotas | free, unlimited | free tier ≈ 10 min of speech/month |
| Privacy | audio never leaves the machine | sent to a third party |
| Quality | very good | best |

Switch with `STT_PROVIDER=elevenlabs` / `TTS_PROVIDER=elevenlabs` + `ELEVENLABS_API_KEY`. Both sides
are behind tiny `STT` / `TTS` protocols (`app/voice/providers.py`), so the voice endpoint never knows
which engine it's using.

> "I made speech engines pluggable: open-source local models by default for cost, privacy and no
> quota limits during development, and ElevenLabs as a config switch when quality matters, e.g. for
> a demo. Same interface, no code changes."

### No PyTorch needed
- faster-whisper runs on **CTranslate2** (optimised C++ inference for transformer models).
- Kokoro runs on **ONNX Runtime**. Both quantised to **int8** → smaller and faster on CPU.
- Total ~250 MB of models (downloaded once by `scripts/download_voice_models.py`, gitignored).

### WebSocket, not SSE
Chat is one request → one streamed response, so SSE fits. Voice is **bidirectional and concurrent**:
the browser sends audio and control messages ("interrupt", "confirm") while the server streams events
and audio back. That needs a WebSocket.

---

## 3. The latency trick: speak sentence by sentence

Measured on the dev laptop (CPU only): Kokoro takes ~2.6 s to synthesise a 5.5-second sentence
(faster than real time), Whisper ~0.7 s to transcribe it.

If we waited for the full answer and synthesised it all, the caller would hear silence for many
seconds. Instead (`VoiceSession.respond` in `app/api/voice.py`):

1. Agent tokens stream in → a `SentenceSplitter` emits each sentence **the moment it's complete**.
2. Sentences go into an `asyncio.Queue`; a separate **speaker task** synthesises and sends them in order.
3. So the LLM keeps generating sentence 2 while TTS works on sentence 1 → a **pipeline**.

The metric that matters is **time to first audio** — when the caller hears something. Every turn
reports `stt_ms`, `first_token_ms`, `first_audio_ms`, `total_ms`, shown on the Voice page.

**Splitter details:** a sentence ends at `. ! ?` followed by whitespace, but not inside numbers
("2.5 hours"); very short fragments ("Sure!") join the next sentence for natural prosody.

**Model warm-up:** loading Whisper + Kokoro takes seconds, so the API loads them **in the background
at startup** (`warm_up_voice()`), including one throwaway synthesis (first inference is slowest). The
API is usable immediately; the first caller doesn't pay the load cost.

---

## 4. Making text speakable
`speakable()` in `app/voice/text.py`:
- strips citation markers (`[1]`, `[1, 2]`) — useful on screen, nonsense when spoken
- strips markdown symbols
- reads currency naturally: `₹6,500` → "6,500 rupees", `INR 1,200` → "1,200 rupees"

The on-screen transcript keeps the full text (minus citation markers).

---

## 5. Human-in-the-loop by voice
The booking confirmation from Phase 2/3 still works — now also by speaking:
- When the agent pauses (`confirm` event), the server **reads the action aloud**:
  *"Book appointment: Men's haircut, Tuesday 20 October, 11:00, Yash Singh. Shall I go ahead?"*
- The next utterance is interpreted by `spoken_decision()`:
  - yes / yeah / sure / go ahead / confirm / **haan** → approve
  - no / cancel / wait / don't / **nahi** → decline
  - **"no" wins** if both appear ("yes… actually no" = no) — the safe default
  - unclear ("the blue one") → *"Please say yes to confirm, or no to cancel"* — nothing is sent to the agent
- Clicking the card works too (`{"type": "confirm"}`).

> "Voice confirmation is deliberately conservative: any negative word wins, and anything ambiguous
> re-prompts instead of guessing — a wrong 'yes' books a real appointment."

---

## 6. Barge-in (interrupting the agent)
Real phone agents must stop talking when the caller speaks. Pressing the mic while the agent is
speaking or thinking:
1. **Browser** stops playback immediately and clears its audio queue.
2. Sends `{"type": "interrupt"}`; the **server cancels the running turn task** (`asyncio` task
   cancellation) — LLM streaming and the TTS speaker task stop; it replies `interrupted`.
3. The new utterance is handled normally.

Any new message also cancels an in-flight turn, so the server never speaks over the caller.

---

## 7. Browser side (`useVoiceSession.ts`, Voice page)
- **Recording:** `getUserMedia` (with echo cancellation + noise suppression) → `MediaRecorder`
  (webm/opus) → one binary WebSocket message per utterance (push-to-talk).
- **Playback:** `AudioContext.decodeAudioData` handles both WAV (Kokoro) and MP3 (ElevenLabs);
  a queue plays chunks **strictly in order**.
- **Autoplay policy:** browsers block audio until a user gesture, so the `AudioContext` is created on
  the first mic press.
- **Framing:** each audio frame is preceded by a JSON `{"type": "audio", "seq", "mime", "text"}`;
  the server sends both under one lock so they can't interleave.
- Status: Connecting → Hold to talk → Listening → Thinking → Speaking; "Type instead" fallback.

---

## 8. A real dependency bug (good story)
faster-whisper 1.2.1 decodes audio with PyAV, passing an argument (`metadata_errors`) that **PyAV 19
removed** → `TypeError` on every transcription. Pinning PyAV 14 failed (no prebuilt wheel; would need
compiling FFmpeg bindings). **Fix:** decode audio ourselves with PyAV 19 — open the container,
resample to 16 kHz mono float32 with `av.AudioResampler` — and pass Whisper a NumPy array. Fewer
moving parts, and it handles every browser format (verified with WAV and WebM/Opus).

---

## 9. Testing (65 tests total; Phase 4 added 17)
| File | Proves |
|---|---|
| `test_voice_units.py` | Sentence splitting (incremental, short fragments, decimals); speakable text; yes/no/unclear decisions incl. "no wins"; real PyAV decode + resample; ElevenLabs STT/TTS requests (path, headers, body) against `httpx.MockTransport` |
| `test_voice_ws.py` | WebSocket end to end with fake STT/TTS + the real supervisor graph with fake agents: question → transcript, delegation, **one audio frame per sentence**, citations stripped, timings; **booking confirmed by saying "yes please"** (decision sent to the same A2A task); unclear answer re-prompts without touching the agent; silence → retry prompt; unknown business → close code 4404 |

Live check: real Whisper transcribed a Kokoro-generated question ("Hi are you open on Sundays?") sent
over the WebSocket, and real Kokoro spoke the reply back (Gemini was rate-limited, so the reply was the
graceful "busy" message — still exercising the full voice path).

---

## 10. Limitations / next steps
1. **Push-to-talk**, not hands-free: no voice-activity detection yet (browser-side VAD, e.g. Silero
   via WebAssembly, would allow automatic turn-taking).
2. STT runs **after** the recording ends (not streaming partial transcripts). Streaming STT
   (Deepgram / ElevenLabs realtime / whisper streaming) would cut latency further.
3. Local TTS on CPU is the slowest stage; a GPU or ElevenLabs flash model reduces first-audio time.
4. English only (`language="en"`, English voice); Whisper and ElevenLabs support Hindi — a natural
   upgrade for Indian businesses.
5. Phone calls (Twilio Media Streams) would be another transport adapter on the same pipeline.

---

## Q&A

**Q: Walk me through a voice turn.**
A: Browser records webm/opus while the button is held and sends it over a WebSocket. The server
decodes it to 16 kHz mono, transcribes with faster-whisper, runs the supervisor graph, splits the
streamed answer into sentences, synthesises each with Kokoro in a pipelined speaker task, and sends
audio frames back, which the browser plays in order.

**Q: How do you reduce voice latency?**
A: Sentence-level streaming TTS pipelined with LLM generation, model warm-up at startup, int8
quantised models, no "thinking" pass on the LLM, short spoken answers by prompt, and measuring time to
first audio per turn. Next: streaming STT and VAD-based turn detection.

**Q: Why a WebSocket for voice but SSE for chat?**
A: Voice is bidirectional and concurrent — audio and control messages from the client while audio
streams back. SSE is one-way.

**Q: Why local models instead of a cloud API?**
A: Free, private, no rate limits during development — and pluggable, so ElevenLabs is one env var
away when quality matters.

**Q: How does confirmation work by voice?**
A: The pending action is read aloud; the reply is classified conservatively — any negative wins,
ambiguity re-prompts — and the decision resumes the same paused graph/A2A task as a button click.

**Q: How does interruption work?**
A: The client stops playback and sends "interrupt"; the server cancels the asyncio task running the
turn, which stops LLM streaming and synthesis.
