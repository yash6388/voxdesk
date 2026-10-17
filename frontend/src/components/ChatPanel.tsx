"use client";

import { useEffect, useRef, useState } from "react";

import { type Route, type Source, getHistory, streamChat } from "@/lib/api";

type UIMessage = {
  role: "user" | "assistant";
  content: string;
  route?: Route;
  sources?: Source[];
  error?: string;
};

const INTENT_LABELS: Record<Route["intent"], string> = {
  knowledge: "📚 knowledge",
  booking: "📅 booking",
  smalltalk: "💬 small talk",
};

// The thread id is remembered per business so a page reload continues the same conversation.
const threadKey = (businessId: string) => `voxdesk:thread:${businessId}`;

function loadThreadId(businessId: string): string | null {
  try {
    return localStorage.getItem(threadKey(businessId));
  } catch {
    return null;
  }
}

function saveThreadId(businessId: string, threadId: string | null) {
  try {
    if (threadId) localStorage.setItem(threadKey(businessId), threadId);
    else localStorage.removeItem(threadKey(businessId));
  } catch {
    // Storage unavailable (private mode etc.) — conversation just won't survive a reload.
  }
}

export function ChatPanel({ businessId }: { businessId: string }) {
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Restore the previous conversation from the server-side checkpoint.
  useEffect(() => {
    const saved = loadThreadId(businessId);
    if (!saved) return;
    setThreadId(saved);
    getHistory(businessId, saved)
      .then((h) => setMessages(h.messages))
      .catch(() => saveThreadId(businessId, null));
    return () => abortRef.current?.abort();
  }, [businessId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Apply a change to the assistant message currently being streamed (always the last one).
  const updateLast = (patch: (m: UIMessage) => UIMessage) =>
    setMessages((prev) => [...prev.slice(0, -1), patch(prev[prev.length - 1])]);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || streaming) return;

    setInput("");
    setStreaming(true);
    setMessages((prev) => [
      ...prev,
      { role: "user", content: text },
      { role: "assistant", content: "" },
    ]);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      for await (const ev of streamChat(businessId, text, threadId, controller.signal)) {
        switch (ev.event) {
          case "meta":
            setThreadId(ev.data.thread_id);
            saveThreadId(businessId, ev.data.thread_id);
            break;
          case "route":
            updateLast((m) => ({ ...m, route: ev.data }));
            break;
          case "sources":
            updateLast((m) => ({ ...m, sources: ev.data }));
            break;
          case "token":
            updateLast((m) => ({ ...m, content: m.content + ev.data.text }));
            break;
          case "error":
            updateLast((m) => ({ ...m, error: ev.data.message }));
            break;
        }
      }
    } catch (err) {
      if (!controller.signal.aborted) {
        updateLast((m) => ({ ...m, error: (err as Error).message }));
      }
    } finally {
      setStreaming(false);
    }
  }

  function newChat() {
    abortRef.current?.abort();
    saveThreadId(businessId, null);
    setThreadId(null);
    setMessages([]);
  }

  return (
    <section className="flex h-[calc(100vh-11rem)] min-h-[480px] flex-col rounded-lg border border-zinc-200 dark:border-zinc-800">
      <div className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
        <h2 className="font-medium">Chat</h2>
        <button
          onClick={newChat}
          className="text-sm text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100"
        >
          New chat
        </button>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {messages.length === 0 && (
          <p className="text-center text-sm text-zinc-500">
            Ask anything a customer might — prices, opening hours, policies…
          </p>
        )}
        {messages.map((m, i) => (
          <Message
            key={i}
            message={m}
            pending={streaming && i === messages.length - 1 && !m.content}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      <form onSubmit={send} className="flex gap-2 border-t border-zinc-200 p-3 dark:border-zinc-800">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message…"
          className="flex-1 rounded-md border border-zinc-300 bg-transparent px-3 py-2 text-sm dark:border-zinc-700"
        />
        <button
          disabled={streaming || !input.trim()}
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          Send
        </button>
      </form>
    </section>
  );
}

function Message({ message: m, pending }: { message: UIMessage; pending: boolean }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-zinc-900 px-4 py-2 text-sm text-white dark:bg-zinc-100 dark:text-zinc-900">
          {m.content}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-[85%] space-y-1.5">
      {m.route && (
        <div className="text-xs text-zinc-500">
          {INTENT_LABELS[m.route.intent]}
          {m.route.search_query && <> · searched “{m.route.search_query}”</>}
        </div>
      )}
      <div className="rounded-2xl rounded-bl-sm bg-zinc-100 px-4 py-2 text-sm dark:bg-zinc-900">
        {pending ? <span className="animate-pulse text-zinc-400">Thinking…</span> : m.content}
        {m.error && <span className="text-red-600">{m.error}</span>}
      </div>
      {m.sources && m.sources.length > 0 && (
        <details className="text-xs text-zinc-500">
          <summary className="cursor-pointer">{m.sources.length} sources</summary>
          <ol className="mt-1 space-y-1">
            {m.sources.map((s, i) => (
              <li key={i} className="rounded bg-zinc-50 p-2 dark:bg-zinc-900">
                <div className="font-medium">
                  [{i + 1}] {s.filename} · chunk {s.chunk_index} · score {s.score.toFixed(4)}
                </div>
                <div className="mt-1 line-clamp-3 whitespace-pre-line">{s.content}</div>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
