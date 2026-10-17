"use client";

import { X } from "lucide-react";
import { useEffect } from "react";

export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-zinc-950/40 backdrop-blur-sm" onClick={onClose} />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative w-full max-w-md animate-fade-in rounded-2xl border border-border bg-surface p-6 shadow-2xl"
      >
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-md p-1 text-muted hover:bg-zinc-100 dark:hover:bg-zinc-800"
          aria-label="Close"
        >
          <X className="size-4" />
        </button>
        <h2 className="text-lg font-semibold">{title}</h2>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
        <div className="mt-5">{children}</div>
      </div>
    </div>
  );
}
