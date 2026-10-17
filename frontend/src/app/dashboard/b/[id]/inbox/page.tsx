"use client";

import { CircleCheck, Inbox, MessageSquare, Mic, UserRound } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Badge, Card, PageHeader } from "@/components/ui/primitives";
import {
  type Conversation,
  type ConversationDetail,
  type ConversationStatus,
  getConversation,
  listConversations,
  resolveConversation,
} from "@/lib/api";
import { BRAND_TINT, cn, timeAgo } from "@/lib/utils";

type Tab = "needs_human" | "all";

const STATUS: Record<ConversationStatus, { label: string; tone: "warning" | "neutral" | "success" }> = {
  needs_human: { label: "Needs a human", tone: "warning" },
  open: { label: "Handled by agent", tone: "neutral" },
  resolved: { label: "Resolved", tone: "success" },
};

/** Notify the sidebar badge that the Inbox count changed. */
const announce = () => window.dispatchEvent(new Event("voxdesk:inbox"));

export default function InboxPage() {
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<Tab>("needs_human");
  const [conversations, setConversations] = useState<Conversation[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    () =>
      listConversations(id, tab === "needs_human" ? "needs_human" : undefined)
        .then(setConversations)
        .catch((e: Error) => setError(e.message)),
    [id, tab],
  );

  useEffect(() => {
    setConversations(null);
    refresh();
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    if (!selected) return setDetail(null);
    setDetail(null);
    getConversation(id, selected)
      .then(setDetail)
      .catch((e: Error) => setError(e.message));
  }, [id, selected]);

  async function resolve(conversation: Conversation) {
    try {
      await resolveConversation(id, conversation.id);
      setDetail((d) => (d ? { ...d, status: "resolved" } : d));
      if (tab === "needs_human") setSelected(null);
      announce();
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <>
      <PageHeader
        title="Inbox"
        description="Conversations where a customer asked for a person. Follow up, then mark them resolved."
      />

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <Card className="overflow-hidden">
          <div className="flex gap-1 border-b border-border px-3 pt-3">
            {(["needs_human", "all"] as Tab[]).map((t) => (
              <button
                key={t}
                onClick={() => {
                  setTab(t);
                  setSelected(null);
                }}
                className={cn(
                  "-mb-px border-b-2 px-3 pb-2.5 text-sm font-medium transition",
                  tab === t
                    ? "border-indigo-600 text-foreground dark:border-indigo-400"
                    : "border-transparent text-muted hover:text-foreground",
                )}
              >
                {t === "needs_human" ? "Needs a human" : "All conversations"}
              </button>
            ))}
          </div>

          {conversations === null ? (
            <div className="space-y-2 p-4">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-16 animate-pulse rounded-lg bg-zinc-200/60 dark:bg-zinc-800/60" />
              ))}
            </div>
          ) : conversations.length === 0 ? (
            <div className="flex flex-col items-center px-6 py-14 text-center">
              <span className={cn("mb-3 flex size-10 items-center justify-center rounded-xl", BRAND_TINT)}>
                <Inbox className="size-5" />
              </span>
              <p className="text-sm font-medium">
                {tab === "needs_human" ? "All caught up" : "No conversations yet"}
              </p>
              <p className="mt-1 text-xs text-muted">
                {tab === "needs_human"
                  ? "When a customer asks to speak to someone, it shows up here."
                  : "Conversations from chat and voice appear here."}
              </p>
            </div>
          ) : (
            <ul className="max-h-[32rem] divide-y divide-border overflow-y-auto">
              {conversations.map((c) => (
                <li key={c.id}>
                  <button
                    onClick={() => setSelected(c.id)}
                    className={cn(
                      "flex w-full items-start gap-3 px-4 py-3 text-left transition",
                      selected === c.id
                        ? "bg-indigo-50/70 dark:bg-indigo-500/10"
                        : "hover:bg-zinc-50 dark:hover:bg-zinc-800/40",
                    )}
                  >
                    <ChannelIcon channel={c.channel} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-sm font-medium">
                          {c.status === "needs_human"
                            ? "Wants a person"
                            : `${c.turn_count} customer ${c.turn_count === 1 ? "message" : "messages"}`}
                        </span>
                        <span className="shrink-0 text-xs text-muted">{timeAgo(c.last_activity_at)}</span>
                      </div>
                      <p className="truncate text-xs text-muted">
                        {c.handoff_reason ?? c.last_message ?? "—"}
                      </p>
                      {tab === "all" && (
                        <Badge tone={STATUS[c.status].tone} className="mt-1.5">
                          {STATUS[c.status].label}
                        </Badge>
                      )}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="flex min-h-[24rem] flex-col overflow-hidden">
          {!selected ? (
            <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-muted">
              Select a conversation to read the transcript.
            </div>
          ) : !detail ? (
            <div className="space-y-3 p-5">
              {[0, 1, 2].map((i) => (
                <div key={i} className="h-12 animate-pulse rounded-lg bg-zinc-200/60 dark:bg-zinc-800/60" />
              ))}
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3 border-b border-border px-5 py-3.5">
                <ChannelIcon channel={detail.channel} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold">
                    {detail.channel === "voice" ? "Voice call" : "Text chat"} ·{" "}
                    {detail.messages.length} messages
                  </div>
                  <div className="text-xs text-muted">
                    Started {timeAgo(detail.created_at)} · last activity {timeAgo(detail.last_activity_at)}
                  </div>
                </div>
                <Badge tone={STATUS[detail.status].tone}>{STATUS[detail.status].label}</Badge>
                {detail.status === "needs_human" && (
                  <Button size="sm" onClick={() => resolve(detail)}>
                    <CircleCheck className="size-4" /> Mark resolved
                  </Button>
                )}
              </div>

              {detail.handoff_reason && (
                <div className="mx-5 mt-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-xs dark:border-amber-500/30 dark:bg-amber-500/10">
                  <UserRound className="mt-0.5 size-3.5 shrink-0 text-amber-600" />
                  <span>
                    Customer asked for a person: <span className="font-medium">“{detail.handoff_reason}”</span>
                  </span>
                </div>
              )}

              <div className="flex-1 space-y-3 overflow-y-auto p-5">
                {detail.messages.length === 0 ? (
                  <p className="text-sm text-muted">No transcript saved for this conversation.</p>
                ) : (
                  detail.messages.map((m, i) => (
                    <div key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                      <div
                        className={cn(
                          "max-w-[80%] whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm",
                          m.role === "user"
                            ? "rounded-br-md bg-indigo-600 text-white dark:bg-indigo-500"
                            : "rounded-bl-md bg-zinc-100 dark:bg-zinc-800",
                        )}
                      >
                        {m.content}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </>
          )}
        </Card>
      </div>
    </>
  );
}

function ChannelIcon({ channel }: { channel: Conversation["channel"] }) {
  const Icon = channel === "voice" ? Mic : MessageSquare;
  return (
    <span
      className={cn("flex size-8 shrink-0 items-center justify-center rounded-lg", BRAND_TINT)}
      title={channel === "voice" ? "Voice" : "Text chat"}
    >
      <Icon className="size-4" />
    </span>
  );
}
