"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ChatPanel } from "@/components/ChatPanel";
import { DocumentPanel } from "@/components/DocumentPanel";
import { type Business, getBusiness } from "@/lib/api";

export default function BusinessPage() {
  const { id } = useParams<{ id: string }>();
  const [business, setBusiness] = useState<Business | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBusiness(id)
      .then(setBusiness)
      .catch((e: Error) => setError(e.message));
  }, [id]);

  if (error) {
    return (
      <p className="text-red-600">
        {error} · <Link href="/" className="underline">Back</Link>
      </p>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          ← All businesses
        </Link>
        <h1 className="mt-1 text-2xl font-semibold">{business?.name ?? "…"}</h1>
        {business?.description && <p className="text-zinc-500">{business.description}</p>}
      </div>
      <div className="grid gap-4 md:grid-cols-[320px_1fr]">
        <DocumentPanel businessId={id} />
        <ChatPanel businessId={id} />
      </div>
    </div>
  );
}
