"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { type Business, createBusiness, listBusinesses } from "@/lib/api";

export function BusinessList() {
  const [businesses, setBusinesses] = useState<Business[] | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    listBusinesses()
      .then(setBusinesses)
      .catch((e: Error) => setError(e.message));
  }, []);

  async function onCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const business = await createBusiness(name.trim(), description.trim());
      setBusinesses((prev) => [business, ...(prev ?? [])]);
      setName("");
      setDescription("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="grid gap-8 md:grid-cols-[1fr_320px]">
      <section>
        <h2 className="mb-3 text-sm font-medium uppercase tracking-wide text-zinc-500">
          Businesses
        </h2>
        {businesses === null && !error && <p className="text-zinc-500">Loading…</p>}
        {businesses?.length === 0 && (
          <p className="text-zinc-500">No businesses yet — create one to get started.</p>
        )}
        <ul className="grid gap-3">
          {businesses?.map((b) => (
            <li key={b.id}>
              <Link
                href={`/b/${b.id}`}
                className="block rounded-lg border border-zinc-200 p-4 transition hover:border-zinc-400 dark:border-zinc-800 dark:hover:border-zinc-600"
              >
                <div className="font-medium">{b.name}</div>
                {b.description && (
                  <div className="mt-1 text-sm text-zinc-500">{b.description}</div>
                )}
              </Link>
            </li>
          ))}
        </ul>
      </section>

      <form
        onSubmit={onCreate}
        className="h-fit space-y-3 rounded-lg border border-zinc-200 p-4 dark:border-zinc-800"
      >
        <h2 className="font-medium">New business</h2>
        <input
          required
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Name, e.g. Glow Studio Salon"
          className="w-full rounded-md border border-zinc-300 bg-transparent px-3 py-2 text-sm dark:border-zinc-700"
        />
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Short description (helps the assistant introduce itself)"
          rows={3}
          className="w-full rounded-md border border-zinc-300 bg-transparent px-3 py-2 text-sm dark:border-zinc-700"
        />
        <button
          disabled={saving || !name.trim()}
          className="w-full rounded-md bg-zinc-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-zinc-100 dark:text-zinc-900"
        >
          {saving ? "Creating…" : "Create"}
        </button>
        {error && <p className="text-sm text-red-600">{error}</p>}
      </form>
    </div>
  );
}
