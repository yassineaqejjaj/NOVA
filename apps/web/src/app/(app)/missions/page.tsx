"use client";

import { Skeleton } from "@nova/ui";
import { CalendarClock, Loader2, Repeat } from "lucide-react";
import Link from "next/link";

import { MISSION_ORB, MissionChip, ProgressBar } from "@/components/missions/ui";
import { M } from "@/components/missions/missions.messages";
import { Page, PageHeader } from "@/components/shell/page";
import { NovaOrb } from "@/components/shell/nova-orb";
import { useMissions } from "@/lib/api/missions";
import { dateTime, timeAgo } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSystemLabel } from "@/lib/i18n/catalog";

/** Mission Control: everything NOVA is carrying out — goals, running work, upcoming routines. */
export default function MissionsPage() {
  const t = useT(M);
  const label = useSystemLabel();
  const { data, isLoading } = useMissions();
  const goals = (data?.goals ?? []).filter((g) => g.status !== "completed" || (g.completed_at && Date.now() - new Date(g.completed_at).getTime() < 7 * 86400_000));
  const standalone = (data?.tasks ?? []).filter((task) => !task.goal_id);
  return (
    <Page>
      <PageHeader title={t("missionsTitle")} description={t("missionsDescription")} />
      {isLoading ? <Skeleton className="h-60" /> : null}
      <section aria-labelledby="goals-heading">
        <h2 id="goals-heading" className="mb-2 text-[15px] font-semibold tracking-tight">{t("activeGoals")}</h2>
        {data && goals.length === 0 ? <p className="text-[13px] text-subtle">{t("noGoalsRunning")} <Link href="/goals?new=1" className="text-accent hover:underline">{t("newGoal")}</Link></p> : null}
        <ul className="divide-y divide-border/70">
          {goals.map((g) => (
            <li key={g.id} className="py-3" data-testid="mission" data-mission={g.mission}>
              <Link href={`/goals?goal=${g.id}`} className="flex items-center gap-3">
                <NovaOrb state={MISSION_ORB[g.mission]} size={30} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-[14.5px] font-medium">{g.title}</span>
                    <MissionChip state={g.mission} />
                  </div>
                  <div className="mt-1 flex items-center gap-2">
                    <ProgressBar percent={g.progress.percent} className="flex-1" />
                    <span className="text-[12px] tabular-nums text-subtle">{g.progress.percent}%</span>
                  </div>
                  <div className="mt-1 truncate text-[12px] text-muted">
                    {g.current ? `${g.current.title}${g.current.activity ? ` — ${label(g.current.activity)}` : ""}` : g.next ? `${t("next")} : ${g.next.title}` : ""}
                  </div>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="work-heading" className="mt-10">
        <h2 id="work-heading" className="mb-2 text-[15px] font-semibold tracking-tight">{t("runningWork")}</h2>
        {data && standalone.length === 0 ? <p className="text-[13px] text-subtle">{t("nothingRunning")}</p> : null}
        <ul className="divide-y divide-border/70">
          {standalone.map((task) => (
            <li key={task.id} className="flex items-center gap-3 py-2.5">
              {task.origin === "routine" ? <Repeat className="size-4 text-subtle" /> : <Loader2 className="size-4 animate-spin text-accent" />}
              <Link href={task.conversation_id ? `/c/${task.conversation_id}` : `/work?task=${task.id}`} className="min-w-0 flex-1 truncate text-[14px] hover:text-accent">{task.title}</Link>
              <span className="truncate text-[12px] text-subtle">{label(task.activity)}</span>
              <span className="shrink-0 text-[12px] text-subtle">{timeAgo(task.started_at)}</span>
            </li>
          ))}
        </ul>
      </section>
      <section aria-labelledby="routines-heading" className="mt-10">
        <h2 id="routines-heading" className="mb-2 text-[15px] font-semibold tracking-tight">{t("upcoming")}</h2>
        <ul className="divide-y divide-border/70">
          {(data?.routines ?? []).filter((r) => r.next_run_at).map((r) => (
            <li key={r.id} className="flex items-center gap-3 py-2.5">
              <CalendarClock className="size-4 text-subtle" />
              <Link href="/routines" className="min-w-0 flex-1 truncate text-[14px] hover:text-accent">{r.name}</Link>
              <span className="text-[12px] text-subtle">{t("nextRun", { when: dateTime(r.next_run_at!) })}</span>
            </li>
          ))}
        </ul>
      </section>
    </Page>
  );
}
