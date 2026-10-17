"use client";

import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";
import { cn } from "@/lib/utils";

type Status = "checking" | "online" | "offline";

const LABELS: Record<Status, string> = {
  checking: "Connecting…",
  online: "API online",
  offline: "API offline",
};

export function BackendStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    const check = () =>
      getHealth()
        .then(() => setStatus("online"))
        .catch(() => setStatus("offline"));
    check();
    const timer = setInterval(check, 15000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="relative flex size-2">
        {status === "online" && (
          <span className="absolute inline-flex size-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        )}
        <span
          className={cn(
            "relative inline-flex size-2 rounded-full",
            status === "online" && "bg-emerald-500",
            status === "offline" && "bg-red-500",
            status === "checking" && "bg-amber-400",
          )}
        />
      </span>
      {LABELS[status]}
    </div>
  );
}
