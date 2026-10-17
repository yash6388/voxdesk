import {
  Activity,
  BookOpen,
  CalendarDays,
  CircleCheck,
  CircleX,
  Gauge,
  LoaderCircle,
  MessageSquare,
  Network,
  Plug,
  Search,
} from "lucide-react";

import type { ToolStep, UIMessage } from "@/components/chat/types";
import { Badge } from "@/components/ui/primitives";
import type { Delegation, Route } from "@/lib/api";
import { formatMs } from "@/lib/utils";

const INTENTS: Record<Route["intent"], { label: string; icon: React.ElementType; note: string }> = {
  knowledge: {
    label: "Knowledge",
    icon: BookOpen,
    note: "Delegated to the Knowledge agent → hybrid search → grounded answer",
  },
  booking: {
    label: "Booking",
    icon: CalendarDays,
    note: "Delegated to the Booking agent → MCP tools",
  },
  smalltalk: { label: "Small talk", icon: MessageSquare, note: "Answered by the supervisor itself" },
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

          {message.delegation && (
            <Section title="Agent · A2A">
              <DelegationInfo delegation={message.delegation} />
            </Section>
          )}

          {message.timing && (
            <Section title="Latency">
              <div className="grid grid-cols-2 gap-2">
                <Metric label="First token" value={message.timing.firstTokenMs} />
                <Metric label="Total" value={message.timing.totalMs} />
              </div>
            </Section>
          )}

          {message.tools && message.tools.length > 0 && (
            <Section title={`Tool calls · MCP (${message.tools.length})`}>
              <ol className="space-y-2">
                {message.tools.map((t, i) => (
                  <ToolCallItem key={i} step={t} />
                ))}
              </ol>
            </Section>
          )}

          {message.confirmation && (
            <Section title="Human in the loop">
              <p className="text-xs text-muted">
                {message.confirmation.state === "pending"
                  ? "Paused — waiting for the customer to confirm."
                  : `Customer ${message.confirmation.state} the action.`}
              </p>
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

const AGENT_NAMES: Record<Delegation["agent"], string> = {
  knowledge: "Knowledge agent",
  booking: "Booking agent",
};

const STATE_TONES: Record<Delegation["state"], "brand" | "success" | "warning" | "danger"> = {
  working: "brand",
  completed: "success",
  "input-required": "warning",
  failed: "danger",
};

function DelegationInfo({ delegation: d }: { delegation: Delegation }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-sm font-medium">
          <Network className="size-3.5 text-indigo-600 dark:text-indigo-400" />
          {AGENT_NAMES[d.agent] ?? d.agent}
        </span>
        <Badge tone={STATE_TONES[d.state] ?? "neutral"}>{d.state}</Badge>
      </div>
      {d.task_id && (
        <div className="mt-2 truncate font-mono text-[11px] text-muted">task {d.task_id}</div>
      )}
    </div>
  );
}

function ToolCallItem({ step }: { step: ToolStep }) {
  const args = Object.entries(step.args);
  const status = step.result?.status;
  return (
    <li className="rounded-lg border border-border p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-mono text-xs font-semibold">
          <Plug className="size-3 text-indigo-600 dark:text-indigo-400" />
          {step.name}
        </span>
        {status === "success" && <CircleCheck className="size-3.5 text-emerald-500" />}
        {status === "error" && <CircleX className="size-3.5 text-red-500" />}
        {!status && <LoaderCircle className="size-3.5 animate-spin text-muted" />}
      </div>
      {args.length > 0 && (
        <div className="mt-2 space-y-0.5 font-mono text-[11px] text-muted">
          {args.map(([k, v]) => (
            <div key={k} className="truncate">
              <span className="text-foreground/70">{k}</span>: {String(v)}
            </div>
          ))}
        </div>
      )}
      {step.result && (
        <p
          className={
            "mt-2 line-clamp-3 rounded bg-zinc-100 px-2 py-1 font-mono text-[11px] dark:bg-zinc-800/70 " +
            (status === "error" ? "text-red-600" : "text-muted")
          }
        >
          {step.result.content}
        </p>
      )}
    </li>
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
