"use client";

import { AudioWaveform, X } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { ChatPanel } from "@/components/chat/ChatPanel";
import { type PublicBusiness, getPublicBusiness } from "@/lib/api";
import { avatarGradient, cn, initials } from "@/lib/utils";

const noop = () => {};

/** The page a business shares with its customers — no account needed. */
export default function CustomerChatPage() {
  return (
    <Suspense>
      <CustomerChat />
    </Suspense>
  );
}

function CustomerChat() {
  const { slug } = useParams<{ slug: string }>();
  // ?embed=1 → running inside the website widget's iframe: compact, no page chrome.
  const embedded = useSearchParams().get("embed") === "1";
  const [business, setBusiness] = useState<PublicBusiness | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    getPublicBusiness(slug)
      .then(setBusiness)
      .catch(() => setMissing(true));
  }, [slug]);

  if (embedded) {
    return (
      <div className="flex h-screen flex-col bg-surface">
        <div className="flex items-center gap-3 border-b border-border bg-gradient-to-r from-indigo-600 to-violet-600 px-4 py-3 text-white">
          <span className="flex size-8 items-center justify-center rounded-lg bg-white/20 text-xs font-bold">
            {business ? initials(business.name) : ""}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-semibold">{business?.name ?? " "}</div>
            <div className="text-xs text-indigo-100">Typically replies instantly</div>
          </div>
          <button
            // Ask the host page's widget to close the panel.
            onClick={() => window.parent.postMessage("voxdesk:close", "*")}
            className="rounded-md p-1.5 transition hover:bg-white/15"
            aria-label="Close chat"
          >
            <X className="size-4" />
          </button>
        </div>
        <div className="min-h-0 flex-1">
          {missing ? (
            <p className="p-6 text-center text-sm text-muted">This chat isn’t available.</p>
          ) : (
            business && (
              <ChatPanel
                businessId={business.id}
                businessName={business.name}
                selectedId={null}
                onSelect={noop}
                showHeader={false}
              />
            )
          )}
        </div>
        <a
          href={`/c/${slug}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-1 border-t border-border py-1.5 text-[11px] text-muted hover:text-foreground"
        >
          <AudioWaveform className="size-3" /> Powered by VoxDesk
        </a>
      </div>
    );
  }

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
