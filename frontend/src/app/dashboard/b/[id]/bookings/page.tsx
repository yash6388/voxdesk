"use client";

import { CalendarCheck, CalendarDays, CalendarX, MessageSquare } from "lucide-react";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ButtonLink } from "@/components/ui/Button";
import { Badge, Card, PageHeader } from "@/components/ui/primitives";
import { type Booking, cancelBookingAsOwner, getBusiness, listBookings } from "@/lib/api";
import { BRAND_TINT, cn } from "@/lib/utils";

type Tab = "upcoming" | "past";

export default function BookingsPage() {
  const { id } = useParams<{ id: string }>();
  const [bookings, setBookings] = useState<Booking[] | null>(null);
  const [timezone, setTimezone] = useState<string | undefined>();
  const [tab, setTab] = useState<Tab>("upcoming");
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(
    () =>
      listBookings(id)
        .then(setBookings)
        .catch((e: Error) => setError(e.message)),
    [id],
  );

  useEffect(() => {
    refresh();
    getBusiness(id).then((b) => setTimezone(b.timezone)).catch(() => {});
    // Bookings arrive from the agent at any time; keep the list fresh.
    const timer = setInterval(refresh, 10000);
    return () => clearInterval(timer);
  }, [id, refresh]);

  const now = Date.now();
  const upcoming = (bookings ?? [])
    .filter((b) => b.status === "confirmed" && new Date(b.end_at).getTime() > now)
    .sort((a, b) => a.start_at.localeCompare(b.start_at));
  const past = (bookings ?? []).filter((b) => !upcoming.includes(b));
  const today = upcoming.filter((b) => sameDay(b.start_at, timezone));
  const shown = tab === "upcoming" ? upcoming : past;

  async function cancel(booking: Booking) {
    if (!confirm(`Cancel ${booking.customer_name}'s ${booking.service_name}?`)) return;
    await cancelBookingAsOwner(id, booking.id).catch((e: Error) => setError(e.message));
    await refresh();
  }

  return (
    <>
      <PageHeader
        title="Bookings"
        description="Appointments your agent has booked. Updates automatically."
        actions={
          <ButtonLink href={`/dashboard/b/${id}`} variant="secondary">
            <MessageSquare className="size-4" /> Book via Playground
          </ButtonLink>
        }
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Stat icon={CalendarDays} label="Today" value={today.length} />
        <Stat icon={CalendarCheck} label="Upcoming" value={upcoming.length} />
        <Stat
          icon={CalendarX}
          label="Cancelled"
          value={(bookings ?? []).filter((b) => b.status === "cancelled").length}
        />
      </div>

      <Card className="overflow-hidden">
        <div className="flex gap-1 border-b border-border px-3 pt-3">
          {(["upcoming", "past"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "-mb-px border-b-2 px-3 pb-2.5 text-sm font-medium capitalize transition",
                tab === t
                  ? "border-indigo-600 text-foreground dark:border-indigo-400"
                  : "border-transparent text-muted hover:text-foreground",
              )}
            >
              {t === "past" ? "Past & cancelled" : "Upcoming"}
            </button>
          ))}
        </div>

        {error && <p className="px-5 pt-3 text-sm text-red-600">{error}</p>}

        {bookings === null ? (
          <div className="space-y-2 p-5">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-14 animate-pulse rounded-lg bg-zinc-200/60 dark:bg-zinc-800/60" />
            ))}
          </div>
        ) : shown.length === 0 ? (
          <p className="px-5 py-12 text-center text-sm text-muted">
            {tab === "upcoming"
              ? "No upcoming bookings yet. Try booking one in the Playground."
              : "Nothing here yet."}
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {shown.map((b) => (
              <li key={b.id} className="flex flex-wrap items-center gap-4 px-5 py-3.5">
                <DateBadge iso={b.start_at} timezone={timezone} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{b.service_name}</div>
                  <div className="text-xs text-muted">
                    {formatTime(b.start_at, timezone)} – {formatTime(b.end_at, timezone)} ·{" "}
                    {b.customer_name} · {b.customer_phone}
                  </div>
                </div>
                <Badge tone={b.status === "confirmed" ? "success" : "neutral"}>{b.status}</Badge>
                {tab === "upcoming" && (
                  <button
                    onClick={() => cancel(b)}
                    className="text-xs font-medium text-muted transition hover:text-red-600"
                  >
                    Cancel
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

function Stat({ icon: Icon, label, value }: { icon: React.ElementType; label: string; value: number }) {
  return (
    <Card className="flex items-center gap-4 p-5">
      <span className={cn("flex size-10 items-center justify-center rounded-xl", BRAND_TINT)}>
        <Icon className="size-5" />
      </span>
      <div>
        <div className="text-2xl font-semibold tabular-nums">{value}</div>
        <div className="text-xs text-muted">{label}</div>
      </div>
    </Card>
  );
}

function DateBadge({ iso, timezone }: { iso: string; timezone?: string }) {
  const d = new Date(iso);
  const month = d.toLocaleString(undefined, { month: "short", timeZone: timezone });
  const day = d.toLocaleString(undefined, { day: "numeric", timeZone: timezone });
  return (
    <div className="flex w-12 flex-col items-center rounded-lg border border-border py-1">
      <span className="text-[10px] font-semibold uppercase text-indigo-600 dark:text-indigo-400">
        {month}
      </span>
      <span className="text-lg font-semibold leading-tight">{day}</span>
    </div>
  );
}

/** Times are shown in the business's timezone, not the viewer's. */
function formatTime(iso: string, timezone?: string) {
  return new Date(iso).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  });
}

function sameDay(iso: string, timezone?: string) {
  const fmt = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: timezone });
  return fmt(new Date(iso)) === fmt(new Date());
}
