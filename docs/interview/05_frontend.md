# 05 — Frontend: Next.js, Streaming Chat, Upload Status

> Phase 1. The backend is the focus of VoxDesk, but you should be able to explain how the browser
> talks to it — especially how a streamed reply is read and rendered.

---

## 1. Plain English first

The frontend is a Next.js app with two screens:
1. **Home (`/`)** — list of businesses + a form to create one.
2. **Business workspace (`/b/[id]`)** — left: the *knowledge base* (upload documents, watch them go
   `processing → ready`); right: a *chat* with the business's AI assistant, where answers appear
   word by word, with the agent's routing decision and the sources it used.

```
frontend/src/
├── app/
│   ├── layout.tsx          header (logo + backend status dot) wrapping every page
│   ├── page.tsx            home → <BusinessList/>
│   └── b/[id]/page.tsx     workspace → <DocumentPanel/> + <ChatPanel/>
├── components/
│   ├── BackendStatus.tsx   green/red dot from GET /health
│   ├── BusinessList.tsx    list + create form
│   ├── DocumentPanel.tsx   upload, status polling, delete
│   └── ChatPanel.tsx       streaming chat, route badge, sources, history restore
└── lib/api.ts              typed API client + SSE stream parser
```

---

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

### How events update the UI (`ChatPanel.tsx`)
On send, the UI immediately adds the user's message and an **empty assistant message**, then fills
that last message as events arrive:

| Event | UI effect |
|---|---|
| `meta` | Save `thread_id` (state + `localStorage`) |
| `route` | Show badge: 📚 knowledge · searched "keratin treatment cost" |
| `sources` | Collapsible list of cited chunks with scores |
| `token` | Append text → the answer appears progressively |
| `error` | Show error inline |

The route badge and sources make the **agent's reasoning visible** — useful for debugging and a
great demo moment in an interview.

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

Ingestion runs as a background task on the server (`202 Accepted`). The document panel polls
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
