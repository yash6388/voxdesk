"use client";

import {
  CalendarCheck,
  CircleAlert,
  Gauge,
  MessageSquare,
  MessagesSquare,
  ShieldAlert,
  UserRound,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { type BarItem, BarList, TrendChart } from "@/components/analytics/Charts";
import { ButtonLink } from "@/components/ui/Button";
import { Card, PageHeader } from "@/components/ui/primitives";
import { type Analytics, getAnalytics } from "@/lib/api";
import { BRAND_TINT, cn, formatMs } from "@/lib/utils";

const RANGES = [7, 30, 90] as const;

const OUTCOME_LABELS: Record<string, string> = {
  answered: "Answered",
  booked: "Booking made",
  booking_pending: "Awaiting confirmation",
  booking_declined: "Booking declined",
  handoff: "Handed to a human",
  guardrail: "Blocked by guardrail",
  error: "Error",
};

const INTENT_LABELS: Record<string, string> = {
  knowledge: "Questions",
  booking: "Booking",
  smalltalk: "Small talk",
  handoff: "Asked for a person",
  none: "Not routed (blocked)",
};

const CHANNEL_LABELS: Record<string, string> = { chat: "Text chat", voice: "Voice" };

const toItems = (counts: Record<string, number>, labels: Record<string, string>): BarItem[] =>
  Object.entries(counts).map(([key, value]) => ({ key, label: labels[key] ?? key, value }));

export default function AnalyticsPage() {
  const { id } = useParams<{ id: string }>();
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showTable, setShowTable] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getAnalytics(id, days)
        .then((d) => !cancelled && (setData(d), setError(null)))
        .catch((e: Error) => !cancelled && setError(e.message));
    load();
    const timer = setInterval(load, 30000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [id, days]);

  return (
    <>
      <PageHeader
        title="Analytics"
        description="How customers use your agent across text chat and voice."
        actions={
          <div className="inline-flex rounded-lg border border-border bg-surface p-0.5">
            {RANGES.map((r) => (
              <button
                key={r}
                onClick={() => setDays(r)}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm font-medium transition",
                  days === r
                    ? "bg-zinc-100 text-foreground dark:bg-zinc-800"
                    : "text-muted hover:text-foreground",
                )}
              >
                {r} days
              </button>
            ))}
          </div>
        }
      />

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {!data ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-24 animate-pulse rounded-xl bg-zinc-200/60 dark:bg-zinc-800/60" />
          ))}
        </div>
      ) : data.turns === 0 ? (
        <Card className="flex flex-col items-center px-6 py-16 text-center">
          <span className={cn("mb-4 flex size-12 items-center justify-center rounded-xl", BRAND_TINT)}>
            <MessagesSquare className="size-6" />
          </span>
          <h2 className="font-semibold">No conversations in the last {days} days</h2>
          <p className="mt-1 max-w-sm text-sm text-muted">
            Chat with your agent in the Playground or share your customer link, and numbers will
            appear here.
          </p>
          <ButtonLink href={`/dashboard/b/${id}`} className="mt-5">
            <MessageSquare className="size-4" /> Open Playground
          </ButtonLink>
        </Card>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 sm:gap-4 xl:grid-cols-3">
            <Stat
              icon={MessagesSquare}
              label="Conversations"
              value={data.conversations}
              sub={`${data.turns} messages`}
            />
            <Stat
              icon={CalendarCheck}
              label="Bookings made"
              value={data.bookings}
              sub={
                data.conversations
                  ? `${Math.round((data.bookings / data.conversations) * 100)}% of conversations`
                  : undefined
              }
            />
            <Stat
              icon={Gauge}
              label="Time to first word (p50)"
              value={data.first_token_p50_ms !== null ? formatMs(data.first_token_p50_ms) : "—"}
              sub={
                data.first_token_p95_ms !== null
                  ? `p95 ${formatMs(data.first_token_p95_ms)}`
                  : "No timed replies yet"
              }
            />
            <Stat
              icon={UserRound}
              label="Handed to a human"
              value={data.handoffs}
              sub={
                data.needs_human_open ? (
                  <Link
                    href={`/dashboard/b/${id}/inbox`}
                    className="font-medium text-indigo-600 hover:underline dark:text-indigo-400"
                  >
                    {data.needs_human_open} waiting in Inbox →
                  </Link>
                ) : (
                  "Inbox is clear"
                )
              }
            />
            <Stat
              icon={ShieldAlert}
              label="Guardrail blocks"
              value={data.guardrail_blocks}
              sub="Stopped before any model"
            />
            <Stat
              icon={CircleAlert}
              label="Errors"
              value={data.errors}
              sub={
                data.turns
                  ? `${((data.errors / data.turns) * 100).toFixed(1)}% of messages`
                  : undefined
              }
            />
          </div>

          <Card className="p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h2 className="text-sm font-semibold">Messages per day</h2>
                <p className="text-xs text-muted">Counted in the business&apos;s timezone</p>
              </div>
              <button
                onClick={() => setShowTable((v) => !v)}
                className="text-xs font-medium text-muted transition hover:text-foreground"
              >
                {showTable ? "Show chart" : "Show table"}
              </button>
            </div>
            {showTable ? (
              <div className="max-h-64 overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-surface text-left text-xs text-muted">
                    <tr>
                      <th className="py-1.5 font-medium">Date</th>
                      <th className="py-1.5 text-right font-medium">Messages</th>
                      <th className="py-1.5 text-right font-medium">Conversations</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border tabular-nums">
                    {[...data.daily].reverse().map((d) => (
                      <tr key={d.date}>
                        <td className="py-1.5">{d.date}</td>
                        <td className="py-1.5 text-right">{d.turns}</td>
                        <td className="py-1.5 text-right">{d.conversations}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <TrendChart data={data.daily} />
            )}
          </Card>

          <div className="grid gap-6 lg:grid-cols-3">
            <Panel title="Outcomes" note="What happened on each message">
              <BarList items={toItems(data.outcomes, OUTCOME_LABELS)} />
            </Panel>
            <Panel title="Intents" note="What customers asked for">
              <BarList items={toItems(data.intents, INTENT_LABELS)} />
            </Panel>
            <Panel title="Channels" note="Conversations by channel">
              <BarList items={toItems(data.channels, CHANNEL_LABELS)} />
            </Panel>
          </div>
        </div>
      )}
    </>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  sub,
}: {
  icon: React.ElementType;
  label: string;
  value: number | string;
  sub?: React.ReactNode;
}) {
  return (
    <Card className="flex items-start gap-4 p-4 sm:p-5">
      <span
        className={cn("hidden size-10 shrink-0 items-center justify-center rounded-xl sm:flex", BRAND_TINT)}
      >
        <Icon className="size-5" />
      </span>
      <div className="min-w-0">
        <div className="text-xs text-muted">{label}</div>
        <div className="text-2xl font-semibold tabular-nums">{value}</div>
        {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
      </div>
    </Card>
  );
}

function Panel({ title, note, children }: { title: string; note: string; children: React.ReactNode }) {
  return (
    <Card className="p-5">
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="mb-4 text-xs text-muted">{note}</p>
      {children}
    </Card>
  );
}
