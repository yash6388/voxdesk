# VoxDesk — How to Pitch It

> How to present VoxDesk in an interview: 30-second, 2-minute and 5-minute versions, a whiteboard
> diagram you can draw in 60 seconds, a demo script, and how to steer follow-up questions toward your
> strongest material. Facts and numbers come from `PROJECT_EXPLAINED.md` — never claim more than that.

---

## 0. Rules of a good project pitch

1. **Problem → what it does → how → proof → what you learned.** Not a list of technologies.
2. **Lead with the user, then the engineering.** "A salon misses calls" before "LangGraph".
3. **One number per claim.** "Hybrid retrieval: 86% Hit@1 vs 82% vector-only" beats "it's accurate".
4. **Say the trade-off before they ask.** It shows judgment, not just building.
5. **Stop and let them pick the thread.** End each version with a hook, not a monologue.

---

## 1. The 30-second version (intro / "tell me about a project")

> "I built **VoxDesk**, a multi-agent voice AI platform for small businesses like salons and clinics.
> The business uploads its documents and services, and customers can talk to an agent by voice or
> chat — it answers from the business's own documents with citations, books appointments against
> real availability after the customer confirms, and hands off to staff when needed.
>
> Under the hood a **LangGraph supervisor** delegates over the **A2A protocol** to a knowledge agent
> doing **hybrid RAG on pgvector** and a booking agent whose tools come from **my own MCP server**.
> I built an evaluation suite for it — for example it's how I chose the chunk size — plus failover
> between LLM providers, tracing, auth and multi-tenancy."

Hook to end on: *"Happy to go into the agent design, the voice latency, or how I evaluated it."*

---

## 2. The 2-minute version (the default)

**Problem (15 s).** "Small businesses lose customers on the phone — they're busy, closed, or the
same questions repeat all day: prices, hours, 'can I book Tuesday?'. I wanted an agent a business can
set up in minutes from its own documents, that customers can talk to by voice."

**What it does (25 s).** "Owners upload PDFs or FAQs and set services and hours. Customers reach the
agent on a public page, a QR code, or a one-line chat widget on the business's website. It answers
with citations and says 'I don't know' instead of guessing; it books, reschedules and cancels, always
asking for confirmation before it changes anything; and if someone wants a person, the conversation
lands in the owner's Inbox. Owners also get analytics and a Playground that shows how every reply
was produced."

**How (45 s).** "It's a supervisor pattern. A LangGraph graph routes each message with a cheap model
using structured output — intent plus a rewritten standalone query. Questions go over **A2A** to a
knowledge agent: **hybrid search**, pgvector plus Postgres full-text, fused with reciprocal rank
fusion. Bookings go to a booking agent whose tools come from an **MCP server** I wrote. Before any
write, the graph pauses — that pause travels over A2A as an `input-required` task state, so the
customer sees a confirmation card or just says 'yes' in voice. The database has an exclusion
constraint, so double booking is impossible even under concurrency. Voice is speech-to-text, the same
graph, then text-to-speech **sentence by sentence**, so the customer hears the first sentence while
the rest is still being generated."

**Proof (20 s).** "I built an eval suite with a golden set: hybrid retrieval gets 86% Hit@1 and 100%
Hit@3, routing 100%, an LLM judge scores faithfulness 5 out of 5, and it refuses unanswerable
questions every time. The evals actually changed production: halving the chunk size improved Hit@1
from 82 to 86%. 130 automated tests run in CI."

**Learned (15 s).** "The biggest lesson: enforce rules in code, not prompts. The LLM sometimes
invented a customer name, and once kept re-routing a customer's phone number as a handoff — prompt
fixes didn't hold, small deterministic checks did."

---

## 3. The 5-minute version (when they say "walk me through it")

Draw the diagram (§4) while you talk. Spend one minute on each:

1. **Product + users** — owner and customer journeys (2-minute version, first two parts).
2. **Agent architecture** — supervisor graph: `route → knowledge | booking | handoff | small talk`.
   Why an explicit graph instead of one big agent: predictable, testable, checkpoints give memory
   and pause/resume for free. Why separate A2A services: independent scaling and deployment, failure
   isolation (if booking is down, questions still work), least privilege (only the booking agent
   holds the MCP key).
3. **RAG** — 500-character chunks, 768-d Gemini embeddings, HNSW + GIN indexes, RRF with k = 60,
   tenant filter on every query. The eval numbers. Query rewriting for follow-ups.
4. **Booking safety** — tenant comes from the MCP connection, not a tool argument (the LLM can't
   choose another business); human confirmation for writes only; code checks the customer details
   are real; exclusion constraint for races.
5. **Production** — Gemini with automatic failover to Groq behind a circuit breaker (failover went
   from 2.3 s to 0.5 s); Redis rate limits and prompt-injection guardrails before any LLM spend;
   JWT in httpOnly cookies, other tenants get 404; Langfuse traces that follow a turn across services;
   analytics and handoff; Docker images and CI.

Close with limitations + next steps (§7).

---

## 4. The whiteboard (draw in ~60 seconds)

```
   [Customer: voice / chat / widget]          [Owner dashboard]
          │ WebSocket / SSE                         │ REST
          ▼                                         ▼
   ┌─────────────── API ──────────────────────────────┐
   │ guardrails · rate limit · STT/TTS                 │
   │ Supervisor (LangGraph) — memory in Postgres       │
   │   route ─► knowledge │ booking │ handoff │ chat   │
   └──────────┬──────────────────┬────────────────────┘
          A2A │              A2A │
              ▼                  ▼
     [Knowledge agent]     [Booking agent] ── MCP ──► [MCP server: booking tools]
      hybrid RAG                                         │
              │                                          │
              └──────────► [Postgres + pgvector] ◄───────┘      [Redis] [Langfuse]
```

Draw order: customer → API → supervisor → two agents → MCP → database. Then add Redis/Langfuse
while talking about production. Point at each arrow and name the protocol.

---

## 5. Live demo script (3 minutes)

Prepare: all services running, demo salon seeded, Playground open with the Inspector visible,
a second tab on the Voice page, a third on the customer page `/c/<slug>`.

1. **Question + citations** — *"How much is a keratin treatment?"* → point at the citation chip and
   the Inspector: route = Knowledge, rewritten query, sources, time to first token.
2. **Follow-up** — *"And how long does it take?"* → Inspector shows the rewritten standalone query.
3. **Unknown** — *"Do you do tattoos?"* → it refuses and offers staff (no hallucination).
4. **Booking** — *"Book a men's haircut tomorrow afternoon"* → it lists times, asks name and phone →
   confirmation card → confirm → open the **Bookings** page: it's there.
5. **Voice** — Voice tab: hold the button, ask about opening hours → it speaks sentence by sentence;
   interrupt it mid-sentence; show the latency panel.
6. **Handoff** — *"I'd like to talk to the manager"* → Inbox badge appears → open the transcript.
7. **Analytics + trace** — Analytics page, then "Open trace in Langfuse" from the Inspector to show
   one trace spanning the API and an agent.

If something fails live: show the health indicator and say what's down — graceful degradation is
part of the design ("booking is down, questions still work").

---

## 6. Steering follow-ups (they'll ask; here's where to take it)

| They ask | Your strongest short answer | Then offer |
|---|---|---|
| "Why multi-agent? Isn't that over-engineered?" | "For one business, a single agent would work. I split it for isolation, independent scaling and least privilege — and to practise A2A. The cost is an extra network hop and more moving parts — small next to LLM latency, which dominates every turn." | Failure isolation demo |
| "MCP vs A2A?" | "MCP connects an agent to **tools**; A2A connects agents to **other agents** — with tasks, states, streaming and pause-for-input. My booking agent uses both: A2A to talk to the supervisor, MCP for tools." | HITL over A2A |
| "How do you stop hallucinations?" | "Retrieval-grounded prompts with citations, refusal when context is missing — 100% correct refusals in evals — and an LLM judge for faithfulness." | Eval suite |
| "How did you evaluate it?" | "Golden set; retrieval Hit@k/MRR across vector/keyword/hybrid and chunk sizes; routing accuracy; fact checks + LLM-as-judge; booking task success with fake tools so nothing is booked." | Chunk-size story |
| "What about prompt injection?" | "Input guardrails before any LLM, and more importantly the LLM can't choose the tenant or skip confirmation — those are enforced in code and in the database." | Tenant header design |
| "Latency?" | "Text: tokens stream as they're generated; in the evals a grounded answer's median was ~0.7 s. Voice: sentence-level TTS pipelining so time-to-first-audio ≈ first sentence. Next step is streaming STT and voice-activity detection." | Voice metrics |
| "What would you change?" | "Phone calls via a telephony adapter, streaming STT, per-staff calendars, notifications on handoff, a reranker experiment, bigger golden set." | Roadmap |
| "What was hardest?" | "Human-in-the-loop across two agents in different processes: the booking agent pauses, the A2A task goes input-required, the supervisor pauses its own graph, and the decision resumes the same remote task." | Sequence diagram |
| "Did you use AI tools?" | "Yes, heavily — but I own the decisions: I read the SDKs, verified with tests and live runs, and measured before claiming. Several bugs in these notes are ones I caught in review or live testing." | Bug stories |

---

## 7. Limitations and next steps (say it confidently)

> "It's not deployed yet — it's deploy-ready with Docker images, health checks and production safety
> checks. Voice is push-to-talk; I'd add voice-activity detection and streaming speech-to-text, then
> a telephony adapter for real phone calls. Handoff flags the conversation, but there's no live
> takeover or notification yet. The golden set is about fifty cases — enough to make decisions like
> chunk size, not a benchmark."

---

## 8. Phrases worth memorising

- "The tenant comes from the connection, not from the model."
- "Confirmation for writes only — safety without confirmation fatigue."
- "Only the database can prevent a race; so the database does."
- "Enforce invariants in code; prompts are suggestions."
- "I changed production because the eval said so: 82 → 86% Hit@1."
- "Time to first audio is the metric callers feel."
- "Evals measure what you thought of; live testing finds the rest."

---

## 9. Resume bullets (pick 3–4)

- Built **VoxDesk**, a multi-agent voice AI platform for businesses: **LangGraph** supervisor
  delegating over **A2A** to knowledge and booking agents; booking tools served by a custom
  **MCP** server; FastAPI + Next.js.
- Implemented **hybrid RAG** (pgvector HNSW + Postgres full-text, RRF) with an evaluation suite
  (Hit@k, MRR, LLM-as-judge); chose chunk size from evals — **Hit@1 86%, Hit@3 100%, faithfulness 5/5**.
- Built a streaming **voice pipeline** (faster-whisper → agent → Kokoro/ElevenLabs over WebSocket)
  with sentence-level TTS pipelining, spoken confirmations and barge-in.
- Made it production-ready: **human-in-the-loop** confirmation across agents, Postgres exclusion
  constraint against double booking, Gemini→Groq **failover with a circuit breaker**, JWT auth with
  tenant isolation, Redis rate limiting, prompt-injection guardrails, **Langfuse distributed tracing**,
  Docker, CI with 130 tests.
