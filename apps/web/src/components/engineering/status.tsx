"use client";

import { Badge } from "@nova/ui";
import { Check, CircleDashed, Loader2, Minus, Hourglass, X } from "lucide-react";

import type { RunStatus, StageStatus } from "@/lib/api/engineering";
import { useT } from "@/lib/i18n";

import { M } from "./engineering.messages";

const TONE: Record<RunStatus, "neutral" | "accent" | "success" | "warning" | "danger"> = {
  queued: "neutral",
  running: "accent",
  waiting_user: "warning",
  completed: "success",
  failed: "danger",
  cancelled: "neutral",
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const t = useT(M);
  return (
    <Badge tone={TONE[status]} data-testid="run-status" data-status={status}>
      {status === "running" ? <Loader2 className="size-3 animate-spin" aria-hidden /> : null}
      {t(`s_${status}` as "s_queued")}
    </Badge>
  );
}

export function StageIcon({ status }: { status: StageStatus }) {
  const base = "grid size-6 shrink-0 place-items-center rounded-full";
  switch (status) {
    case "done":
      return <span className={`${base} bg-success/15 text-success`}><Check className="size-3.5" /></span>;
    case "running":
      return <span className={`${base} bg-accent-soft text-accent`}><Loader2 className="size-3.5 animate-spin" /></span>;
    case "waiting":
      return <span className={`${base} bg-warning/15 text-warning`}><Hourglass className="size-3.5" /></span>;
    case "failed":
      return <span className={`${base} bg-danger/15 text-danger`}><X className="size-3.5" /></span>;
    case "skipped":
      return <span className={`${base} bg-surface-2 text-subtle`}><Minus className="size-3.5" /></span>;
    default:
      return <span className={`${base} bg-surface-2 text-subtle`}><CircleDashed className="size-3.5" /></span>;
  }
}
