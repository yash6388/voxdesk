"use client";

import { useCallback, useEffect, useState } from "react";

import { type VoxDocument, deleteDocument, listDocuments, uploadDocument } from "@/lib/api";

/** Documents for one business, auto-polling while any are still being ingested. */
export function useDocuments(businessId: string) {
  const [documents, setDocuments] = useState<VoxDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

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

  // Ingestion runs in the background on the server; poll only while something is processing.
  const processing = documents?.some((d) => d.status === "processing") ?? false;
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(refresh, 2000);
    return () => clearInterval(timer);
  }, [processing, refresh]);

  const upload = useCallback(
    async (files: File[]) => {
      setUploading(true);
      setError(null);
      try {
        for (const file of files) await uploadDocument(businessId, file);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setUploading(false);
        await refresh();
      }
    },
    [businessId, refresh],
  );

  const remove = useCallback(
    async (documentId: string) => {
      await deleteDocument(businessId, documentId).catch((e: Error) => setError(e.message));
      await refresh();
    },
    [businessId, refresh],
  );

  const ready = documents?.filter((d) => d.status === "ready") ?? [];
  const stats = {
    total: documents?.length ?? 0,
    ready: ready.length,
    chunks: ready.reduce((sum, d) => sum + d.num_chunks, 0),
  };

  return { documents, error, uploading, upload, remove, stats };
}
