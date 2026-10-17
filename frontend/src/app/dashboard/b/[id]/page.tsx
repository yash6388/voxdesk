"use client";

import { FileUp } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { Inspector } from "@/components/chat/Inspector";
import type { UIMessage } from "@/components/chat/types";
import { ButtonLink } from "@/components/ui/Button";
import { Card, PageHeader } from "@/components/ui/primitives";
import { type Business, getBusiness } from "@/lib/api";
import { useDocuments } from "@/lib/useDocuments";

export default function PlaygroundPage() {
  const { id } = useParams<{ id: string }>();
  const [business, setBusiness] = useState<Business | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inspected, setInspected] = useState<UIMessage | null>(null);
  const { documents, stats } = useDocuments(id);

  useEffect(() => {
    getBusiness(id)
      .then(setBusiness)
      .catch((e: Error) => setError(e.message));
  }, [id]);

  const onSelect = useCallback((m: UIMessage | null) => setInspected(m), []);

  if (error) {
    return (
      <Card className="p-6 text-sm">
        <p className="text-red-600">{error}</p>
        <Link href="/dashboard" className="mt-2 inline-block underline">
          Back to businesses
        </Link>
      </Card>
    );
  }

  return (
    <>
      <PageHeader
        title="Playground"
        description="Talk to the agent exactly as your customers will, and see how it decides."
      />

      {documents !== null && stats.ready === 0 && (
        <Card className="mb-4 flex flex-col gap-3 border-amber-200 bg-amber-50/60 p-4 sm:flex-row sm:items-center sm:justify-between dark:border-amber-500/30 dark:bg-amber-500/10">
          <p className="text-sm">
            <span className="font-medium">No documents yet.</span>{" "}
            <span className="text-muted">The agent can only answer questions it has documents for.</span>
          </p>
          <ButtonLink href={`/dashboard/b/${id}/knowledge`} size="sm">
            <FileUp className="size-4" /> Upload documents
          </ButtonLink>
        </Card>
      )}

      <div className="grid h-[calc(100vh-13rem)] min-h-[520px] gap-4 lg:grid-cols-[1fr_340px]">
        <Card className="min-h-0 overflow-hidden">
          {business && (
            <ChatPanel
              businessId={id}
              businessName={business.name}
              selectedId={inspected?.id ?? null}
              onSelect={onSelect}
            />
          )}
        </Card>
        <Card className="hidden min-h-0 overflow-hidden lg:block">
          <Inspector message={inspected} />
        </Card>
      </div>
    </>
  );
}
