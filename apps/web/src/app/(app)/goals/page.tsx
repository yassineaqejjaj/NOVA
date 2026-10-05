"use client";

import { Button, cn, Skeleton } from "@nova/ui";
import { AnimatePresence, motion } from "framer-motion";
import { CalendarClock, MessageSquare, Pause, Play, Plus, Target, X } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

import { GoalDialog } from "@/components/missions/goal-dialog";
import { MilestoneList, MISSION_ORB, MissionChip, ProgressBar } from "@/components/missions/ui";
import { M } from "@/components/missions/missions.messages";
import { EmptyState, Page, PageHeader } from "@/components/shell/page";
import { NovaOrb } from "@/components/shell/nova-orb";
import { type Goal, useGoal, useGoalAction, useGoals } from "@/lib/api/missions";
import { useLang, useT } from "@/lib/i18n";
import { useSystemLabel } from "@/lib/i18n/catalog";

function formatDate(iso: string, lang: string) {
  return new Date(iso).toLocaleDateString(lang === "fr" ? "fr-FR" : "en-GB", { day: "numeric", month: "short" });
}

function GoalCard({ goal, selected, onSelect }: { goal: Goal; selected: boolean; onSelect: () => void }) {
  const t = useT(M);
  const lang = useLang();
  const label = useSystemLabel();
  return (
    <button onClick={onSelect} className={cn("w-full rounded-[16px] border bg-surface px-4 py-4 text-left transition-colors hover:border-border-strong", selected ? "border-accent/50" : "border-border")} data-testid="goal-card">
      <div className="flex items-start gap-3">
        <NovaOrb state={MISSION_ORB[goal.mission]} size={34} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-semibold tracking-tight">{goal.title}</span>
            <MissionChip state={goal.mission} />
          </div>
          <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12px] text-subtle">
            {goal.project_name ? <span>{goal.project_name}</span> : null}
            {goal.due_date ? <span className="inline-flex items-center gap-1"><CalendarClock className="size-3" /> {t("due", { date: formatDate(goal.due_date, lang) })}</span> : null}
            <span>{t(`s_${goal.status}`)}</span>
          </div>
        </div>
        <span className="text-[20px] font-semibold tabular-nums">{goal.progress.percent}%</span>
      </div>
      <ProgressBar percent={goal.progress.percent} className="mt-3" />
      <div className="mt-2 flex justify-between gap-3 text-[12px] text-muted">
        <span className="truncate">{goal.current ? `● ${goal.current.title}${goal.current.activity ? ` — ${label(goal.current.activity)}` : ""}` : goal.next ? `○ ${goal.next.title}` : ""}</span>
        <span className="shrink-0 tabular-nums text-subtle">{t("progress", { done: goal.progress.done, total: goal.progress.total })}</span>
      </div>
    </button>
  );
}

function GoalDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const t = useT(M);
  const lang = useLang();
  const label = useSystemLabel();
  const { data: goal } = useGoal(id);
  const act = useGoalAction();
  if (!goal) return <div className="p-5"><Skeleton className="h-60" /></div>;
  const waiting = goal.milestones.filter((m) => m.status === "waiting" || m.status === "ready");
  const run = (action: string) => act.mutate({ goalId: goal.id, action }, { onSuccess: () => toast(t("done")) });
  return (
    <div className="flex h-full flex-col" data-testid="goal-detail">
      <div className="flex items-start gap-3 border-b border-border px-5 py-4">
        <NovaOrb state={MISSION_ORB[goal.mission]} size={40} />
        <div className="min-w-0 flex-1">
          <div className="text-[11.5px] font-medium uppercase tracking-wider text-subtle">{t("missions")}</div>
          <h2 className="text-[17px] font-semibold leading-snug">{goal.title}</h2>
          {goal.outcome ? <p className="mt-0.5 text-[13px] text-muted">{goal.outcome}</p> : null}
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label={t("cancel")}><X /></Button>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4">
        <section>
          <div className="mb-1.5 flex items-center justify-between text-[12.5px]">
            <MissionChip state={goal.mission} />
            <span className="tabular-nums text-subtle">{goal.progress.percent}% · {t("progress", { done: goal.progress.done, total: goal.progress.total })}</span>
          </div>
          <ProgressBar percent={goal.progress.percent} />
          <dl className="mt-3 grid grid-cols-3 gap-2 text-[12px]">
            <div className="rounded-[10px] bg-surface-2/60 px-2.5 py-2"><dt className="text-subtle">{t("nowWorking")}</dt><dd className="mt-0.5 text-text">{goal.current?.status === "working" ? (goal.current.activity ? label(goal.current.activity) : goal.current.title) : "—"}</dd></div>
            <div className="rounded-[10px] bg-surface-2/60 px-2.5 py-2"><dt className="text-subtle">{t("next")}</dt><dd className="mt-0.5 text-text">{goal.next?.title ?? "—"}</dd></div>
            <div className="rounded-[10px] bg-surface-2/60 px-2.5 py-2"><dt className="text-subtle">{t("waitingForYou")}</dt><dd className={cn("mt-0.5", waiting.length ? "text-warning" : "text-text")}>{waiting.length ? waiting.map((m) => m.title).join(", ") : t("nothing")}</dd></div>
          </dl>
        </section>
        {goal.status === "proposed" ? (
          <div className="rounded-[12px] border border-accent/35 bg-accent-soft/50 p-3">
            <p className="text-[13px] text-text">{goal.summary}</p>
            <Button className="mt-2" variant="primary" size="sm" onClick={() => run("approve")} disabled={act.isPending}>{t("approvePlan")}</Button>
          </div>
        ) : goal.summary ? <p className="text-[13px] text-muted">{goal.summary}</p> : null}
        <section>
          <h3 className="mb-1.5 text-[11.5px] font-medium uppercase tracking-wider text-subtle">{t("plan")}</h3>
          <MilestoneList goalId={goal.id} milestones={goal.milestones} interactive={goal.status === "active"} />
        </section>
        {goal.assumptions.length ? <p className="text-[12px] text-subtle">{t("assumptions")} : {goal.assumptions.join(" · ")}</p> : null}
        <div className="flex flex-wrap gap-2 border-t border-border pt-3 text-[12.5px] text-subtle">
          <span>{t("autonomy")} : {t(`a_${goal.autonomy}`)}</span>
          {goal.due_date ? <span>· {t("due", { date: formatDate(goal.due_date, lang) })}</span> : null}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 border-t border-border px-5 py-3">
        {goal.conversation_id ? <Link href={`/c/${goal.conversation_id}`} className="inline-flex items-center gap-1.5 rounded-[10px] border border-border px-3 py-1.5 text-[13px] hover:bg-surface-2"><MessageSquare className="size-3.5" /> {t("openConversation")}</Link> : null}
        {goal.status === "active" ? <Button variant="secondary" size="sm" onClick={() => run("pause")}><Pause className="!size-3.5" /> {t("pause")}</Button> : null}
        {goal.status === "paused" ? <Button variant="secondary" size="sm" onClick={() => run("resume")}><Play className="!size-3.5" /> {t("resume")}</Button> : null}
        {goal.status !== "archived" ? <Button variant="ghost" size="sm" className="ml-auto text-subtle" onClick={() => run("archive")}>{t("archive")}</Button> : null}
      </div>
    </div>
  );
}

function GoalsPage() {
  const t = useT(M);
  const router = useRouter();
  const params = useSearchParams();
  const selected = params.get("goal");
  const { data: goals, isLoading } = useGoals();
  const [open, setOpen] = useState(params.get("new") === "1");
  const [preset, setPreset] = useState("");
  const select = (id: string | null) => router.replace(id ? `/goals?goal=${id}` : "/goals", { scroll: false });
  const examples = [t("exampleCheckout"), t("exampleQ1"), t("exampleChurn")];
  return (
    <div className="flex min-h-screen">
      <div className="min-w-0 flex-1">
        <Page>
          <PageHeader title={t("goalsTitle")} description={t("goalsDescription")} actions={<Button variant="primary" onClick={() => { setPreset(""); setOpen(true); }}><Plus /> {t("newGoal")}</Button>} />
          {isLoading ? <Skeleton className="h-40" /> : null}
          {goals && goals.length === 0 ? (
            <EmptyState
              icon={<Target />}
              title={t("goalsEmpty")}
              description={t("goalsEmptyHint")}
              action={
                <div className="flex flex-wrap justify-center gap-2">
                  {examples.map((e) => <Button key={e} variant="secondary" size="sm" className="rounded-full" onClick={() => { setPreset(e); setOpen(true); }}>{e}</Button>)}
                </div>
              }
            />
          ) : null}
          <div className="grid gap-3">{(goals ?? []).map((g) => <GoalCard key={g.id} goal={g} selected={g.id === selected} onSelect={() => select(g.id)} />)}</div>
        </Page>
      </div>
      <AnimatePresence>
        {selected ? (
          <motion.aside initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }} transition={{ duration: 0.2 }} className="fixed inset-0 z-40 bg-background md:sticky md:top-0 md:h-screen md:w-[460px] md:shrink-0 md:border-l md:border-border">
            <GoalDetail id={selected} onClose={() => select(null)} />
          </motion.aside>
        ) : null}
      </AnimatePresence>
      {open ? <GoalDialog key={preset} open={open} onOpenChange={setOpen} initialTitle={preset} /> : null}
    </div>
  );
}

export default function GoalsRoute() {
  return (
    <Suspense>
      <GoalsPage />
    </Suspense>
  );
}
