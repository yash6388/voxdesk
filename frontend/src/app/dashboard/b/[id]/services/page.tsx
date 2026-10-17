"use client";

import { Clock, LoaderCircle, Plus, Scissors } from "lucide-react";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/Button";
import { Switch } from "@/components/ui/Switch";
import { Badge, Card, Input, Label, PageHeader } from "@/components/ui/primitives";
import {
  type HoursDay,
  type Service,
  createService,
  getBusiness,
  getHours,
  listServices,
  saveHours,
  setServiceActive,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

export default function ServicesPage() {
  const { id } = useParams<{ id: string }>();
  return (
    <>
      <PageHeader
        title="Services & hours"
        description="What customers can book, and when. The booking agent only offers times that fit."
      />
      <div className="grid gap-6 xl:grid-cols-[1fr_420px]">
        <ServicesCard businessId={id} />
        <HoursCard businessId={id} />
      </div>
    </>
  );
}

// ---------- Services ----------

function ServicesCard({ businessId }: { businessId: string }) {
  const [services, setServices] = useState<Service[] | null>(null);
  const [currency, setCurrency] = useState("INR");
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ name: "", duration: "30", price: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    listServices(businessId).then(setServices).catch((e: Error) => setError(e.message));
    getBusiness(businessId).then((b) => setCurrency(b.currency)).catch(() => {});
  }, [businessId]);

  async function onAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const created = await createService(businessId, {
        name: form.name.trim(),
        description: "",
        duration_minutes: Number(form.duration),
        price: form.price ? Number(form.price) : null,
      });
      setServices((prev) => [...(prev ?? []), created].sort((a, b) => a.name.localeCompare(b.name)));
      setForm({ name: "", duration: "30", price: "" });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function toggle(service: Service) {
    const updated = await setServiceActive(businessId, service.id, !service.active).catch(
      (e: Error) => {
        setError(e.message);
        return null;
      },
    );
    if (updated) setServices((prev) => prev?.map((s) => (s.id === updated.id ? updated : s)) ?? null);
  }

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-border px-5 py-3.5">
        <Scissors className="size-4 text-indigo-600 dark:text-indigo-400" />
        <h2 className="text-sm font-semibold">Services</h2>
      </div>

      <form onSubmit={onAdd} className="grid gap-3 border-b border-border p-5 sm:grid-cols-[1fr_120px_120px_auto] sm:items-end">
        <div>
          <Label htmlFor="svc-name">Name</Label>
          <Input
            id="svc-name"
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Women's haircut"
          />
        </div>
        <div>
          <Label htmlFor="svc-duration">Minutes</Label>
          <Input
            id="svc-duration"
            type="number"
            min={5}
            max={480}
            step={5}
            required
            value={form.duration}
            onChange={(e) => setForm({ ...form, duration: e.target.value })}
          />
        </div>
        <div>
          <Label htmlFor="svc-price">Price ({currency})</Label>
          <Input
            id="svc-price"
            type="number"
            min={0}
            value={form.price}
            onChange={(e) => setForm({ ...form, price: e.target.value })}
            placeholder="Optional"
          />
        </div>
        <Button disabled={saving || !form.name.trim()}>
          {saving ? <LoaderCircle className="size-4 animate-spin" /> : <Plus className="size-4" />}
          Add
        </Button>
      </form>
      {error && <p className="px-5 pt-3 text-sm text-red-600">{error}</p>}

      {services === null ? (
        <div className="space-y-2 p-5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded-lg bg-zinc-200/60 dark:bg-zinc-800/60" />
          ))}
        </div>
      ) : services.length === 0 ? (
        <p className="px-5 py-10 text-center text-sm text-muted">
          No services yet. Add what customers can book above.
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {services.map((s) => (
            <li key={s.id} className={cn("flex items-center gap-4 px-5 py-3", !s.active && "opacity-50")}>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{s.name}</div>
                <div className="text-xs text-muted">
                  {s.duration_minutes} min
                  {s.price !== null && ` · ${currency} ${s.price.toLocaleString()}`}
                </div>
              </div>
              {!s.active && <Badge>Hidden</Badge>}
              <Switch checked={s.active} onChange={() => toggle(s)} label={`Offer ${s.name}`} />
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ---------- Opening hours ----------

type DayRow = { open: boolean; opens: string; closes: string };

function HoursCard({ businessId }: { businessId: string }) {
  const [rows, setRows] = useState<DayRow[] | null>(null);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    getHours(businessId)
      .then((hours) => {
        const byDay = new Map(hours.map((h) => [h.weekday, h]));
        setRows(
          DAYS.map((_, i) => {
            const h = byDay.get(i);
            return h
              ? { open: true, opens: h.opens_at.slice(0, 5), closes: h.closes_at.slice(0, 5) }
              : { open: false, opens: "10:00", closes: "18:00" };
          }),
        );
      })
      .catch((e: Error) => setMessage({ ok: false, text: e.message }));
  }, [businessId]);

  const update = (i: number, patch: Partial<DayRow>) =>
    setRows((prev) => prev?.map((r, j) => (j === i ? { ...r, ...patch } : r)) ?? null);

  async function onSave() {
    if (!rows) return;
    setSaving(true);
    setMessage(null);
    const days: HoursDay[] = rows
      .map((r, i) => ({ weekday: i, opens_at: r.opens, closes_at: r.closes, open: r.open }))
      .filter((d) => d.open)
      .map(({ weekday, opens_at, closes_at }) => ({ weekday, opens_at, closes_at }));
    try {
      await saveHours(businessId, days);
      setMessage({ ok: true, text: "Opening hours saved." });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="h-fit overflow-hidden">
      <div className="flex items-center gap-2 border-b border-border px-5 py-3.5">
        <Clock className="size-4 text-indigo-600 dark:text-indigo-400" />
        <h2 className="text-sm font-semibold">Opening hours</h2>
      </div>
      <div className="space-y-1 p-3">
        {rows === null
          ? DAYS.map((d) => (
              <div key={d} className="h-11 animate-pulse rounded-lg bg-zinc-200/60 dark:bg-zinc-800/60" />
            ))
          : rows.map((r, i) => (
              <div
                key={DAYS[i]}
                className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-zinc-50 dark:hover:bg-zinc-800/40"
              >
                <Switch
                  checked={r.open}
                  onChange={() => update(i, { open: !r.open })}
                  label={`Open on ${DAYS[i]}`}
                />
                <span className="w-24 text-sm font-medium">{DAYS[i]}</span>
                {r.open ? (
                  <div className="flex items-center gap-2 text-sm">
                    <TimeInput value={r.opens} onChange={(v) => update(i, { opens: v })} />
                    <span className="text-muted">–</span>
                    <TimeInput value={r.closes} onChange={(v) => update(i, { closes: v })} />
                  </div>
                ) : (
                  <span className="text-sm text-muted">Closed</span>
                )}
              </div>
            ))}
      </div>
      <div className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
        <span className={cn("text-sm", message?.ok ? "text-emerald-600" : "text-red-600")}>
          {message?.text}
        </span>
        <Button size="sm" onClick={onSave} disabled={saving || rows === null}>
          {saving ? "Saving…" : "Save hours"}
        </Button>
      </div>
    </Card>
  );
}

function TimeInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <input
      type="time"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-8 rounded-md border border-border bg-surface px-2 text-sm outline-none focus:border-indigo-500"
    />
  );
}
