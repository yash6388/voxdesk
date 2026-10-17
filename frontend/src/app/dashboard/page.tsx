"use client";

import { ArrowRight, Building2, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Card, Input, Label, PageHeader, Textarea } from "@/components/ui/primitives";
import { type Business, createBusiness, listBusinesses } from "@/lib/api";
import { avatarGradient, cn, formatDate, initials } from "@/lib/utils";

export default function BusinessesPage() {
  const [businesses, setBusinesses] = useState<Business[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    listBusinesses()
      .then(setBusinesses)
      .catch((e: Error) => setError(e.message));
  }, []);

  return (
    <>
      <PageHeader
        title="Businesses"
        description="Each business gets its own AI agent, knowledge base and conversations."
        actions={
          <Button onClick={() => setCreating(true)}>
            <Plus className="size-4" /> New business
          </Button>
        }
      />

      {error && (
        <Card className="border-red-200 p-4 text-sm text-red-600 dark:border-red-900">
          Couldn’t load businesses: {error}. Is the API running?
        </Card>
      )}

      {businesses === null && !error && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-36 animate-pulse rounded-xl bg-zinc-200/60 dark:bg-zinc-800/60" />
          ))}
        </div>
      )}

      {businesses?.length === 0 && <EmptyState onCreate={() => setCreating(true)} />}

      {businesses && businesses.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {businesses.map((b, i) => (
            <Link
              key={b.id}
              href={`/dashboard/b/${b.id}`}
              style={{ animationDelay: `${i * 50}ms` }}
              className="group animate-fade-in rounded-xl border border-border bg-surface p-5 shadow-sm transition hover:-translate-y-0.5 hover:border-indigo-300 hover:shadow-lg hover:shadow-indigo-500/5 dark:hover:border-indigo-500/40"
            >
              <div className="flex items-start justify-between">
                <span
                  className={cn(
                    "flex size-11 items-center justify-center rounded-xl bg-gradient-to-br text-sm font-bold text-white shadow-sm",
                    avatarGradient(b.name),
                  )}
                >
                  {initials(b.name)}
                </span>
                <ArrowRight className="size-4 text-muted opacity-0 transition group-hover:translate-x-0.5 group-hover:opacity-100" />
              </div>
              <h3 className="mt-4 font-semibold">{b.name}</h3>
              <p className="mt-1 line-clamp-2 min-h-10 text-sm text-muted">
                {b.description || "No description"}
              </p>
              <p className="mt-3 text-xs text-muted">Created {formatDate(b.created_at)}</p>
            </Link>
          ))}
        </div>
      )}

      <CreateBusinessDialog open={creating} onClose={() => setCreating(false)} />
    </>
  );
}

function EmptyState({ onCreate }: { onCreate: () => void }) {
  return (
    <Card className="flex flex-col items-center px-6 py-16 text-center">
      <span className="flex size-14 items-center justify-center rounded-2xl bg-gradient-to-br from-indigo-500/10 to-violet-500/10 text-indigo-600 dark:text-indigo-400">
        <Building2 className="size-7" />
      </span>
      <h3 className="mt-5 text-lg font-semibold">Create your first business</h3>
      <p className="mt-2 max-w-sm text-sm text-muted">
        Add a business, upload its documents, and its AI agent can start answering customers.
      </p>
      <Button onClick={onCreate} className="mt-6">
        <Plus className="size-4" /> New business
      </Button>
    </Card>
  );
}

function CreateBusinessDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const business = await createBusiness(name.trim(), description.trim());
      // New businesses start empty, so go straight to uploading documents.
      router.push(`/dashboard/b/${business.id}/knowledge`);
    } catch (err) {
      setError((err as Error).message);
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New business"
      description="You can upload documents for its knowledge base next."
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <Label htmlFor="name">Business name</Label>
          <Input
            id="name"
            required
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Glow Studio Salon"
          />
        </div>
        <div>
          <Label htmlFor="description">Description</Label>
          <Textarea
            id="description"
            rows={3}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="A hair and beauty salon in Koregaon Park, Pune."
          />
          <p className="mt-1.5 text-xs text-muted">The agent uses this to introduce itself.</p>
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <div className="flex justify-end gap-2 pt-2">
          <Button type="button" variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={saving || !name.trim()}>{saving ? "Creating…" : "Create business"}</Button>
        </div>
      </form>
    </Dialog>
  );
}
