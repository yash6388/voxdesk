"use client";

import { Bot, RotateCcw, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { ConfirmCard } from "@/components/chat/ConfirmCard";
import type { UIMessage } from "@/components/chat/types";
import { type ChatEvent, type Source, getHistory, resumeChat, streamChat } from "@/lib/api";
import { BRAND_TINT, cn } from "@/lib/utils";

const SUGGESTIONS = [
  "What are your opening hours?",
  "How much does a haircut cost?",
  "Book a haircut for tomorrow afternoon",
  "What's your cancellation policy?",
];

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

export function ChatPanel({
  businessId,
  businessName,
  selectedId,
  onSelect,
}: {
  businessId: string;
  businessName: string;
  selectedId: string | null;
  onSelect: (message: UIMessage | null) => void;
}) {
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pending = messages.some((m) => m.confirmation?.state === "pending");

  // Restore the previous conversation from the server-side checkpoint.
  useEffect(() => {
    const saved = loadThreadId(businessId);
    if (!saved) return;
    setThreadId(saved);
    getHistory(businessId, saved)
      .then((h) => {
        const restored: UIMessage[] = h.messages.map((m, i) => ({ ...m, id: `history-${i}` }));
        // A confirmation was waiting when the page closed: show the card again.
        if (h.pending_confirmation) {
          restored.push({
            id: "history-pending",
            role: "assistant",
            content: "",
            confirmation: { ...h.pending_confirmation, state: "pending" },
          });
        }
        setMessages(restored);
      })
      .catch(() => saveThreadId(businessId, null));
    return () => abortRef.current?.abort();
  }, [businessId]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // Keep the inspector showing the latest version of the selected message.
  useEffect(() => {
    const selected = messages.find((m) => m.id === selectedId);
    if (selected) onSelect(selected);
  }, [messages, selectedId, onSelect]);

  /** Apply streamed events to one assistant message. Shared by new messages and resumes. */
  async function consume(events: AsyncGenerator<ChatEvent>, assistantId: string) {
    const patch = (fn: (m: UIMessage) => UIMessage) =>
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)));

    const started = performance.now();
    setStreaming(true);
    try {
      for await (const ev of events) {
        switch (ev.event) {
          case "meta":
            setThreadId(ev.data.thread_id);
            saveThreadId(businessId, ev.data.thread_id);
            break;
          case "route":
            patch((m) => ({ ...m, route: ev.data }));
            break;
          case "sources":
            patch((m) => ({ ...m, sources: ev.data }));
            break;
          case "tool_call":
            patch((m) => ({ ...m, tools: [...(m.tools ?? []), { ...ev.data }] }));
            break;
          case "tool_result":
            patch((m) => {
              // Attach the result to the first call of that tool still waiting for one.
              const tools = [...(m.tools ?? [])];
              const i = tools.findIndex((t) => t.name === ev.data.name && !t.result);
              if (i >= 0) tools[i] = { ...tools[i], result: ev.data };
              return { ...m, tools };
            });
            break;
          case "confirm":
            patch((m) => ({ ...m, confirmation: { ...ev.data, state: "pending" } }));
            break;
          case "token":
            patch((m) => ({
              ...m,
              content: m.content + ev.data.text,
              timing: {
                ...m.timing,
                firstTokenMs: m.timing?.firstTokenMs ?? performance.now() - started,
              },
            }));
            break;
          case "error":
            patch((m) => ({ ...m, error: ev.data.message }));
            break;
        }
      }
    } catch (err) {
      if (!abortRef.current?.signal.aborted) {
        patch((m) => ({ ...m, error: (err as Error).message }));
      }
    } finally {
      patch((m) => ({ ...m, timing: { ...m.timing, totalMs: performance.now() - started } }));
      setStreaming(false);
    }
  }

  function startAssistantMessage(): string {
    const id = crypto.randomUUID();
    setMessages((prev) => [...prev, { id, role: "assistant", content: "", timing: {} }]);
    onSelect({ id, role: "assistant", content: "" });
    abortRef.current = new AbortController();
    return id;
  }

  async function send(text: string) {
    text = text.trim();
    if (!text || streaming || pending) return;
    setInput("");
    setMessages((prev) => [...prev, { id: crypto.randomUUID(), role: "user", content: text }]);
    const id = startAssistantMessage();
    await consume(streamChat(businessId, text, threadId, abortRef.current!.signal), id);
  }

  /** Customer clicked Confirm/Decline on the agent's pending action. */
  async function decide(messageId: string, approved: boolean) {
    if (!threadId || streaming) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === messageId && m.confirmation
          ? { ...m, confirmation: { ...m.confirmation, state: approved ? "approved" : "declined" } }
          : m,
      ),
    );
    const id = startAssistantMessage();
    await consume(resumeChat(businessId, threadId, approved, abortRef.current!.signal), id);
  }

  function newChat() {
    abortRef.current?.abort();
    saveThreadId(businessId, null);
    setThreadId(null);
    setMessages([]);
    onSelect(null);
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <div className="flex items-center gap-3">
          <BotAvatar />
          <div>
            <div className="text-sm font-semibold">{businessName}</div>
            <div className="flex items-center gap-1.5 text-xs text-muted">
              <span className="size-1.5 rounded-full bg-emerald-500" /> AI assistant
            </div>
          </div>
        </div>
        <button
          onClick={newChat}
          className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium text-muted transition hover:bg-zinc-100 hover:text-foreground dark:hover:bg-zinc-800"
        >
          <RotateCcw className="size-3.5" /> New chat
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 space-y-5 overflow-y-auto px-5 py-6">
        {messages.length === 0 && <Welcome businessName={businessName} onPick={send} />}
        {messages.map((m, i) =>
          m.role === "user" ? (
            <UserBubble key={m.id} text={m.content} />
          ) : (
            <div key={m.id} className="space-y-3">
              {(m.content || m.error || !m.confirmation) && (
                <AssistantBubble
                  message={m}
                  selected={m.id === selectedId}
                  typing={streaming && i === messages.length - 1 && !m.content && !m.error}
                  onClick={() => onSelect(m)}
                />
              )}
              {m.confirmation && (
                <div className="pl-10">
                  <ConfirmCard
                    confirmation={m.confirmation}
                    busy={streaming}
                    onDecide={(approved) => decide(m.id, approved)}
                  />
                </div>
              )}
            </div>
          ),
        )}
      </div>

      {/* Composer */}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="border-t border-border p-4"
      >
        <div className="flex items-center gap-2 rounded-xl border border-border bg-background px-2 py-1.5 transition focus-within:border-indigo-500 focus-within:ring-4 focus-within:ring-indigo-500/10">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={pending}
            placeholder={
              pending ? "Confirm or decline the action above…" : "Ask what a customer would ask…"
            }
            className="h-9 flex-1 bg-transparent px-2 text-sm outline-none placeholder:text-zinc-400"
          />
          <button
            disabled={streaming || pending || !input.trim()}
            aria-label="Send"
            className="flex size-9 items-center justify-center rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 dark:bg-indigo-500 dark:hover:bg-indigo-400 transition disabled:opacity-40"
          >
            <Send className="size-4" />
          </button>
        </div>
      </form>
    </div>
  );
}

function BotAvatar({ small }: { small?: boolean }) {
  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full",
        BRAND_TINT,
        small ? "size-7" : "size-9",
      )}
    >
      <Bot className={small ? "size-4" : "size-5"} />
    </span>
  );
}

function Welcome({ businessName, onPick }: { businessName: string; onPick: (q: string) => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <span className={cn("flex size-14 items-center justify-center rounded-2xl", BRAND_TINT)}>
        <Bot className="size-7" />
      </span>
      <h3 className="mt-4 text-lg font-semibold">Test {businessName}’s agent</h3>
      <p className="mt-1 max-w-sm text-sm text-muted">
        Chat like a customer would. The inspector on the right shows how the agent decided.
      </p>
      <div className="mt-6 flex max-w-md flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            onClick={() => onPick(q)}
            className="rounded-full border border-border bg-surface px-3 py-1.5 text-xs transition hover:border-indigo-300 hover:text-indigo-700 dark:hover:border-indigo-500/50 dark:hover:text-indigo-300"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex animate-fade-in justify-end">
      <div className="max-w-[80%] rounded-2xl rounded-br-md bg-indigo-600 text-white dark:bg-indigo-500 px-4 py-2.5 text-sm shadow-sm">
        {text}
      </div>
    </div>
  );
}

function AssistantBubble({
  message: m,
  selected,
  typing,
  onClick,
}: {
  message: UIMessage;
  selected: boolean;
  typing: boolean;
  onClick: () => void;
}) {
  return (
    <div className="flex animate-fade-in gap-3">
      <BotAvatar small />
      <button
        onClick={onClick}
        className={cn(
          "max-w-[80%] rounded-2xl rounded-tl-md border px-4 py-2.5 text-left text-sm leading-relaxed transition",
          selected
            ? "border-indigo-300 bg-indigo-50/50 dark:border-indigo-500/40 dark:bg-indigo-500/10"
            : "border-transparent bg-zinc-100 hover:border-zinc-200 dark:bg-zinc-800/70 dark:hover:border-zinc-700",
        )}
      >
        {typing ? <TypingDots /> : <WithCitations text={m.content} sources={m.sources} />}
        {m.error && <span className="text-red-600">{m.error}</span>}
      </button>
    </div>
  );
}

function TypingDots() {
  return (
    <span className="flex h-5 items-center gap-1">
      {[0, 150, 300].map((delay) => (
        <span
          key={delay}
          style={{ animationDelay: `${delay}ms` }}
          className="size-1.5 animate-bounce rounded-full bg-zinc-400"
        />
      ))}
    </span>
  );
}

/** Render "[1]" markers in the answer as small citation chips. */
function WithCitations({ text, sources }: { text: string; sources?: Source[] }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <>
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (!match) return <span key={i}>{part}</span>;
        const source = sources?.[Number(match[1]) - 1];
        return (
          <span
            key={i}
            title={source ? `${source.filename} · chunk ${source.chunk_index}` : undefined}
            className="mx-0.5 inline-flex h-4 min-w-4 -translate-y-px items-center justify-center rounded bg-indigo-100 px-1 align-middle text-[10px] font-semibold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300"
          >
            {match[1]}
          </span>
        );
      })}
    </>
  );
}
