import { CalendarCheck, Check, X } from "lucide-react";

import type { UIMessage } from "@/components/chat/types";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/primitives";
import { BRAND_TINT, cn } from "@/lib/utils";

/** Human-in-the-loop: the agent paused and needs the customer's go-ahead. */
export function ConfirmCard({
  confirmation,
  busy,
  onDecide,
}: {
  confirmation: NonNullable<UIMessage["confirmation"]>;
  busy: boolean;
  onDecide: (approved: boolean) => void;
}) {
  const { actions, state } = confirmation;

  return (
    <div className="w-full max-w-sm animate-fade-in rounded-2xl border border-border bg-surface p-4 shadow-sm">
      {actions.map((action, i) => (
        <div key={i} className={cn(i > 0 && "mt-4 border-t border-border pt-4")}>
          <div className="flex items-center gap-2">
            <span className={cn("flex size-8 items-center justify-center rounded-lg", BRAND_TINT)}>
              <CalendarCheck className="size-4" />
            </span>
            <span className="text-sm font-semibold">{action.title}</span>
          </div>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
            {Object.entries(action.details).map(([label, value]) => (
              <div key={label} className="contents">
                <dt className="text-muted">{label}</dt>
                <dd className="font-medium">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}

      <div className="mt-4">
        {state === "pending" ? (
          <div className="flex gap-2">
            <Button size="sm" className="flex-1" disabled={busy} onClick={() => onDecide(true)}>
              <Check className="size-4" /> Confirm
            </Button>
            <Button
              size="sm"
              variant="secondary"
              className="flex-1"
              disabled={busy}
              onClick={() => onDecide(false)}
            >
              <X className="size-4" /> Decline
            </Button>
          </div>
        ) : (
          <Badge tone={state === "approved" ? "success" : "neutral"}>
            {state === "approved" ? (
              <>
                <Check className="size-3" /> Confirmed
              </>
            ) : (
              <>
                <X className="size-3" /> Declined
              </>
            )}
          </Badge>
        )}
      </div>
    </div>
  );
}
