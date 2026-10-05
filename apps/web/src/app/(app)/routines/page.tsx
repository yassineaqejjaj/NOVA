"use client";

import { Button, cn, Dialog, DialogContent, Input, Label, Select, Skeleton, Switch, Textarea } from "@nova/ui";
import { CalendarClock, Pencil, Play, Plus, Repeat, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { AutonomyLevels } from "@/components/missions/ui";
import { M } from "@/components/missions/missions.messages";
import { EmptyState, Page, PageHeader } from "@/components/shell/page";
import { ApiError } from "@/lib/api/client";
import { useProjects, useSkills } from "@/lib/api/hooks";
import { type GoalAutonomy, type Routine, type RoutineTemplate, type Schedule, useDeleteRoutine, useRoutines, useRoutineTemplates, useRunRoutine, useSaveRoutine } from "@/lib/api/missions";
import { dateTime, timeAgo } from "@/lib/format";
import { useLang, useT } from "@/lib/i18n";
import { skillName } from "@/lib/i18n/catalog";

const DAYS = [0, 1, 2, 3, 4, 5, 6] as const;
type Draft = { id?: string; name: string; instructions: string; skill_ids: string[]; schedule: Schedule; autonomy: GoalAutonomy; project_id: string | null; template?: string | null; enabled: boolean };

function useScheduleText() {
  const t = useT(M);
  return (s: Schedule) => {
    const days = s.kind === "weekly" ? ` · ${(s.days ?? []).map((d) => t(`d${d as 0}`)).join(", ")}` : s.kind === "monthly" ? ` · ${s.day ?? 1}` : "";
    return s.kind === "manual" ? t("k_manual") : `${t(`k_${s.kind}`)}${days} · ${s.time ?? "08:30"}`;
  };
}

function RoutineDialog({ draft, onClose }: { draft: Draft; onClose: () => void }) {
  const t = useT(M);
  const lang = useLang();
  const { data: skills } = useSkills();
  const { data: projects } = useProjects();
  const save = useSaveRoutine();
  const [d, setD] = useState<Draft>(draft);
  const set = (patch: Partial<Draft>) => setD((prev) => ({ ...prev, ...patch }));
  const setSchedule = (patch: Partial<Schedule>) => setD((prev) => ({ ...prev, schedule: { ...prev.schedule, ...patch } }));
  const toggleDay = (day: number) => setSchedule({ days: (d.schedule.days ?? []).includes(day) ? (d.schedule.days ?? []).filter((x) => x !== day) : [...(d.schedule.days ?? []), day].sort() });
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await save.mutateAsync({ ...d, schedule: { ...d.schedule, tz: Intl.DateTimeFormat().resolvedOptions().timeZone || "Europe/Paris" } });
      toast(t("saved"));
      onClose();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    }
  };
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent title={d.id ? t("edit") : t("newRoutine")} className="max-h-[82vh] overflow-y-auto sm:w-[min(92vw,620px)]">
        <form onSubmit={submit} className="space-y-4">
          <div className="space-y-1.5"><Label htmlFor="r-name">{t("routineName")}</Label><Input id="r-name" required value={d.name} onChange={(e) => set({ name: e.target.value })} /></div>
          <div className="space-y-1.5"><Label htmlFor="r-instr">{t("instructions")}</Label><Textarea id="r-instr" required rows={3} value={d.instructions} onChange={(e) => set({ instructions: e.target.value })} /></div>
          <div className="space-y-1.5">
            <Label>{t("schedule")}</Label>
            <div className="grid gap-2 sm:grid-cols-[1fr_120px]">
              <Select value={d.schedule.kind} onValueChange={(v) => setSchedule({ kind: v as Schedule["kind"], days: v === "weekly" ? d.schedule.days?.length ? d.schedule.days : [0] : d.schedule.days })} options={(["daily", "weekdays", "weekly", "monthly", "manual"] as const).map((k) => ({ value: k, label: t(`k_${k}`) }))} className="w-full" ariaLabel={t("schedule")} />
              {d.schedule.kind !== "manual" ? <Input type="time" aria-label={t("time")} value={d.schedule.time ?? "08:30"} onChange={(e) => setSchedule({ time: e.target.value })} /> : null}
            </div>
            {d.schedule.kind === "weekly" ? (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {DAYS.map((day) => (
                  <button key={day} type="button" aria-pressed={(d.schedule.days ?? []).includes(day)} onClick={() => toggleDay(day)} className={cn("rounded-full border px-2.5 py-1 text-[12.5px]", (d.schedule.days ?? []).includes(day) ? "border-accent/50 bg-accent-soft text-text" : "border-border text-muted")}>{t(`d${day}`)}</button>
                ))}
              </div>
            ) : null}
            {d.schedule.kind === "monthly" ? <div className="flex items-center gap-2 pt-1 text-[13px]"><Label htmlFor="r-day">{t("dayOfMonth")}</Label><Input id="r-day" type="number" min={1} max={28} className="w-20" value={d.schedule.day ?? 1} onChange={(e) => setSchedule({ day: Number(e.target.value) })} /></div> : null}
          </div>
          <div className="space-y-1.5">
            <Label>{t("skillsUsed")}</Label>
            <div className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto">
              {(skills ?? []).map((s) => {
                const on = d.skill_ids.includes(s.id);
                return <button key={s.id} type="button" aria-pressed={on} onClick={() => set({ skill_ids: on ? d.skill_ids.filter((x) => x !== s.id) : [...d.skill_ids, s.id].slice(0, 6) })} className={cn("rounded-full border px-2.5 py-1 text-[12px]", on ? "border-accent/50 bg-accent-soft text-text" : "border-border text-muted hover:text-text")}>{skillName(s, lang)}</button>;
              })}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>{t("project")}</Label>
            <Select value={d.project_id ?? "none"} onValueChange={(v) => set({ project_id: v === "none" ? null : v })} options={[{ value: "none", label: t("noProject") }, ...(projects ?? []).map((p) => ({ value: p.id, label: p.name }))]} className="w-full" ariaLabel={t("project")} />
          </div>
          <div className="space-y-1.5"><Label>{t("autonomy")}</Label><AutonomyLevels value={d.autonomy} onChange={(v) => set({ autonomy: v })} /></div>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={onClose}>{t("cancel")}</Button>
            <Button type="submit" variant="primary" disabled={save.isPending}>{t("save")}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RoutineRow({ routine, onEdit }: { routine: Routine; onEdit: () => void }) {
  const t = useT(M);
  const text = useScheduleText();
  const run = useRunRoutine();
  const save = useSaveRoutine();
  const remove = useDeleteRoutine();
  return (
    <li className="flex flex-wrap items-center gap-3 py-3.5" data-testid="routine">
      <span className={cn("grid size-9 place-items-center rounded-full", routine.enabled ? "bg-accent-soft text-accent" : "bg-surface-2 text-subtle")}><Repeat className="size-4" /></span>
      <div className="min-w-0 flex-1 basis-56">
        <div className="text-[14.5px] font-medium">{routine.name}</div>
        <div className="mt-0.5 flex flex-wrap gap-x-3 text-[12px] text-subtle">
          <span className="inline-flex items-center gap-1"><CalendarClock className="size-3" /> {text(routine.schedule)}</span>
          {routine.next_run_at && routine.enabled ? <span>{t("nextRun", { when: dateTime(routine.next_run_at) })}</span> : null}
          {routine.last_run_at ? <span>{t("lastRun", { when: timeAgo(routine.last_run_at) })}</span> : null}
          <span>{t("runs", { n: routine.runs })}</span>
        </div>
      </div>
      <div className="flex items-center gap-1">
        <Switch checked={routine.enabled} onCheckedChange={(enabled) => save.mutate({ id: routine.id, enabled })} aria-label={t("enabled")} />
        <Button variant="secondary" size="sm" onClick={() => run.mutate(routine.id, { onSuccess: () => toast(t("started")) })} disabled={run.isPending}><Play className="!size-3" /> {t("runNow")}</Button>
        {routine.conversation_id ? <Link href={`/c/${routine.conversation_id}`} className="rounded-md px-2 py-1 text-[12.5px] text-accent hover:underline">{t("missions")}</Link> : null}
        <Button variant="ghost" size="icon" className="size-8" onClick={onEdit} aria-label={t("edit")}><Pencil className="!size-3.5" /></Button>
        <Button variant="ghost" size="icon" className="size-8 text-subtle" onClick={() => remove.mutate(routine.id, { onSuccess: () => toast(t("deleted")) })} aria-label={t("delete")}><Trash2 className="!size-3.5" /></Button>
      </div>
    </li>
  );
}

export default function RoutinesPage() {
  const t = useT(M);
  const text = useScheduleText();
  const { data: routines, isLoading } = useRoutines();
  const { data: templates } = useRoutineTemplates();
  const [draft, setDraft] = useState<Draft | null>(null);
  const fromTemplate = (tpl: RoutineTemplate): Draft => ({ name: tpl.name, instructions: tpl.instructions, skill_ids: tpl.skill_ids, schedule: tpl.schedule, autonomy: "execute_automatically", project_id: null, template: tpl.id, enabled: true });
  const blank: Draft = { name: "", instructions: "", skill_ids: [], schedule: { kind: "weekly", days: [0], time: "08:30" }, autonomy: "execute_automatically", project_id: null, enabled: true };
  const used = new Set((routines ?? []).map((r) => r.template));
  return (
    <Page>
      <PageHeader title={t("routinesTitle")} description={t("routinesDescription")} actions={<Button variant="primary" onClick={() => setDraft(blank)}><Plus /> {t("newRoutine")}</Button>} />
      {isLoading ? <Skeleton className="h-32" /> : null}
      {routines && routines.length === 0 ? <EmptyState icon={<Repeat />} title={t("routinesEmpty")} description={t("routinesEmptyHint")} /> : null}
      <ul className="divide-y divide-border/70">
        {(routines ?? []).map((r) => <RoutineRow key={r.id} routine={r} onEdit={() => setDraft({ ...r })} />)}
      </ul>
      <section className="mt-10">
        <h2 className="mb-3 text-[15px] font-semibold tracking-tight">{t("templates")}</h2>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {(templates ?? []).map((tpl) => (
            <button key={tpl.id} onClick={() => setDraft(fromTemplate(tpl))} className={cn("rounded-[14px] border border-border bg-surface p-3.5 text-left transition-colors hover:border-accent/40", used.has(tpl.id) && "opacity-60")} data-testid="routine-template">
              <div className="flex items-center gap-2 text-[14px] font-medium"><Repeat className="size-3.5 text-accent" /> {tpl.name}</div>
              <div className="mt-0.5 text-[12px] text-subtle">{text(tpl.schedule)}</div>
              <p className="mt-1.5 line-clamp-2 text-[12.5px] text-muted">{tpl.instructions}</p>
            </button>
          ))}
        </div>
      </section>
      {draft ? <RoutineDialog draft={draft} onClose={() => setDraft(null)} /> : null}
    </Page>
  );
}
