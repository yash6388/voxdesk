export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------- Types (mirror backend/app/schemas.py) ----------

export type HealthResponse = { status: string; environment: string };

export type Business = {
  id: string;
  name: string;
  description: string;
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

export type ChatEvent =
  | { event: "meta"; data: { thread_id: string } }
  | { event: "route"; data: Route }
  | { event: "sources"; data: Source[] }
  | { event: "token"; data: { text: string } }
  | { event: "error"; data: { message: string } }
  | { event: "done"; data: Record<string, never> };

// ---------- Helpers ----------

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store", ...init });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${res.status}`);
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
  request<{ thread_id: string; messages: ChatMessage[] }>(`/chat/${businessId}/${threadId}`);

/**
 * POST /chat and yield Server-Sent Events as they arrive.
 * (The browser's EventSource only supports GET, so we parse the stream ourselves.)
 */
export async function* streamChat(
  businessId: string,
  message: string,
  threadId: string | null,
  signal?: AbortSignal,
): AsyncGenerator<ChatEvent> {
  const res = await fetch(`${API_URL}/chat`, {
    ...json({ business_id: businessId, message, thread_id: threadId }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`Chat failed: ${res.status}`);

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
