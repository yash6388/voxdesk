# 06 — MCP: Our Booking Server, the Booking Agent, and Human-in-the-Loop

> Phase 2. This is the answer to **"Have you implemented MCP?"** — yes, both sides: we built an MCP
> server and our LangGraph agent consumes it as an MCP client.
>
> **Phase 3 update:** the booking graph now runs inside the **Booking agent A2A service**
> (`graph/booking_graph.py`, `agents/booking.py`); its confirmation pause surfaces as A2A
> `input-required`. See [`07_a2a.md`](07_a2a.md). Everything below still applies.

---

## 1. Plain English first

A customer says *"Book me a men's haircut tomorrow at 4."* To do that, the agent needs real
capabilities: list services, check free times, create a booking. Those capabilities live in a
separate **MCP server** that we wrote. The agent connects to it, discovers the tools, and calls
them. Before anything that changes data (book / cancel / reschedule), the graph **pauses** and the
customer must click **Confirm**.

```
Customer ──chat──► FastAPI ──► LangGraph booking agent ──MCP (HTTP)──► VoxDesk MCP server ──► Postgres
                                   │                                     list_services
                                   │ wants to book? ⏸ ask customer       check_availability
                                   ▼                                     book_appointment …
                              [Confirm] [Decline]
```

---

## 2. What MCP is (and isn't)

**MCP (Model Context Protocol)** is an open standard (from Anthropic, now widely adopted) for how
an AI application discovers and calls **tools** (also *resources* and *prompts*) that live
somewhere else.

- **MCP server** — exposes tools with names, descriptions and JSON input schemas, and executes them.
- **MCP client** — the AI app: connects, calls `tools/list`, gives the schemas to the LLM, and when
  the LLM picks a tool, sends `tools/call`.
- **Transports** — `stdio` (server runs as a local subprocess, e.g. Claude Desktop plugins) or
  **Streamable HTTP** (server is a network service — what we use).
- Messages are **JSON-RPC 2.0**.

### MCP vs plain function calling

| Plain function calling | MCP |
|---|---|
| Tool is a Python function inside the agent's process | Tool lives in a separate server/process |
| Only that app can use it | **Any MCP client** can use it: our agent, MCP Inspector, Claude Desktop, Cursor… |
| Tool code deploys with the agent | Tool server deploys, scales and is secured independently |
| No discovery — the app hard-codes the tool list | Client discovers tools at runtime (`tools/list`) |

### MCP vs A2A (next phase)
**MCP connects an agent to tools. A2A connects an agent to other agents.** A tool is a function
with a schema; an agent is an autonomous peer that can reason, hold a multi-step task and respond
over time. In Phase 3 the booking agent becomes an A2A service, and *it* will still use MCP for
its tools.

**Say it like this:**
> "I built the booking capabilities as an MCP server rather than as in-process functions, so the
> tools are decoupled from the agent: they run, scale and are secured as their own service, and
> any MCP client can use them — I can point the MCP Inspector or Claude Desktop at the same server
> with zero code changes. The LangGraph agent consumes them through langchain-mcp-adapters."

---

## 3. The MCP server

**File:** `backend/app/mcp/server.py` · run with `uv run python -m app.mcp.server` (port 8001)

Built with **FastMCP** from the official `mcp` Python SDK. A tool is a decorated async function —
the SDK builds the JSON schema from the type hints and uses the docstring as the description the
LLM reads:

```python
@mcp.tool()
async def check_availability(service_id: str, date: str, ctx: Context) -> dict:
    """List free start times (HH:MM) for a service on a date (YYYY-MM-DD)."""
```

### The 7 tools
| Tool | Type | Purpose |
|---|---|---|
| `get_business_info` | read | name, timezone, **current local date/time**, weekly hours (so "tomorrow" can be resolved) |
| `list_services` | read | services with ids, durations, prices |
| `check_availability` | read | free start times for a service on a date |
| `find_my_bookings` | read | a customer's upcoming bookings by phone |
| `book_appointment` | **write** | create a booking |
| `reschedule_booking` | **write** | move a booking (phone must match) |
| `cancel_booking` | **write** | cancel a booking (phone must match) |

### Tool design decisions (interviewers love these)
- **Docstrings are prompts.** The LLM chooses tools based on name + description, so they're written
  for the model: what it does, formats (`YYYY-MM-DD`, `HH:MM`), and when to call it ("only after the
  customer has chosen a time and given name and phone").
- **Date and time are separate string arguments** rather than one ISO datetime — LLMs fill
  `date="2026-10-18", time="16:00"` more reliably than timezone-aware timestamps.
- **Errors are user-safe messages** (`ToolError("Sorry, that time is already booked.")`), so the
  agent can relay them and suggest alternatives.
- **Small, single-purpose tools** instead of one giant "manage_booking" tool — easier for the model
  to choose correctly.
- **Stateless HTTP** (`stateless_http=True`) — no server-side session between requests, so the server
  can run as many replicas behind a load balancer.

### Security: who may call, and for which business
Every request must carry two headers:
```
Authorization: Bearer <MCP_API_KEY>    → may you call this server at all?  (middleware, constant-time compare)
X-Business-Id: <uuid>                  → which tenant is this call for?
```
**The tenant comes from the connection, never from tool arguments.** No tool has a `business_id`
parameter (there's a test asserting this). The `ctx: Context` parameter is injected by the SDK and
hidden from the schema. So even a prompt-injected LLM cannot be talked into touching another
business's bookings — it has no way to name one.

Customer-level checks on top: cancelling or rescheduling requires the **phone number used to book**
(normalised, so `98765 43210` = `9876543210`).

**Say it like this:**
> "Tenant identity is a property of the authenticated connection, not something the model chooses.
> The tool schemas don't even contain a business id, so prompt injection can't cross tenants."

---

## 4. Booking domain logic and the double-booking guarantee

**File:** `backend/app/booking/service.py` — shared by the MCP server *and* the owner REST API, so
the rules live in one place.

Rules enforced: service must be active and belong to the business; time must be in the future,
inside opening hours for that weekday, with the full service duration fitting before closing;
slots step every 30 minutes; bookings up to 60 days ahead; all times timezone-aware (stored UTC,
shown in the business's timezone).

### The best story in this phase: preventing double bookings
Checking "is this slot free?" in code isn't enough. Two customers booking 4 pm at the same moment
can **both** pass the check before either saves — a classic race condition.

The fix is in the database itself — a Postgres **exclusion constraint**:
```sql
EXCLUDE USING gist (
    business_id WITH =,
    tstzrange(start_at, end_at, '[)') WITH &&
) WHERE (status = 'confirmed')
```
Meaning: *no two confirmed bookings of the same business may have overlapping time ranges.*
- `tstzrange(start, end, '[)')` — a time range including start, excluding end, so 15:00–15:30 and
  15:30–16:00 don't conflict.
- `&&` — the "overlaps" operator.
- `WHERE status = 'confirmed'` — cancelled bookings don't block the slot.
- Needs the `btree_gist` extension to combine `=` on a UUID with `&&` on a range in one GiST index.

The app still checks first (for a friendly message); the constraint is the **guarantee**. If it
fires, we catch the `IntegrityError` and return *"Sorry, that time was just booked by someone
else."* There's a test that forces the race (both requests skip the app check) and asserts exactly
one succeeds.

**Say it like this:**
> "Application-level checks can't prevent double booking under concurrency, so I enforce it in
> Postgres with an exclusion constraint over a time range — the database rejects overlapping
> confirmed bookings atomically, and I have a test that reproduces the race."

---

## 5. The booking agent (MCP client side)

**Files:** `backend/app/graph/builder.py`, `backend/app/graph/tools.py`

```
route ─ booking → booking_agent ─┬─ no tool calls ───────────────────→ END (reply to customer)
                       ▲         ├─ read tools ────→ tools ─┐
                       │         └─ write tools ─→ confirm ─┤  ⏸ interrupt()
                       └────────────────────────────────────┘
```

- **Loading tools:** `MCPToolProvider.get_tools(business_id)` uses `MultiServerMCPClient` from
  `langchain-mcp-adapters` with the auth + tenant headers. It calls `tools/list` and returns
  LangChain tools that each send `tools/call` when invoked.
- **`booking_agent` node:** Gemini with the tools bound (`chat_llm.bind_tools(tools)`), a booking
  system prompt that includes the current local date/time, and the **last 3 turns in full**
  (including tool calls and results — see §7).
- **Routing after the agent** is plain code: no tool calls → reply; only read tools → run them;
  any write tool → `confirm` first.
- **`tools` node:** invokes each requested tool with the full tool call, which returns a
  `ToolMessage` linked to the call id; results go back to the agent, which loops until it has a
  final answer.
- **Resilience:** if the MCP server is unreachable, the agent replies *"I can't reach our booking
  system right now…"* instead of crashing (tested).

---

## 6. Human-in-the-loop with `interrupt()`

**Why:** booking, cancelling and rescheduling have real-world consequences. LLMs can misunderstand
("Tuesday" vs "Thursday"). The customer should see exactly what will happen and approve it.

**How (`confirm` node):**
```python
decision = interrupt({"actions": [...human-readable summaries...]})
if decision["approved"]:  return Command(goto="tools")
else:                      return Command(goto="booking_agent", update={"messages": [declined ToolMessages]})
```
- `interrupt()` **saves the graph state to the Postgres checkpoint and stops the run.** The SSE
  stream sends a `confirm` event; the UI shows a card with Service / Date / Time / Name / Phone.
- The customer clicks Confirm or Decline → `POST /chat/resume {approved}` → the backend calls
  `graph.astream(Command(resume={"approved": ...}))` → the graph continues **inside `confirm`**,
  possibly on a different server instance, hours later.
- Declining doesn't just stop: the agent receives "customer declined" and asks what they'd like
  instead.
- While a confirmation is pending, `POST /chat` returns **409** and the UI locks the composer; the
  history endpoint returns `pending_confirmation` so the card reappears after a page reload.
- **Read-only tools don't ask** — only writes do. Confirmation fatigue is a real UX problem.
- The summary card resolves ids to names from the database (e.g. service id → "Men's haircut").

**Say it like this:**
> "Write actions go through a human-in-the-loop step built on LangGraph's interrupt: the graph
> checkpoints itself and pauses, the UI shows a confirmation card, and a resume endpoint continues
> the graph with the customer's decision. Because state is in Postgres, the pause survives restarts
> and works across instances."

---

## 7. Real bugs found by live testing (tell these stories!)

### Bug 1 — the agent invented a service id
Turn 1: agent called `list_services`, then `check_availability`, and offered times.
Turn 2 ("4pm works"): it called `book_appointment(service_id="mens-haircut", customer_name="John Doe", …)`.
**Cause:** to keep context clean, earlier turns' tool results were being dropped, so the real
service UUID was gone and the model guessed.
**Fix:** the booking agent sees the **last 3 turns in full**. Slicing at customer messages keeps
every tool call paired with its result (Gemini rejects orphaned tool results).

### Bug 2 — the agent invented the customer's name and phone, despite the prompt
Even with an explicit rule ("never use placeholders like John Doe"), Gemini still filled in a fake
name and number. **Lesson: a prompt is a request, not a guarantee.**
**Fix — a deterministic grounding guardrail** (`ungrounded_customer_details`): before asking the
customer to confirm, code checks that the phone digits and every word of the name **appear in
something the customer actually said**. If not, the call goes back to the agent with
*"The customer hasn't given their name and phone — ask for it."* The confirm step also validates
ids (unknown service/booking → back to the agent). The customer never sees a nonsense card.

After the fix, the same conversation went: offer times → *"what's your name and phone number?"* →
real details → confirmation card → Confirm → booked.

### Defence in depth (the summary)
| Layer | Catches |
|---|---|
| Prompt rules | Most mistakes, most of the time |
| Full recent context | Guessed ids from forgotten tool results |
| Grounding guardrail + id validation (code) | Invented customer details, unknown ids |
| Human confirmation | Misunderstood intent (wrong day/service) |
| Domain rules (service layer) | Past times, closed days, outside hours |
| DB exclusion constraint | Concurrent double booking |

**Say it like this:**
> "I treat the LLM as untrusted input. Prompts guide it, but anything that must hold is enforced in
> code: arguments are validated and grounded against what the customer said before a human is even
> asked, the human confirms writes, and the database enforces the invariants."

### Operational finding — free-tier quota
Google's free tier allowed only **20 requests/day per model** for this project. A booking
conversation makes several LLM calls (agent → tool → agent…), so testing hit `429
RESOURCE_EXHAUSTED`. Improvements made: LLM retries capped at 2 (the SDK had been silently backing
off ~35 s before failing), and rate limits now show *"Our assistant is handling too many requests
right now"* instead of a generic error. Production answer: paid tier, model fallbacks, per-tenant
rate limiting, and caching.

---

## 8. Owner side (dashboard)

- **Services & hours** page — add services (name, minutes, price), hide/show them (never hard-deleted,
  so past bookings keep their service), edit the weekly schedule.
- **Bookings** page — today / upcoming / cancelled counts, upcoming and past tabs, owner cancel;
  auto-refreshes so a booking made in the Playground appears within seconds. Times are shown in the
  **business's** timezone, not the viewer's.
- **Playground** — confirmation card in the chat; the Agent Inspector shows every MCP tool call with
  arguments, status and result.
- `scripts/seed_demo.py` — creates the demo salon's services, hours and document (idempotent).

---

## 9. Testing (39 tests total; Phase 2 added 23)

| File | Proves |
|---|---|
| `test_booking.py` | Slots respect hours/closed days; booked slots disappear; double booking rejected; **concurrent race stopped by the DB constraint**; outside-hours/closed-day rejections; phone-matched cancel; cancel frees slot; reschedule frees old slot; phone normalisation |
| `test_mcp_server.py` | Tool schemas never expose `business_id`; list/availability; book → find → cancel through FastMCP; domain errors become tool errors; bad ids rejected; **no API key → 401** |
| `test_graph.py` | Read tools run without confirmation; **write tool pauses → nothing runs → approve → runs**; decline → never runs; **invented details go back to the agent, no confirmation shown**; MCP down → graceful reply; guardrail unit test |
| `test_api.py` | Services/hours CRUD; invalid hours (backwards, duplicate day) → 422; unknown timezone → 422 |

---

## 10. Limitations (say them first)

1. **One appointment at a time per business** — no staff/resources (e.g. 3 stylists = 3 parallel
   slots). Next step: a `resources` table and the exclusion constraint on `resource_id`.
2. Phone number as ownership proof is lightweight — real systems would verify via OTP.
3. Shared static API key between agent and MCP server; production would use OAuth 2.1 (which the
   MCP spec supports) or mTLS, and per-client keys.
4. No buffer time between appointments, holidays or special hours yet.
5. Tools are re-listed on each agent step (one cheap `tools/list` call) — could be cached per tenant.

---

## Q&A

**Q: Did you implement MCP?**
A: Yes, both sides. I built an MCP server with FastMCP exposing seven booking tools over Streamable
HTTP with bearer-token auth and header-based tenant scoping, and the LangGraph agent consumes it via
langchain-mcp-adapters. The same server works with the MCP Inspector or Claude Desktop unchanged.

**Q: Why MCP instead of just function calling?**
A: Decoupling and reuse. Tools become an independently deployed, secured and scaled service with
runtime discovery, usable by any MCP client — not code locked inside one agent.

**Q: stdio vs Streamable HTTP?**
A: stdio runs the server as a local subprocess — great for desktop tools, one client per process.
Streamable HTTP makes it a network service — multiple clients, remote deployment, load balancing.
A multi-tenant SaaS needs HTTP.

**Q: How do you stop the agent booking for the wrong business?**
A: The business id travels as a header on the authenticated MCP connection; tool schemas have no
business parameter, so the model can't choose one.

**Q: How do you prevent double booking?**
A: App-level check for a friendly message, plus a Postgres exclusion constraint on
`(business_id, tstzrange(start, end))` for confirmed bookings, which makes overlaps impossible even
under concurrent requests. Tested with a forced race.

**Q: What if the LLM calls the booking tool with made-up data?**
A: Before the customer is asked to confirm, code validates ids against the database and checks that
the name and phone appear in the customer's own messages; failures go back to the agent. Then the
human confirms. Then domain rules and DB constraints apply.

**Q: How does human-in-the-loop work across HTTP requests?**
A: LangGraph's `interrupt()` checkpoints state to Postgres and ends the run; a resume endpoint sends
`Command(resume=...)` for the same thread, and execution continues inside the paused node.

**Q: How would you scale the MCP server?**
A: It's stateless HTTP, so run N replicas behind a load balancer; the database is the shared state.
Add per-tenant rate limits and cache read-heavy tools like `list_services`.
