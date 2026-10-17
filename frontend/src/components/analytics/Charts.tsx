"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

/*
 * Small hand-written SVG charts (no chart library).
 * Marks use one validated hue (indigo-600 on light, indigo-500 on dark — both pass the
 * palette validator's lightness/contrast checks); text always stays in ink colours.
 */

type Point = { date: string; turns: number; conversations: number };

const HEIGHT = 220;
const PAD = { top: 16, right: 12, bottom: 28, left: 36 };

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/** A "nice" axis maximum and 3–4 evenly spaced ticks. */
function ticks(max: number) {
  if (max <= 4) return [0, 1, 2, 3, 4].filter((t) => t <= Math.max(max, 1) + 1).slice(0, 5);
  const step = 10 ** Math.floor(Math.log10(max / 3));
  const nice = [1, 2, 5, 10].map((m) => m * step).find((s) => max / s <= 4) ?? step * 10;
  return Array.from({ length: Math.ceil(max / nice) + 1 }, (_, i) => i * nice);
}

const shortDate = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short" });

/** Messages per day: area + 2px line, crosshair tooltip on hover. */
export function TrendChart({ data }: { data: Point[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const yTicks = ticks(Math.max(...data.map((d) => d.turns), 0));
  const yMax = yTicks[yTicks.length - 1] || 1;
  const plotW = Math.max(width - PAD.left - PAD.right, 1);
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const x = (i: number) => PAD.left + (data.length > 1 ? (i / (data.length - 1)) * plotW : plotW / 2);
  const y = (v: number) => PAD.top + plotH - (v / yMax) * plotH;

  const line = data.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d.turns)}`).join("");
  const area = `${line}L${x(data.length - 1)},${y(0)}L${x(0)},${y(0)}Z`;
  // As many date labels as fit (~70px each), at most 6.
  const labels = Math.min(6, Math.max(2, Math.floor(plotW / 70)));
  const every = Math.max(1, Math.ceil(data.length / labels));

  function onMove(e: React.PointerEvent<SVGRectElement>) {
    const box = e.currentTarget.getBoundingClientRect();
    const ratio = (e.clientX - box.left) / box.width;
    setHover(Math.min(data.length - 1, Math.max(0, Math.round(ratio * (data.length - 1)))));
  }

  const active = hover !== null ? data[hover] : null;

  return (
    <div ref={ref} className="relative">
      {width > 0 && (
        <svg width={width} height={HEIGHT} role="img" aria-label="Messages per day">
          {yTicks.map((t) => (
            <g key={t}>
              <line
                x1={PAD.left}
                x2={width - PAD.right}
                y1={y(t)}
                y2={y(t)}
                className="stroke-zinc-200 dark:stroke-zinc-800"
                strokeWidth={1}
              />
              <text
                x={PAD.left - 8}
                y={y(t)}
                dy="0.32em"
                textAnchor="end"
                className="fill-zinc-500 text-[11px] tabular-nums dark:fill-zinc-400"
              >
                {t}
              </text>
            </g>
          ))}
          {data.map((d, i) =>
            (i % every === 0 && data.length - 1 - i >= every / 2) || i === data.length - 1 ? (
              <text
                key={d.date}
                x={x(i)}
                y={HEIGHT - 8}
                textAnchor={i === 0 ? "start" : i === data.length - 1 ? "end" : "middle"}
                className="fill-zinc-500 text-[11px] dark:fill-zinc-400"
              >
                {shortDate(d.date)}
              </text>
            ) : null,
          )}

          <path d={area} className="fill-indigo-600/10 dark:fill-indigo-500/15" />
          <path
            d={line}
            fill="none"
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
            className="stroke-indigo-600 dark:stroke-indigo-500"
          />

          {active && hover !== null && (
            <g pointerEvents="none">
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={PAD.top}
                y2={PAD.top + plotH}
                className="stroke-zinc-300 dark:stroke-zinc-700"
                strokeWidth={1}
              />
              <circle
                cx={x(hover)}
                cy={y(active.turns)}
                r={5}
                strokeWidth={2}
                className="fill-indigo-600 stroke-[var(--surface)] dark:fill-indigo-500"
              />
            </g>
          )}

          {/* Hit target: the whole plot, so hovering anywhere snaps to the nearest day. */}
          <rect
            x={PAD.left}
            y={PAD.top}
            width={plotW}
            height={plotH}
            fill="transparent"
            onPointerMove={onMove}
            onPointerLeave={() => setHover(null)}
          />
        </svg>
      )}

      {active && hover !== null && (
        <div
          className="pointer-events-none absolute top-2 z-10 min-w-36 rounded-lg border border-border bg-surface px-3 py-2 text-xs shadow-lg"
          // Beside the crosshair (never on top of the line); flips left near the right edge.
          style={x(hover) + 172 > width ? { right: width - x(hover) + 12 } : { left: x(hover) + 12 }}
        >
          <div className="mb-1 font-medium">{shortDate(active.date)}</div>
          <Row label="Messages" value={active.turns} swatch />
          <Row label="Conversations" value={active.conversations} />
        </div>
      )}
    </div>
  );
}

function Row({ label, value, swatch }: { label: string; value: number; swatch?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 text-muted">
      <span className="flex items-center gap-1.5">
        {swatch ? (
          <span className="size-2 rounded-full bg-indigo-600 dark:bg-indigo-500" />
        ) : (
          <span className="size-2" />
        )}
        {label}
      </span>
      <span className="font-medium tabular-nums text-foreground">{value}</span>
    </div>
  );
}

export type BarItem = { key: string; label: string; value: number };

/** Horizontal bars, sorted by size, value at the tip, share on hover. */
export function BarList({ items, empty = "No data yet." }: { items: BarItem[]; empty?: string }) {
  const total = items.reduce((s, i) => s + i.value, 0);
  const max = Math.max(...items.map((i) => i.value), 1);
  if (total === 0) return <p className="py-6 text-center text-sm text-muted">{empty}</p>;

  return (
    <ul className="space-y-3">
      {[...items]
        .sort((a, b) => b.value - a.value)
        .map((item) => (
          <li key={item.key} className="group relative">
            <div className="mb-1 flex items-baseline justify-between gap-3 text-sm">
              <span className="truncate">{item.label}</span>
              <span className="tabular-nums text-muted">
                <span className="mr-1.5 text-xs opacity-0 transition group-hover:opacity-100">
                  {Math.round((item.value / total) * 100)}%
                </span>
                <span className="font-medium text-foreground">{item.value}</span>
              </span>
            </div>
            <div className="h-2.5 w-full">
              <div
                className={cn(
                  "h-full rounded-r-[4px] bg-indigo-600 transition group-hover:bg-indigo-700 dark:bg-indigo-500 dark:group-hover:bg-indigo-400",
                  item.value === 0 && "hidden",
                )}
                style={{ width: `${Math.max((item.value / max) * 100, 1.5)}%` }}
              />
            </div>
          </li>
        ))}
    </ul>
  );
}
