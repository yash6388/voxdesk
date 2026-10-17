"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { type VoxDocument, deleteDocument, listDocuments, uploadDocument } from "@/lib/api";

const STATUS_STYLES: Record<VoxDocument["status"], string> = {
  processing: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
  ready: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
};

export function DocumentPanel({ businessId }: { businessId: string }) {
  const [documents, setDocuments] = useState<VoxDocument[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const refresh = useCallback(
    () =>
      listDocuments(businessId)
        .then(setDocuments)
        .catch((e: Error) => setError(e.message)),
    [businessId],
  );

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Ingestion runs in the background on the server; poll while anything is processing.
  const processing = documents.some((d) => d.status === "processing");
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [processing, refresh]);

  async function onUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of files) await uploadDocument(businessId, file);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function onDelete(id: string) {
    await deleteDocument(businessId, id).catch((e: Error) => setError(e.message));
    await refresh();
  }

  return (
    <section className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-medium">Knowledge base</h2>
        <label className="cursor-pointer rounded-md border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900">
          {uploading ? "Uploading…" : "Upload"}
          <input
            ref={fileInput}
            type="file"
            multiple
            accept=".pdf,.txt,.md"
            onChange={onUpload}
            disabled={uploading}
            className="hidden"
          />
        </label>
      </div>
      <p className="mb-3 text-xs text-zinc-500">PDF, TXT or Markdown — prices, hours, policies, FAQs.</p>

      {documents.length === 0 && (
        <p className="text-sm text-zinc-500">No documents yet.</p>
      )}
      <ul className="space-y-2">
        {documents.map((d) => (
          <li
            key={d.id}
            className="flex items-start justify-between gap-2 rounded-md bg-zinc-50 px-3 py-2 text-sm dark:bg-zinc-900"
          >
            <div className="min-w-0">
              <div className="truncate font-medium">{d.filename}</div>
              <div className="mt-1 flex items-center gap-2 text-xs text-zinc-500">
                <span className={`rounded px-1.5 py-0.5 ${STATUS_STYLES[d.status]}`}>
                  {d.status}
                </span>
                {d.status === "ready" && <span>{d.num_chunks} chunks</span>}
              </div>
              {d.error && <div className="mt-1 text-xs text-red-600">{d.error}</div>}
            </div>
            <button
              onClick={() => onDelete(d.id)}
              className="text-xs text-zinc-400 hover:text-red-600"
              aria-label={`Delete ${d.filename}`}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
      {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
    </section>
  );
}
