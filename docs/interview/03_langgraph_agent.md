# 03 — The LangGraph Agent: Routing, Memory, Streaming

> Phase 1. How a customer message flows through the agent and comes back as a streamed answer.

---

## 1. Plain English first

When a message arrives, VoxDesk doesn't just throw it at the LLM. It runs a small, explicit
**workflow**:

1. **Route** — decide what the customer wants: a question about the business, a booking, or small
   talk. Also rewrite follow-up questions so they make sense on their own.
2. **Retrieve** — only for questions: fetch relevant document chunks (hybrid search).
3. **Respond** — generate the answer from those chunks, streamed word by word.
4. **Booking** — for now a "coming soon" reply; in Phase 2 this becomes real booking via MCP tools.

The conversation is **saved in Postgres after every step**, so the agent remembers earlier messages.

```
START → route ─┬─ knowledge → retrieve → respond → END
               ├─ smalltalk ───────────→ respond → END
               └─ booking ──→ booking ───────────→ END
```

---

## 2. What is LangGraph and why use it?

**LangGraph** lets you build an LLM application as a **graph**: *nodes* are Python functions
(steps), *edges* decide what runs next, and a typed *state* object flows through.

**Why not a single prompt or a free-running "agent loop"?**
| Single prompt / ReAct loop | Explicit graph (LangGraph) |
|---|---|
| LLM decides everything, including whether to search | Control flow is code you can read, test and debug |
| Hard to guarantee behaviour (e.g. "always search before answering prices") | Guarantees: knowledge questions *always* go through retrieval |
| Harder to add memory, human approval, streaming | Built-in checkpointing (memory), interrupts (human-in-the-loop, Phase 2), streaming |

**Say it like this:**
> "I modelled the agent as an explicit LangGraph state machine rather than letting the LLM loop
> freely. Routing is a structured LLM decision, but what happens after it is deterministic code —
> so behaviour is predictable and each node is testable. LangGraph also gives me checkpointed memory
> and streaming out of the box, and interrupts for human approval in the next phase."

---

## 3. The state

**File:** `app/graph/state.py`

```python
class ChatState(MessagesState):        # gives `messages` with an append-reducer
    business_id: str
    business_name: str
    business_description: str
    intent: Literal["knowledge", "booking", "smalltalk"]
    search_query: str
    context: list[dict]                # retrieved chunks for this turn
```

- `MessagesState` provides `messages` with a **reducer** (`add_messages`): when a node returns
  `{"messages": [reply]}`, it's **appended**, not overwritten. Other fields are simply replaced.
- Messages are **de-duplicated by ID** — we discovered this when a test reused the same message
  object twice and the second reply "disappeared" (it replaced the first). Good detail to know.

---

## 4. The nodes

**File:** `app/graph/builder.py`

### 4.1 `route` — intent + query rewriting in one call
```python
class Route(BaseModel):
    intent: Literal["knowledge", "booking", "smalltalk"]
    search_query: str     # latest question rewritten to be self-contained

structured_router = router_llm.with_structured_output(Route)
decision = await structured_router.ainvoke([system, *last_10_messages])
return {"intent": ..., "search_query": ..., "context": []}
```
- **Structured output:** instead of parsing free text like "I think this is a booking", Gemini is
  forced to return JSON matching the `Route` Pydantic schema. No fragile string parsing.
- **Query rewriting (a.k.a. query condensation):** the follow-up *"And how long does it take?"* is
  useless as a search query on its own. The router sees the history and rewrites it to *"duration
  of keratin treatment"*. Real result from testing — retrieval worked on the follow-up because of
  this.
- **Two jobs, one LLM call** — saves latency, which will matter a lot for voice.
- **Cheaper model:** routing uses `gemini-2.5-flash-lite` (fast, cheap); answers use
  `gemini-2.5-flash`. Right-sizing models per task is a cost/latency decision interviewers like.
- **Resets `context` to `[]`** each turn — state is checkpointed, so without this, last turn's chunks
  could leak into a small-talk reply.

### 4.2 `retrieve`
Runs hybrid search with the rewritten `search_query` (falls back to the raw message), filtered by
`business_id`. Stores chunks in `state["context"]`. Opens its own DB session — nodes don't share
request-scoped sessions.

### 4.3 `respond`
Builds a system prompt (`app/graph/prompts.py`) with the business name, numbered context
`[1]..[5]`, and rules: short and natural (it'll be spoken later — no markdown/bullets), answer only
from context with citations, say "I don't know" and offer staff when the answer isn't there.

### 4.4 `booking`
Placeholder returning a fixed message — no LLM call. Phase 2 replaces it with MCP booking tools.

### 4.5 Routing edge
```python
graph.add_conditional_edges("route", after_route, ["retrieve", "respond", "booking"])
```
`after_route` is plain Python reading `state["intent"]` — deterministic, testable.

### 4.6 History window
Only the **last 10 messages** are sent to the LLM (`HISTORY_WINDOW`). The full history stays in the
checkpoint. This bounds cost and latency on long conversations. *Future improvement:* summarise
older messages instead of dropping them.

### 4.7 Thinking disabled
Gemini 2.5 models can "think" before answering. We set `thinking_budget=0` — for short
customer-service answers the extra reasoning adds latency without improving quality, and latency is
critical for voice.

---

## 5. Memory: the Postgres checkpointer

**File:** `app/main.py` (lifespan)

```python
async with AsyncConnectionPool(settings.psycopg_url, max_size=10,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}) as pool:
    checkpointer = AsyncPostgresSaver(pool)
    await checkpointer.setup()            # creates checkpoint tables if missing
    app.state.graph = build_graph(..., checkpointer=checkpointer)
```

- After **every node**, LangGraph saves the full state to Postgres, keyed by `thread_id`.
- Next message with the same `thread_id` → LangGraph loads the state, appends the new message, and
  continues. That's the agent's memory.
- **Survives server restarts** (unlike in-memory storage), and works across multiple server
  instances because the state is in a shared database.
- **Connection pool** instead of a single connection → handles concurrent conversations.
- The graph is **compiled once at startup** (FastAPI `lifespan`) and reused for every request.
- `GET /chat/{business_id}/{thread_id}` reads the conversation back from the checkpoint
  (`graph.aget_state`) — the UI uses it to restore a chat after a page reload.

**Tenant safety:** the actual thread key is `f"{business_id}:{thread_id}"`. Even if someone guesses
another conversation's `thread_id`, they can't read it through a different business.

**Why psycopg here when the rest uses asyncpg?** LangGraph's Postgres checkpointer is built on
psycopg 3; SQLAlchemy uses asyncpg. Both talk to the same database — `settings.psycopg_url` just
strips the `+asyncpg` driver prefix.

---

## 6. Streaming with Server-Sent Events (SSE)

**File:** `app/api/chat.py`

**Plain English:** instead of waiting for the full answer, the server pushes events over one open
HTTP response as they happen. The UI shows words as they arrive — essential for perceived speed,
and in Phase 4 the voice pipeline will start speaking from the first sentence.

```python
async for mode, payload in graph.astream(inputs, config, stream_mode=["messages", "updates"]):
```
- **`messages` mode** → LLM tokens as they're generated. We forward only tokens from the `respond`
  node (`metadata["langgraph_node"] == "respond"`), otherwise the router's JSON would leak into the
  chat.
- **`updates` mode** → each node's output when it finishes. We use it to send the routing decision
  and the retrieved sources (for showing citations in the UI).

Event sequence the client receives:
```
event: meta     data: {"thread_id": "..."}
event: route    data: {"intent": "knowledge", "search_query": "keratin treatment cost"}
event: sources  data: [{"filename": "...", "chunk_index": 0, "content": "...", "score": 0.0325}]
event: token    data: {"text": "A keratin smoothing treatment costs ₹6,500 [1]."}
event: done     data: {}
```
Errors are caught inside the generator and sent as an `error` event — once streaming has started,
you can't change the HTTP status code anymore, so errors must travel in the stream.

**Why SSE and not WebSockets?** Chat is request → streamed response, one direction. SSE is plain
HTTP (works through proxies, simple to debug with curl). WebSockets are for two-way streams — we'll
use them in Phase 4 for audio, where the client streams microphone data continuously.

Headers: `Cache-Control: no-cache` and `X-Accel-Buffering: no` stop proxies (like nginx) from
buffering the stream.

---

## 7. Real test transcript (Glow Studio Salon sample)

```
USER: Hi there!                               → route: smalltalk  (no retrieval)
BOT:  Hi! How can I help you today?
USER: How much does a keratin treatment cost? → route: knowledge, query "keratin treatment cost"
BOT:  A keratin smoothing treatment costs ₹6,500 [1].
USER: And how long does it take?              → query rewritten: "duration of keratin treatment"
BOT:  The keratin smoothing treatment takes 3 hours [1].
USER: Do you do tattoos?                      → knowledge, nothing relevant found
BOT:  I don't have information about tattoo services. Would you like me to connect you with our staff?
USER: I want to book a haircut for Saturday   → route: booking
BOT:  I can't manage appointments just yet — that's coming soon. ...
```

---

## 8. Known limitations

1. The router is an extra LLM call per turn (~a few hundred ms). Alternatives: a small classifier
   model, or merging routing into the answer call with tools — a latency vs control trade-off.
2. History is truncated at 10 messages, not summarised.
3. No automated evaluation of routing accuracy yet (Phase 5).
4. Gemini streams in fairly large chunks, so short answers arrive in 1–3 token events.

---

## Q&A

**Q: What's the difference between a chain, an agent, and a graph?**
A: A chain is a fixed sequence of steps. An agent lets the LLM choose actions in a loop. A graph
(LangGraph) sits in between: you define the possible steps and transitions in code, and the LLM
makes specific decisions at specific points — predictable but flexible.

**Q: How does the agent remember the conversation?**
A: LangGraph's Postgres checkpointer saves state after every node, keyed by thread ID. Each new
message loads the previous state and appends. It survives restarts and works across instances.

**Q: Why is routing a separate step?**
A: So behaviour is guaranteed in code — knowledge questions always retrieve first, bookings go to
the booking flow, small talk skips retrieval (faster and cheaper). The same router becomes the
*supervisor* that delegates to specialist A2A agents in Phase 3.

**Q: What is structured output and why use it?**
A: Constraining the LLM to return JSON matching a schema (here the `Route` Pydantic model). It
removes brittle text parsing and guarantees valid values like one of three intents.

**Q: How do follow-up questions work with retrieval?**
A: The router rewrites the latest message into a standalone query using the conversation history,
e.g. "And how long?" → "duration of keratin treatment", and retrieval uses that.

**Q: SSE vs WebSockets vs polling?**
A: Polling wastes requests and adds delay. SSE is one-way server push over HTTP — ideal for
streaming a reply. WebSockets are bidirectional — needed for continuous audio in the voice phase.

**Q: How do you stop one business seeing another's conversations?**
A: Checkpoint thread keys are namespaced `business_id:thread_id`, and retrieval always filters by
`business_id`. (Authentication for the business dashboard comes in Phase 5.)

**Q: How would you handle a very long conversation?**
A: Currently a sliding window of 10 messages. Next step: a summarisation node that compresses older
turns into a running summary kept in state.
