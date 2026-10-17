"use client";

import { useEffect, useState } from "react";

import { getHealth } from "@/lib/api";

type Status = "checking" | "online" | "offline";

export function BackendStatus() {
  const [status, setStatus] = useState<Status>("checking");

  useEffect(() => {
    getHealth()
      .then(() => setStatus("online"))
      .catch(() => setStatus("offline"));
  }, []);

  const color = {
    checking: "bg-yellow-400",
    online: "bg-green-500",
    offline: "bg-red-500",
  }[status];

  return (
    <div className="flex items-center gap-2 text-sm text-gray-600 dark:text-gray-300">
      <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
      Backend: {status}
    </div>
  );
}
