import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-xl border border-border bg-surface shadow-sm", className)}
      {...props}
    />
  );
}

type Tone = "neutral" | "brand" | "success" | "warning" | "danger";

const TONES: Record<Tone, string> = {
  neutral: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
  brand: "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300",
  success: "bg-emerald-50 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  warning: "bg-amber-50 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  danger: "bg-red-50 text-red-700 dark:bg-red-500/15 dark:text-red-300",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
      {...props}
    />
  );
}

const fieldClass =
  "w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm outline-none transition placeholder:text-zinc-400 focus:border-indigo-500 focus:ring-4 focus:ring-indigo-500/10";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(fieldClass, "h-10", className)} {...props} />;
}

export function Textarea({
  className,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(fieldClass, "resize-none", className)} {...props} />;
}

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("mb-1.5 block text-sm font-medium", className)} {...props} />;
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex gap-2">{actions}</div>}
    </div>
  );
}
