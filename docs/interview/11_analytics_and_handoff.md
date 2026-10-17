# 11 — Analytics and Human Handoff

> Phase 5, Step 6. The owner can now see **how the agent is doing** (Analytics page), and the agent
> can **pass a customer to a real person** (handoff → Inbox). Small feature on screen; a lot of good
> interview material underneath: event-driven recording, atomic upserts, SQL analytics, and a bug
> that only live testing found.

---

## 1. Plain English first

Two questions every business owner asks about an AI assistant:

1. **"Is it working?"** How many people talked to it, what did they want, did they book, how fast
   did it answer, did anything go wrong? → the **Analytics** page.
2. **"What happens when it can't help?"** Some customers just want a human (a complaint, a special
   request). A good assistant recognises that, says "I've passed this to the team", and makes sure
   the team actually sees it. → **handoff** + the **Inbox**.

```
customer message ─► supervisor graph ─► events (route, token, tool_result, handoff, …) ─► browser
                                                │
                                                └─► TurnRecorder ─► conversations + turns tables
                                                                         │
                                         Analytics page  ◄── SQL ────────┤
                                         Inbox (needs a human) ◄─────────┘
```

---

## 2. How recording works — `backend/app/analytics.py`

### The key idea: listen to the same events the browser gets

Every turn already produces a stream of events for the UI (`conversation.py → run_events`):
`meta → route → delegation → tool_call → tool_result → token… → confirm? → done` (or `guardrail`,
`handoff`, `error`).

Instead of adding analytics code inside the graph or the agents, a `TurnRecorder` **observes that
stream** (`recorder.observe(event, data)` in `api/chat.py` and `api/voice.py`) and works out what
happened:

| Event seen | What the recorder notes |
|---|---|
| `route` | the intent (knowledge / booking / smalltalk / handoff) |
| `token` | appends to the reply text (for the preview) |
| `confirm` | a booking is waiting for the customer's yes/no |
| `tool_result` of `book_appointment` with success | a booking was made |
| `decision` approved=false (resume) | booking declined |
| `handoff` | customer wants a person (+ the reason) |
| `guardrail` / `error` | blocked / failed |

One turn gets **one outcome**, picked by priority:
`guardrail > error > handoff > booked > booking_declined > booking_pending > answered`.
(Why a priority? A turn can produce several signals — e.g. a booking tool call *and* an error later.
The priority says which one describes the turn best.)

**Say it like this:** *"Analytics is event-driven. The recorder subscribes to the same event stream
the client receives, so chat and voice share one implementation, and the agents don't know analytics
exists. Adding a new channel means just passing its events to the recorder."*

### Saving: one atomic upsert

Each turn does two writes in one transaction:

1. **Upsert the conversation** — create it on the first turn, otherwise bump `turn_count` and
   `last_activity_at` (and set `needs_human` on a handoff):
   ```sql
   INSERT INTO conversations (...) VALUES (...)
   ON CONFLICT ON CONSTRAINT uq_conversations_thread
   DO UPDATE SET turn_count = conversations.turn_count + 1, last_activity_at = now(), ...
   RETURNING id;
   ```
2. **Insert the turn** row with intent, outcome, short previews and timings.

Why an upsert rather than "SELECT, then INSERT or UPDATE"? Two requests for the same conversation
could both see "doesn't exist" and both insert → duplicate or a unique-constraint error. The upsert
is **one atomic statement**; the database settles the race. `turn_count + 1` is computed inside the
database too, so concurrent turns can't lose an increment.

### Never break a conversation

`save()` catches and logs any exception. Analytics is secondary — if its table is locked or the
migration hasn't run, the customer must still get their answer. (Same philosophy as the rate limiter
failing open.)

### What's stored (and what isn't)

- `conversations`: one row per chat/voice thread — channel, status (`open` / `needs_human` /
  `resolved`), handoff reason, turn count.
- `turns`: one row per customer message — intent, outcome, **previews** (500/1000 chars),
  `first_token_ms`, `total_ms`. Indexed on `(business_id, created_at)` because every analytics query
  filters by business and date range.
- **Full transcripts are not copied.** They already live in the LangGraph checkpoint (the agent's
  memory). The Inbox reads them from there with `graph.aget_state(...)` — one source of truth.

---

## 3. Analytics SQL — `backend/app/api/insights.py`

`GET /businesses/{id}/analytics?days=30` (owner-only — same `OwnedBusiness` dependency as
everything else, so other tenants get 404).

- **Counts by outcome / intent / channel**: `SELECT outcome, count(*) … GROUP BY outcome`.
- **Daily series in the business's timezone.** A salon in India thinks in Indian days. Grouping by
  UTC date would put 1 a.m. IST messages on "yesterday". So:
  `date(timezone('Asia/Kolkata', created_at))` — Postgres converts each timestamp to local time first.
  Missing days are filled with zeros in Python so the chart has no gaps.
- **Latency percentiles in the database:**
  `percentile_cont(0.5) WITHIN GROUP (ORDER BY first_token_ms)` and the same with 0.95.
  p50 = typical customer; p95 = the slow tail (1 in 20 waits at least this long). Averages hide the
  tail; percentiles don't.

### Bug found by a test: two different "todays"

The SQL grouped by **local** date, but Python built the list of days from `date.today()` on the
server (**UTC**). Shortly after midnight UTC (early morning IST) "today" differed between the two, so
today's messages fell outside the chart. The test caught it; fix: build the range from
`datetime.now(ZoneInfo(business.timezone)).date()`. Lesson: **one timezone rule, applied
everywhere** in a calculation.

---

## 4. Human handoff

### Flow

1. The router gained a 4th intent, **`handoff`** (`graph/state.py`): "wants a human — asks for
   staff/a person/the manager, is upset or complaining, or says yes after the assistant offered to
   connect them with staff".
2. The `handoff` node (`graph/supervisor.py`) does **not** call an LLM: it streams a fixed, polite
   reply (`HANDOFF_REPLY`: "I've let the team know… please share your name and phone number") and
   emits a `handoff` event with the reason.
3. The recorder sees `handoff` → the conversation becomes **`needs_human`**.
4. The owner sees it in the **Inbox** (sidebar badge with the count), reads the transcript (incl.
   the customer's name/number), follows up, clicks **Mark resolved**.

Why a fixed reply? It's a promise on behalf of the business ("someone will get back to you"); it must
be consistent and must not invent things like "within 10 minutes".

Why no live takeover (staff typing into the same chat)? That needs a realtime staff console,
presence, and rules for when the AI goes quiet. The flag + Inbox covers the real need — *make sure a
human follows up* — with a fraction of the complexity. Live takeover is a clear "next step" answer.

### The bug only live testing found

Test conversation:
> **Customer:** I'd like to speak to a real person about a complaint.
> **Agent:** Of course — I've let the team know… please share your name and phone number.
> **Customer:** Sure, it's Priya, 98765 43210
> **Agent:** Of course — I've let the team know… please share your name and phone number. 🤦

The router classified the reply as `handoff` again (the conversation is "about" handing off), so the
customer got the same canned message twice. Unit tests didn't catch it because they use a fake router
that returns whatever we script.

**Fix attempt 1 — prompt:** added "giving their name or phone number after the assistant passed them
to staff → smalltalk" to the intent description. The live router *still* said `handoff`.

**Fix 2 — code (kept):** in the `route` node, if the router says `handoff` **and the previous
assistant message was the handoff reply**, change the intent to `smalltalk`. The small-talk node then
answers naturally ("Thanks, Priya! I've passed your number to the team…"). Because the change happens
in `route` (not in the edge function), the recorded intent and the Inspector are also correct.

**Say it like this:** *"When a rule must always hold, I enforce it in code instead of hoping the
prompt is followed. The prompt fix didn't hold with the real model; a two-line deterministic check
did, and it's covered by a regression test."* (Same lesson as the booking guardrail in `06_mcp.md`.)

The golden set got 3 handoff routing cases (16/16 correct) — but this follow-up case is exactly what
the golden set *didn't* contain. Evals measure what you thought of; live testing finds the rest.

---

## 5. The frontend

- **Analytics page** (`dashboard/b/[id]/analytics`): range filter (7/30/90 days), six KPI tiles
  (conversations, bookings + conversion %, time-to-first-word p50/p95, handoffs with a link to the
  Inbox, guardrail blocks, errors), a messages-per-day area chart, and bar lists for outcomes,
  intents and channels. Refreshes every 30 s.
- **Charts are hand-written SVG** (`components/analytics/Charts.tsx`), no chart library: an area
  chart with a crosshair tooltip that snaps to the nearest day, and horizontal bars with the value at
  the tip. Choices: one colour (it's magnitude, not categories), thin marks, hairline gridlines, a
  "Show table" toggle for accessibility. Colours were run through a palette validator (contrast,
  lightness band) for **both** light and dark mode: indigo-600 on light, indigo-500 on dark (the
  lighter indigo-400 failed the dark-mode lightness band).
- **Inbox** (`dashboard/b/[id]/inbox`): "Needs a human" / "All conversations" tabs, transcript view,
  Mark resolved. Resolving fires a browser event so the sidebar badge updates immediately (otherwise
  it polls every 20 s).
- **Inspector** shows a "Handoff" route and a note when a turn was flagged.

Why no chart library? Three simple charts; a library would add ~100 KB+ and fight the design system.
Hand-written SVG also shows you understand scales and coordinates (`x = left + i/(n-1) * width`).

---

## 6. Verified results

- 130 backend tests (7 new: outcome derivation table, upsert + handoff flag, handoff node, **no
  repeat handoff**, analytics aggregates, inbox list/transcript/resolve, tenant isolation).
- Live: handoff turn → `route: handoff` → `handoff` event → canned reply → conversation in Inbox;
  the follow-up with contact details → `route: smalltalk`, natural reply, not re-flagged.
- Rendered both pages in light, dark and mobile widths with synthetic data (then deleted it); fixed
  overlapping axis labels on mobile and a tooltip covering the line.

## 7. Limitations / next steps

- No live human takeover or notifications (email/Slack/WhatsApp on handoff) yet — notifications are
  the obvious next step.
- Customer contact details are only in the transcript; extracting them into fields (structured output)
  would make the Inbox actionable at a glance.
- Analytics queries hit the raw `turns` table; at large scale you'd pre-aggregate per day
  (materialised view or a nightly rollup).
- "Fallback usage" (Gemini vs Groq per turn) is visible in Langfuse traces, not yet in the owner
  dashboard.

---

## Q&A

**Q: How do you record analytics without slowing down or coupling the agent?**
A: The recorder observes the event stream the client already gets, then writes once at the end of the
turn — after the reply has streamed. Failures are logged and swallowed, so analytics can never break
a conversation.

**Q: Why an upsert?**
A: Create-or-update in one atomic statement. Read-then-write has a race between two concurrent
requests; `INSERT … ON CONFLICT DO UPDATE` lets the database resolve it, and `turn_count + 1` is
computed in the database so no increment is lost.

**Q: Why p50 and p95 instead of the average?**
A: Averages hide the slow tail. p95 tells you what the unluckiest 1 in 20 customers experience —
that's who complains.

**Q: How do you handle timezones in daily charts?**
A: Convert timestamps to the business's timezone in SQL before taking the date, and build the day
range in the same timezone. A test caught a mismatch where Python used UTC.

**Q: Why store transcripts in the checkpoint and not in your own table?**
A: The checkpoint already is the conversation's memory; copying it creates two sources of truth that
can drift. The turns table keeps only short previews for lists.

**Q: How does the agent decide to hand off?**
A: It's an intent in the router's structured output. The handoff node replies with a fixed message
and emits an event; the recorder flags the conversation for the Inbox.

**Q: Tell me about a bug you found in live testing.**
A: After a handoff, the customer's reply with their name and number was routed to handoff again and
got the same canned message. A prompt fix didn't hold with the real model, so I enforced it in code:
no handoff right after a handoff reply. Added a regression test.

**Q: Analytics vs Langfuse — why both?**
A: Langfuse is for engineers: per-call traces, prompts, tokens, latency breakdowns. Analytics is for
the business owner: tenant-scoped product metrics in our own database, queryable with SQL and shown in
the dashboard.
