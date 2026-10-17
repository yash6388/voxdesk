import type { Route, Source } from "@/lib/api";

export type UIMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  route?: Route;
  sources?: Source[];
  error?: string;
  /** Client-measured timings for this turn (only for messages sent in this session). */
  timing?: { firstTokenMs?: number; totalMs?: number };
};
