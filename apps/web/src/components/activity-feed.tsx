"use client";

import { Button, cn, Skeleton } from "@nova/ui";
import { Check, CircleCheckBig, FileText, Orbit, Play, X } from "lucide-react";
import Link from "next/link";

import { EmptyState } from "@/components/shell/page";
import { useActivity } from "@/lib/api/hooks";
import type { ActivityEvent } from "@/lib/api/types";
import { clock, dayLabel } from "@/lib/format";

const TONES = {
  accent: "bg-accent-soft text-accent",
  success: "bg-success/12 text-success",
  danger: "bg-danger/12 text-danger",
  neutral: "bg-surface-3 text-muted",
  violet: "bg-[#efeafd] text-[#6d4fd8] dark:bg-[#6d4fd8]/20 dark:text-[#b7a6f5]",
} as const;

function look(e: ActivityEvent): { icon: React.ReactNode; tone: keyof typeof TONES } {
  if (e.category === "decision") return { icon: <CircleCheckBig />, tone: e.status === "reject" || e.status === "cancel" ? "danger" : "violet" };
  if (e.category === "artifact") return { icon: <FileText />, tone: "accent" };
  if (e.category === "context") return { icon: <Orbit />, tone: "neutral" };
  if (e.kind === "task_completed") return { icon: <Check />, tone: "success" };
  if (e.kind === "task_failed" || e.kind === "task_cancelled") return { icon: <X />, tone: "danger" };
  return { icon: <Play />, tone: "neutral" };
}

function target(e: ActivityEvent): { href: string; label: string } | null {
  if (e.artifact_id) return { href: `/artifacts/${e.artifact_id}`, label: "View artifact" };
  if (e.conversation_id) return { href: `/c/${e.conversation_id}`, label: e.category === "decision" ? "View decision" : "View work" };
  if (e.task_id) return { href: `/work?task=${e.task_id}`, label: "View work" };
  return null;
}

export function filterEvents(events: ActivityEvent[], { category, query }: { category?: string; query?: string }) {
  const needle = query?.trim().toLowerCase();
  return events.filter((e) => {
    if (category === "projects" && !e.project_id) return false;
    if (category && category !== "projects" && category !== "all" && e.category !== category) return false;
    if (needle && !`${e.text} ${e.detail ?? ""} ${e.project_name ?? ""}`.toLowerCase().includes(needle)) return false;
    return true;
  });
}

export function ActivityFeed({
  filters,
  category,
  query,
  compact = false,
}: {
  filters: Record<string, string | undefined>;
  category?: string;
  query?: string;
  compact?: boolean;
}) {
  const { data, isLoading } = useActivity(filters);
  if (isLoading) return <div className="space-y-2"><Skeleton className="h-12" /><Skeleton className="h-12" /></div>;
  const events = filterEvents(data ?? [], { category, query });
  if (!events.length) {
    return <EmptyState icon={<Play />} title={data?.length ? "Nothing matches these filters." : "No activity yet."} description="What NOVA does for you will be listed here." />;
  }
  const groups = new Map<string, ActivityEvent[]>();
  for (const e of events) groups.set(dayLabel(e.at), [...(groups.get(dayLabel(e.at)) ?? []), e]);
  return (
    <div className="space-y-6">
      {[...groups.entries()].map(([day, list]) => (
        <section key={day}>
          <h3 className="mb-2 text-[13px] font-semibold text-text">{day}</h3>
          <ol className="relative">
            {list.map((e, i) => {
              const { icon, tone } = look(e);
              const link = target(e);
              return (
                <li key={`${e.kind}-${e.at}-${i}`} className="relative flex gap-3 pb-1">
                  {!compact ? <span className="w-12 shrink-0 pt-2.5 text-right text-[12px] tabular-nums text-subtle">{clock(e.at)}</span> : null}
                  <div className="relative flex flex-col items-center">
                    <span className={cn("z-10 mt-1.5 flex size-8 items-center justify-center rounded-full [&_svg]:size-4", TONES[tone])}>{icon}</span>
                    {i < list.length - 1 ? <span className="absolute top-10 bottom-0 w-px bg-border" /> : null}
                  </div>
                  <div className={cn("flex min-w-0 flex-1 items-start gap-3 rounded-[14px] px-3 py-2", !compact && "hover:bg-surface-2/70")}>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13.5px] font-medium leading-snug text-text">{e.text}</div>
                      {e.detail ? <div className="mt-0.5 line-clamp-2 text-[12.5px] text-muted">{e.detail}</div> : null}
                      {e.project_name && !compact ? (
                        <span className="mt-1.5 inline-flex items-center gap-1.5 text-[11.5px] text-subtle">
                          <span className="size-1.5 rounded-full bg-accent/70" /> {e.project_name}
                        </span>
                      ) : null}
                      {compact ? <div className="mt-0.5 text-[11.5px] text-subtle">{clock(e.at)}</div> : null}
                    </div>
                    {link && !compact ? (
                      <Button variant="secondary" size="sm" className="shrink-0 rounded-full max-sm:hidden" asChild>
                        <Link href={link.href}>{link.label}</Link>
                      </Button>
                    ) : null}
                    {link && compact ? <Link href={link.href} className="shrink-0 text-[12px] text-accent hover:underline">View</Link> : null}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      ))}
    </div>
  );
}
