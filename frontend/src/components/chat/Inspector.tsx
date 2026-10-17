import { Activity, BookOpen, CalendarDays, Gauge, MessageSquare, Search } from "lucide-react";

import type { UIMessage } from "@/components/chat/types";
import { Badge } from "@/components/ui/primitives";
import type { Route } from "@/lib/api";
import { formatMs } from "@/lib/utils";

const INTENTS: Record<Route["intent"], { label: string; icon: React.ElementType; note: string }> = {
  knowledge: {
    label: "Knowledge",
    icon: BookOpen,
    note: "Routed to retrieval → grounded answer",
  },
  booking: { label: "Booking", icon: CalendarDays, note: "Routed to the booking flow" },
  smalltalk: { label: "Small talk", icon: MessageSquare, note: "Answered directly, no retrieval" },
};

/** Shows how the agent handled one turn: routing decision, rewritten query, sources, latency. */
export function Inspector({ message }: { message: UIMessage | null }) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-border px-5 py-3.5 text-sm font-semibold">
        <Activity className="size-4 text-indigo-600 dark:text-indigo-400" /> Agent inspector
      </div>

      {!message ? (
        <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-muted">
          Send a message, or click any reply, to see how the agent handled it.
        </div>
      ) : (
        <div className="flex-1 space-y-6 overflow-y-auto p-5">
          <Section title="Route">
            {message.route ? (
              <RouteInfo route={message.route} />
            ) : (
              <p className="text-sm text-muted">
                {message.id.startsWith("history") ? "Not recorded for earlier messages." : "Waiting…"}
              </p>
            )}
          </Section>

          {message.timing && (
            <Section title="Latency">
              <div className="grid grid-cols-2 gap-2">
                <Metric label="First token" value={message.timing.firstTokenMs} />
                <Metric label="Total" value={message.timing.totalMs} />
              </div>
            </Section>
          )}

          {message.sources && (
            <Section title={`Sources (${message.sources.length})`}>
              <ol className="space-y-2">
                {message.sources.map((s, i) => (
                  <li key={i} className="rounded-lg border border-border p-3">
                    <div className="flex items-center justify-between gap-2 text-xs">
                      <span className="flex min-w-0 items-center gap-1.5 font-medium">
                        <span className="flex size-4 shrink-0 items-center justify-center rounded bg-indigo-100 text-[10px] font-semibold text-indigo-700 dark:bg-indigo-500/20 dark:text-indigo-300">
                          {i + 1}
                        </span>
                        <span className="truncate">{s.filename}</span>
                      </span>
                      <span className="shrink-0 font-mono text-muted">{s.score.toFixed(4)}</span>
                    </div>
                    <p className="mt-2 line-clamp-4 whitespace-pre-line text-xs leading-relaxed text-muted">
                      {s.content}
                    </p>
                  </li>
                ))}
              </ol>
            </Section>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">{title}</h4>
      {children}
    </section>
  );
}

function RouteInfo({ route }: { route: Route }) {
  const { label, icon: Icon, note } = INTENTS[route.intent];
  return (
    <div className="space-y-2">
      <Badge tone="brand">
        <Icon className="size-3" /> {label}
      </Badge>
      <p className="text-xs text-muted">{note}</p>
      {route.search_query && (
        <div className="flex items-start gap-2 rounded-lg bg-zinc-100 px-3 py-2 text-xs dark:bg-zinc-800/70">
          <Search className="mt-0.5 size-3 shrink-0 text-muted" />
          <span>
            <span className="text-muted">Search query: </span>
            {route.search_query}
          </span>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }: { label: string; value?: number }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="flex items-center gap-1 text-xs text-muted">
        <Gauge className="size-3" /> {label}
      </div>
      <div className="mt-1 font-mono text-sm font-semibold">
        {value === undefined ? "—" : formatMs(value)}
      </div>
    </div>
  );
}
