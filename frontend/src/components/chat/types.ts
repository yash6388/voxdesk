import type { Confirmation, Delegation, Route, Source, ToolCall, ToolResult } from "@/lib/api";

export type ToolStep = ToolCall & { result?: ToolResult };

export type UIMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  route?: Route;
  sources?: Source[];
  /** Link to this turn's trace in Langfuse (when tracing is configured). */
  traceUrl?: string;
  /** Set when an input guardrail blocked the message before any LLM saw it. */
  guardrail?: string;
  /** Set when the agent flagged this conversation for a human (it appears in the Inbox). */
  handoff?: string;
  /** The A2A agent this reply came from (latest state of its task). */
  delegation?: Delegation;
  /** MCP tool calls the booking agent made during this reply. */
  tools?: ToolStep[];
  /** An action awaiting the customer's approval, and what they decided. */
  confirmation?: Confirmation & { state: "pending" | "approved" | "declined" };
  error?: string;
  /** Client-measured timings for this turn (only for messages sent in this session). */
  timing?: { firstTokenMs?: number; totalMs?: number };
};
