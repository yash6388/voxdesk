"use client";

import { useEffect, useState } from "react";

import { type ServiceHealth, getServicesHealth } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAMES: Record<ServiceHealth["name"], string> = {
  database: "Database",
  mcp_server: "Booking tools (MCP)",
  knowledge_agent: "Knowledge agent",
  booking_agent: "Booking agent",
};

type Overall = "checking" | "ok" | "degraded" | "offline";

const LABELS: Record<Overall, string> = {
  checking: "Connecting…",
  ok: "All systems operational",
  degraded: "Some services down",
  offline: "API offline",
};

const DOT: Record<Overall, string> = {
  checking: "bg-amber-400",
  ok: "bg-emerald-500",
  degraded: "bg-amber-500",
  offline: "bg-red-500",
};

/** Sidebar status: API + every service it depends on (from GET /health/services). */
export function BackendStatus() {
  const [overall, setOverall] = useState<Overall>("checking");
  const [services, setServices] = useState<ServiceHealth[]>([]);

  useEffect(() => {
    const check = () =>
      getServicesHealth()
        .then((h) => {
          setServices(h.services);
          setOverall(h.status);
        })
        .catch(() => {
          setServices([]);
          setOverall("offline");
        });
    check();
    const timer = setInterval(check, 15000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="group relative">
      <div className="flex cursor-default items-center gap-2 text-xs text-muted">
        <span className="relative flex size-2">
          {overall === "ok" && (
            <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-60" />
          )}
          <span className={cn("relative inline-flex size-2 rounded-full", DOT[overall])} />
        </span>
        {LABELS[overall]}
      </div>

      {services.length > 0 && (
        <div className="invisible absolute bottom-full left-0 z-20 mb-2 w-60 rounded-xl border border-border bg-surface p-3 opacity-0 shadow-lg transition group-hover:visible group-hover:opacity-100">
          <div className="mb-2 text-xs font-semibold">Services</div>
          <ul className="space-y-1.5">
            {services.map((s) => (
              <li key={s.name} className="flex items-center justify-between gap-2 text-xs">
                <span className="flex items-center gap-2">
                  <span
                    className={cn(
                      "size-1.5 rounded-full",
                      s.status === "up" ? "bg-emerald-500" : "bg-red-500",
                    )}
                  />
                  {NAMES[s.name] ?? s.name}
                </span>
                <span className="font-mono text-muted">
                  {s.status === "up" ? `${Math.round(s.latency_ms ?? 0)} ms` : "down"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
