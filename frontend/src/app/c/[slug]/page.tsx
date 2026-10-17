"use client";

import { AudioWaveform } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { type PublicBusiness, getPublicBusiness } from "@/lib/api";
import { avatarGradient, cn, initials } from "@/lib/utils";

const noop = () => {};

/** The page a business shares with its customers — no account needed. */
export default function CustomerChatPage() {
  const { slug } = useParams<{ slug: string }>();
  const [business, setBusiness] = useState<PublicBusiness | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    getPublicBusiness(slug)
      .then(setBusiness)
      .catch(() => setMissing(true));
  }, [slug]);

  if (missing) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-2 px-4 text-center">
        <h1 className="text-xl font-semibold">This page doesn’t exist</h1>
        <p className="text-sm text-muted">Check the link you were given.</p>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen flex-col items-center px-4 py-6 sm:py-10">
      <div className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-72 bg-gradient-to-b from-indigo-500/10 to-transparent" />

      <header className="mb-6 flex w-full max-w-2xl items-center gap-3">
        {business ? (
          <span
            className={cn(
              "flex size-11 items-center justify-center rounded-xl bg-gradient-to-br text-sm font-bold text-white shadow-sm",
              avatarGradient(business.name),
            )}
          >
            {initials(business.name)}
          </span>
        ) : (
          <span className="size-11 animate-pulse rounded-xl bg-zinc-200 dark:bg-zinc-800" />
        )}
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold">{business?.name ?? " "}</h1>
          <p className="truncate text-sm text-muted">
            {business?.description || "Ask us anything, or book an appointment."}
          </p>
        </div>
      </header>

      <div className="h-[calc(100vh-11rem)] min-h-[480px] w-full max-w-2xl overflow-hidden rounded-2xl border border-border bg-surface shadow-xl shadow-indigo-500/5">
        {business && (
          <ChatPanel
            businessId={business.id}
            businessName={business.name}
            selectedId={null}
            onSelect={noop}
          />
        )}
      </div>

      <Link
        href="/"
        className="mt-4 flex items-center gap-1.5 text-xs text-muted transition hover:text-foreground"
      >
        <AudioWaveform className="size-3.5" /> Powered by VoxDesk
      </Link>
    </div>
  );
}
