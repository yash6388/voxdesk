export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------- Types (mirror backend/app/schemas.py) ----------

export type HealthResponse = { status: string; environment: string };

export type ServiceHealth = {
  name: "database" | "mcp_server" | "knowledge_agent" | "booking_agent";
  status: "up" | "down";
  latency_ms: number | null;
  detail: string | null;
};
export type ServicesHealth = { status: "ok" | "degraded"; services: ServiceHealth[] };

export type User = { id: string; email: string; name: string };

export type PublicBusiness = { id: string; slug: string; name: string; description: string };

export type Business = {
  id: string;
  slug: string;
  name: string;
  description: string;
  timezone: string;
  currency: string;
  created_at: string;
};

export type Service = {
  id: string;
  name: string;
  description: string;
  duration_minutes: number;
  price: number | null;
  active: boolean;
};

export type HoursDay = { weekday: number; opens_at: string; closes_at: string };

export type Booking = {
  id: string;
  service_name: string;
  customer_name: string;
  customer_phone: string;
  start_at: string;
  end_at: string;
  status: "confirmed" | "cancelled";
  created_at: string;
};

export type DocumentStatus = "processing" | "ready" | "failed";

export type VoxDocument = {
  id: string;
  business_id: string;
  filename: string;
  content_type: string;
  status: DocumentStatus;
  num_chunks: number;
  error: string | null;
  created_at: string;
};

export type ChatMessage = { role: "user" | "assistant"; content: string };

export type Source = { filename: string; chunk_index: number; content: string; score: number };

export type Route = { intent: "knowledge" | "booking" | "smalltalk"; search_query: string };

export type ToolCall = { name: string; args: Record<string, unknown> };
/** Which specialist agent handled the turn over A2A, and the remote task's state. */
export type Delegation = {
  agent: "knowledge" | "booking";
  task_id: string;
  state: "working" | "completed" | "input-required" | "failed";
};
export type ToolResult = { name: string; status: "success" | "error"; content: string };

/** An action the agent wants to take that needs the customer's approval. */
export type PendingAction = { title: string; details: Record<string, string> };
export type Confirmation = { actions: PendingAction[] };

export type ChatEvent =
  | { event: "meta"; data: { thread_id: string } }
  | { event: "route"; data: Route }
  | { event: "sources"; data: Source[] }
  | { event: "delegation"; data: Delegation }
  | { event: "guardrail"; data: { reason: "too_long" | "prompt_injection" } }
  | { event: "tool_call"; data: ToolCall }
  | { event: "tool_result"; data: ToolResult }
  | { event: "confirm"; data: Confirmation }
  | { event: "token"; data: { text: string } }
  | { event: "error"; data: { message: string } }
  | { event: "done"; data: Record<string, never> };

// ---------- Helpers ----------

/** An API error that remembers its HTTP status (e.g. 401 → send the user to login). */
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

function errorMessage(body: { detail?: unknown }, status: number): string {
  const { detail } = body;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors: [{loc, msg, …}] → first readable message.
  if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg).replace(/^Value error, /, "");
  return `Request failed: ${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // credentials: "include" sends the httpOnly session cookie to the API.
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", credentials: "include", ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(errorMessage(body, res.status), res.status);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

// ---------- Endpoints ----------

export const getHealth = () => request<HealthResponse>("/health");

export const signup = (email: string, password: string, name: string) =>
  request<{ user: User }>("/auth/signup", json({ email, password, name }));
export const login = (email: string, password: string) =>
  request<{ user: User }>("/auth/login", json({ email, password }));
export const logout = () => request<void>("/auth/logout", { method: "POST" });
export const getMe = () => request<User>("/auth/me");

export const getPublicBusiness = (slug: string) =>
  request<PublicBusiness>(`/public/businesses/${slug}`);
export const getServicesHealth = () => request<ServicesHealth>("/health/services");

export const listBusinesses = () => request<Business[]>("/businesses");
export const getBusiness = (id: string) => request<Business>(`/businesses/${id}`);
export const createBusiness = (name: string, description: string) =>
  request<Business>("/businesses", json({ name, description }));

export const listDocuments = (businessId: string) =>
  request<VoxDocument[]>(`/businesses/${businessId}/documents`);

export const uploadDocument = (businessId: string, file: File) => {
  const form = new FormData();
  form.append("file", file);
  return request<VoxDocument>(`/businesses/${businessId}/documents`, {
    method: "POST",
    body: form,
  });
};

export const deleteDocument = (businessId: string, documentId: string) =>
  request<void>(`/businesses/${businessId}/documents/${documentId}`, { method: "DELETE" });

export const getHistory = (businessId: string, threadId: string) =>
  request<{
    thread_id: string;
    messages: ChatMessage[];
    pending_confirmation: Confirmation | null;
  }>(`/chat/${businessId}/${threadId}`);

export const listServices = (businessId: string) =>
  request<Service[]>(`/businesses/${businessId}/services`);
export const createService = (
  businessId: string,
  body: { name: string; description: string; duration_minutes: number; price: number | null },
) => request<Service>(`/businesses/${businessId}/services`, json(body));
export const setServiceActive = (businessId: string, serviceId: string, active: boolean) =>
  request<Service>(`/businesses/${businessId}/services/${serviceId}?active=${active}`, {
    method: "PATCH",
  });

export const getHours = (businessId: string) =>
  request<HoursDay[]>(`/businesses/${businessId}/hours`);
export const saveHours = (businessId: string, days: HoursDay[]) =>
  request<HoursDay[]>(`/businesses/${businessId}/hours`, { ...json({ days }), method: "PUT" });

export const listBookings = (businessId: string) =>
  request<Booking[]>(`/businesses/${businessId}/bookings`);
export const cancelBookingAsOwner = (businessId: string, bookingId: string) =>
  request<Booking>(`/businesses/${businessId}/bookings/${bookingId}/cancel`, { method: "POST" });

/** POST /chat — send a customer message and stream the reply. */
export const streamChat = (
  businessId: string,
  message: string,
  threadId: string | null,
  signal?: AbortSignal,
) => streamEvents("/chat", { business_id: businessId, message, thread_id: threadId }, signal);

/** POST /chat/resume — approve or decline the agent's pending action and stream the outcome. */
export const resumeChat = (
  businessId: string,
  threadId: string,
  approved: boolean,
  signal?: AbortSignal,
) => streamEvents("/chat/resume", { business_id: businessId, thread_id: threadId, approved }, signal);

/**
 * POST and yield Server-Sent Events as they arrive.
 * (The browser's EventSource only supports GET, so we parse the stream ourselves.)
 */
async function* streamEvents(
  path: string,
  body: unknown,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${API_URL}${path}`, { ...json(body), credentials: "include", signal });
  if (!res.ok || !res.body) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail ?? `Request failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line; keep any partial frame in the buffer.
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) yield { event, data: JSON.parse(data) } as ChatEvent;
    }
  }
}
