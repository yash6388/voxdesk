# 05 — Frontend: Next.js, Streaming Chat, Upload Status

> Phase 1. The backend is the focus of VoxDesk, but you should be able to explain how the browser
> talks to it — especially how a streamed reply is read and rendered.

---

## 1. Plain English first

The frontend is a Next.js SaaS app with a public landing page and a dashboard:

| Route | Screen |
|---|---|
| `/` | **Landing page** — hero with a chat preview, features (built + coming soon), how it works, CTA |
| `/dashboard` | **Businesses** — cards with gradient avatars, "New business" modal, empty state |
| `/dashboard/b/[id]` | **Playground** — chat with the business's agent + **Agent Inspector** (route, rewritten query, sources with scores, latency) |
| `/dashboard/b/[id]/knowledge` | **Knowledge base** — stats, drag-and-drop upload, documents table with live status |
| `/dashboard/b/[id]/services` | **Services & hours** (Phase 2) — add/hide services, weekly opening hours editor |
| `/dashboard/b/[id]/bookings` | **Bookings** (Phase 2) — today/upcoming/cancelled stats, tabs, owner cancel, auto-refresh, times in the business's timezone |

```
frontend/src/
├── app/
│   ├── layout.tsx                      fonts + global styles only
│   ├── page.tsx                        landing page
│   └── dashboard/
│       ├── layout.tsx                  app shell: sidebar + content
│       ├── page.tsx                    businesses
│       └── b/[id]/
│           ├── page.tsx                playground (chat + inspector)
│           └── knowledge/page.tsx      knowledge base
├── components/
│   ├── ui/                             design system: Button, Card, Badge, Input, Dialog, PageHeader
│   ├── app/Sidebar.tsx                 navigation (desktop sidebar + mobile drawer)
│   ├── chat/ChatPanel.tsx              streaming chat, citations, suggestions
│   ├── chat/Inspector.tsx              per-turn agent trace + latency
│   ├── Logo.tsx, BackendStatus.tsx
└── lib/
    ├── api.ts                          typed API client + SSE stream parser
    ├── useDocuments.ts                 documents hook (upload, delete, polling)
    └── utils.ts                        cn(), avatar gradients, formatting
```

### Design system
- **Tokens** in `globals.css` (`--background`, `--surface`, `--border`, `--muted`) exposed to
  Tailwind as `bg-surface`, `border-border`, `text-muted` — light and dark mode switch by changing
  token values only.
- **Colour system:** zinc neutrals + one brand accent (indigo). The indigo → violet → fuchsia
  **gradient is reserved for brand moments** (logo, hero headline, CTA banner); everything else
  uses **solid indigo** (buttons, user bubbles) or a shared **soft tint** (`BRAND_TINT` in
  `lib/utils.ts`: icon tiles, bot avatar). Status colours (green/amber/red) are only used for
  status, never decoration — so they stay meaningful.
- **Shared components** in `components/ui/` so every page looks consistent; icons from Lucide.
- Small touches that make it feel like a product: skeleton loaders, fade-in animations, typing
  dots, empty states with a clear next action, live "API online" indicator.

## 2. Next.js basics you should know

- **App Router:** folders under `src/app/` are routes. `b/[id]/page.tsx` is a dynamic route —
  `/b/abc-123` gives `id = "abc-123"` (read with `useParams()`).
- **Server vs client components:** by default components render on the server. Anything using
  state, effects or browser APIs (`useState`, `fetch` streams, `localStorage`) needs `"use client"`
  at the top. Our interactive panels are client components; `layout.tsx` and the home `page.tsx`
  stay server components that just render them.
- **`NEXT_PUBLIC_API_URL`:** env vars prefixed `NEXT_PUBLIC_` are embedded into browser code at
  build time. It tells the browser where the FastAPI backend is (default `http://localhost:8000`).
- **Tailwind CSS:** utility classes (`rounded-lg border p-4`) instead of separate CSS files; dark
  mode via `dark:` variants.

---

## 3. One typed API client

**File:** `src/lib/api.ts`

All backend calls go through one place. TypeScript types (`Business`, `VoxDocument`, `ChatEvent`…)
mirror the backend's Pydantic schemas, so a field typo is a compile error, not a runtime bug.
A small `request()` helper handles JSON, error messages (FastAPI's `detail`) and `204 No Content`.

**Say it like this:**
> "The frontend has a single typed API client mirroring the backend's Pydantic schemas, so API
> contract changes surface as TypeScript errors. Components never call `fetch` directly."

---

## 4. Reading the streamed reply (the interesting part)

The backend streams **Server-Sent Events** from `POST /chat` (see `03_langgraph_agent.md`).

**Why not the browser's built-in `EventSource`?** It only supports `GET` requests with no body. We
need `POST` with JSON (business id, message, thread id). So we read the stream manually:

```ts
const res = await fetch(`${API_URL}/chat`, { method: "POST", body: ..., signal });
const reader = res.body.getReader();
let buffer = "";
while (true) {
  const { value, done } = await reader.read();
  if (done) break;
  buffer += decoder.decode(value, { stream: true });
  const frames = buffer.split("\n\n");   // SSE frames end with a blank line
  buffer = frames.pop() ?? "";            // last piece may be incomplete — keep it
  for (const frame of frames) { ...parse "event:" and "data:" lines... yield event }
}
```

Key details:
- **Network chunks ≠ SSE frames.** One `read()` can contain half a frame or three frames. Keeping
  the incomplete tail in `buffer` until the next read is what makes parsing correct.
- **`decode(value, { stream: true })`** handles multi-byte characters (like `₹`) split across
  chunks.
- **Async generator (`async function*`)** — the chat component simply writes
  `for await (const ev of streamChat(...))` and handles each event type.
- **`AbortController`** — "New chat" or leaving the page cancels the in-flight request.

### How events update the UI (`components/chat/ChatPanel.tsx`)
On send, the UI immediately adds the user's message and an **empty assistant message** (with its own
id), then patches that message as events arrive:

| Event | UI effect |
|---|---|
| `meta` | Save `thread_id` (state + `localStorage`) |
| `route` | Inspector shows intent + the rewritten search query |
| `sources` | Inspector lists cited chunks with RRF scores; `[1]` in the answer becomes a citation chip |
| `token` | Append text → the answer appears progressively; first token records **time-to-first-token** |
| `error` | Show error inline |

### Confirmation card (Phase 2)
When the stream sends a `confirm` event, the assistant message shows a card (Service / Date / Time /
Name / Phone) with **Confirm** and **Decline**. Clicking calls `POST /chat/resume` via the same SSE
parser (`streamEvents` is shared by `streamChat` and `resumeChat`), and the outcome streams into a
new assistant message. While a confirmation is pending the composer is locked; after a reload the
history endpoint returns `pending_confirmation` so the card comes back.

### The Agent Inspector
Clicking any reply shows, for that turn: the **route** (knowledge / booking / small talk), the
**standalone search query** the router produced, the **sources** with scores, and **latency**
(time to first token and total, measured in the browser with `performance.now()`).

Why build it: it makes the agent's reasoning visible — great for debugging, and the best demo
moment in an interview ("watch the router rewrite my follow-up question"). Time-to-first-token is
also the metric that matters most once voice arrives in Phase 4.

---

## 5. Conversation persistence across reloads

- The `thread_id` is saved in `localStorage` per business.
- On page load, if one exists, the UI calls `GET /chat/{business_id}/{thread_id}`, which reads the
  messages back from the **LangGraph Postgres checkpoint**.
- So the source of truth is the server; the browser only remembers *which* conversation it was in.
- `localStorage` access is wrapped in `try/catch` (private browsing can block it) — the chat still
  works, it just won't survive a reload.

---

## 6. Upload status: polling

Ingestion runs as a background task on the server (`202 Accepted`). The `useDocuments` hook polls
`GET /documents` **every 2 seconds, only while at least one document is `processing`**, and stops
automatically when everything is `ready`/`failed`.

**Why polling and not WebSockets/SSE here?** Ingestion takes seconds and happens rarely; polling is
simple, stateless and reliable. Push updates would be over-engineering at this stage — but you can
mention Redis pub/sub + SSE as the upgrade path for a live dashboard (Phase 5).

---

## 7. CORS

The frontend (`localhost:3000`) and backend (`localhost:8000`) are different **origins**, so the
browser blocks requests unless the backend allows them. FastAPI's `CORSMiddleware` allows the
origins listed in `CORS_ORIGINS`. For `POST` with JSON, the browser first sends an `OPTIONS`
**preflight** request — we verified it returns 200.

---

## 8. A real gotcha we hit

Running `npm run build` while `next dev` was running broke the dev server with
`Cannot find module './586.js'` — both write to the same `.next/` folder. Fix: stop dev,
`rm -rf .next`, restart. Lesson: build and dev share output; don't run them at the same time.

---

## Q&A

**Q: Why Next.js instead of plain React + Vite (like FilingLens)?**
A: Industry standard for production React apps — file-based routing, server components, built-in
optimisation, easy deployment (Vercel). It also shows range beyond the Vite setup in FilingLens.

**Q: How do you stream an LLM response to the browser?**
A: The backend sends Server-Sent Events; the frontend reads `response.body` with a stream reader,
buffers until complete `\n\n`-separated frames, parses `event`/`data` lines, and updates the last
message as tokens arrive. EventSource can't be used because it's GET-only.

**Q: Where is chat history stored?**
A: Server-side in the LangGraph checkpoint (Postgres). The browser only stores the thread id and
re-fetches history on load.

**Q: What's CORS and why did you need it?**
A: A browser security rule blocking cross-origin requests unless the server explicitly allows them.
Frontend and API run on different ports, so the API whitelists the frontend's origin.

**Q: Why poll for document status?**
A: Ingestion is short and infrequent; polling only while something is processing is the simplest
correct solution. Push (SSE/WebSocket via Redis pub/sub) is the upgrade if it ever matters.
