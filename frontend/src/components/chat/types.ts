import type { Confirmation, Route, Source, ToolCall, ToolResult } from "@/lib/api";

export type ToolStep = ToolCall & { result?: ToolResult };

export type UIMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  route?: Route;
  sources?: Source[];
  /** MCP tool calls the booking agent made during this reply. */
  tools?: ToolStep[];
  /** An action awaiting the customer's approval, and what they decided. */
  confirmation?: Confirmation & { state: "pending" | "approved" | "declined" };
  error?: string;
  /** Client-measured timings for this turn (only for messages sent in this session). */
  timing?: { firstTokenMs?: number; totalMs?: number };
};
