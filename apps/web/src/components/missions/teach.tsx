"use client";

import { Button, Dialog, DialogContent, Input, Label, Select, Textarea } from "@nova/ui";
import { motion } from "framer-motion";
import { Eye, GraduationCap, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ApiError } from "@/lib/api/client";
import { useSkills } from "@/lib/api/hooks";
import { type LearnedDraft, useTeach, useTeachActions } from "@/lib/api/missions";
import { defineMessages, useLang, useT } from "@/lib/i18n";
import { skillName } from "@/lib/i18n/catalog";

const M = defineMessages({
  en: {
    teach: "Teach NOVA",
    teachHint: "Do your task once: NOVA watches the steps and saves them as a Skill.",
    watching: "NOVA is watching — do your task as usual.",
    observed: (v: { n: number }) => (v.n === 1 ? "1 step observed" : `${v.n} steps observed`),
    finish: "Finish", cancel: "Cancel",
    reviewTitle: "What NOVA observed",
    reviewHint: "NOVA saw what you did in NOVA. Describe the steps you did elsewhere (Jira, Slack…), then let NOVA create the Skill.",
    nothingYet: "No step observed in NOVA yet.",
    outside: "Steps done outside NOVA (optional)",
    outsidePlaceholder: "e.g. I open Jira, filter the new stories, check the description and the acceptance criteria, then comment what is missing.",
    create: "Create the Skill", creating: "NOVA is generalising your workflow…",
    draftTitle: (v: { n: number }) => `NOVA detected a ${v.n}-step workflow`,
    name: "Name", description: "Description", steps: "Steps", stepTitle: "Step", instruction: "What to do", skill: "Skill",
    noSkill: "No Skill (instruction for NOVA)", addStep: "Add a step", save: "Save the Skill",
    saved: (v: { slug: string }) => `Skill saved — run it with /${v.slug}`,
    routineIdea: (v: { when: string }) => `Could run as a routine: ${v.when}`,
    k_request: "Request", k_edit: "Edit", k_decision: "Decision",
  },
  fr: {
    teach: "Apprendre à NOVA",
    teachHint: "Faites votre tâche une fois : NOVA observe les étapes et les enregistre en compétence.",
    watching: "NOVA vous observe — effectuez votre tâche normalement.",
    observed: (v: { n: number }) => (v.n > 1 ? `${v.n} étapes observées` : "1 étape observée"),
    finish: "Terminer", cancel: "Annuler",
    reviewTitle: "Ce que NOVA a observé",
    reviewHint: "NOVA a vu ce que vous avez fait dans NOVA. Décrivez les étapes faites ailleurs (Jira, Slack…), puis laissez NOVA créer la compétence.",
    nothingYet: "Aucune étape observée dans NOVA pour l’instant.",
    outside: "Étapes réalisées hors de NOVA (facultatif)",
    outsidePlaceholder: "ex. J’ouvre Jira, je filtre les nouvelles stories, je vérifie la description et les critères d’acceptation, puis je commente ce qui manque.",
    create: "Créer la compétence", creating: "NOVA généralise votre workflow…",
    draftTitle: (v: { n: number }) => `NOVA a détecté un workflow en ${v.n} étapes`,
    name: "Nom", description: "Description", steps: "Étapes", stepTitle: "Étape", instruction: "Ce qu’il faut faire", skill: "Compétence",
    noSkill: "Aucune compétence (instruction pour NOVA)", addStep: "Ajouter une étape", save: "Enregistrer la compétence",
    saved: (v: { slug: string }) => `Compétence enregistrée — lancez-la avec /${v.slug}`,
    routineIdea: (v: { when: string }) => `Pourrait tourner en routine : ${v.when}`,
    k_request: "Demande", k_edit: "Modification", k_decision: "Décision",
  },
});

export function TeachButton() {
  const t = useT(M);
  const { data } = useTeach();
  const { start } = useTeachActions();
  if (data?.active) return null;
  return (
    <Button variant="secondary" onClick={() => start.mutate(undefined, { onSuccess: () => toast(t("watching")) })} disabled={start.isPending} title={t("teachHint")}>
      <GraduationCap /> {t("teach")}
    </Button>
  );
}

function DraftEditor({ draft, onDone }: { draft: LearnedDraft; onDone: () => void }) {
  const t = useT(M);
  const lang = useLang();
  const { data: skills } = useSkills();
  const { save } = useTeachActions();
  const [d, setD] = useState(draft);
  const setStep = (i: number, patch: Partial<LearnedDraft["steps"][number]>) => setD({ ...d, steps: d.steps.map((s, j) => (j === i ? { ...s, ...patch } : s)) });
  const submit = async () => {
    try {
      const skill = await save.mutateAsync(d);
      toast(t("saved", { slug: skill.slug }));
      onDone();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    }
  };
  return (
    <div className="space-y-3" data-testid="learned-draft">
      <p className="text-[13.5px] font-medium text-accent">{t("draftTitle", { n: d.steps.length })}</p>
      <div className="space-y-1.5"><Label htmlFor="l-name">{t("name")}</Label><Input id="l-name" value={d.name} onChange={(e) => setD({ ...d, name: e.target.value })} /></div>
      <div className="space-y-1.5"><Label htmlFor="l-desc">{t("description")}</Label><Textarea id="l-desc" rows={2} value={d.description} onChange={(e) => setD({ ...d, description: e.target.value })} /></div>
      <div className="space-y-2">
        <Label>{t("steps")}</Label>
        {d.steps.map((s, i) => (
          <div key={i} className="rounded-[12px] border border-border p-2.5">
            <div className="flex items-center gap-2">
              <span className="text-[12px] font-semibold tabular-nums text-subtle">{i + 1}.</span>
              <Input aria-label={`${t("stepTitle")} ${i + 1}`} value={s.title} onChange={(e) => setStep(i, { title: e.target.value })} className="h-8" />
              <Button variant="ghost" size="icon" className="size-8 shrink-0 text-subtle" onClick={() => setD({ ...d, steps: d.steps.filter((_, j) => j !== i) })} aria-label={t("cancel")}><Trash2 className="!size-3.5" /></Button>
            </div>
            <Textarea aria-label={t("instruction")} rows={2} className="mt-1.5 text-[13px]" value={s.instruction} onChange={(e) => setStep(i, { instruction: e.target.value })} />
            <Select value={s.skill_id ?? "none"} onValueChange={(v) => setStep(i, { skill_id: v === "none" ? null : v })} options={[{ value: "none", label: t("noSkill") }, ...(skills ?? []).map((k) => ({ value: k.id, label: skillName(k, lang) }))]} className="mt-1.5 w-full" ariaLabel={t("skill")} />
          </div>
        ))}
        <Button variant="ghost" size="sm" onClick={() => setD({ ...d, steps: [...d.steps, { title: "", instruction: "", skill_id: null }] })}><Plus className="!size-3.5" /> {t("addStep")}</Button>
      </div>
      {d.routine_suggestion ? <p className="text-[12px] text-subtle">{t("routineIdea", { when: d.routine_suggestion })}</p> : null}
      <div className="flex justify-end"><Button variant="primary" onClick={submit} disabled={save.isPending || !d.name.trim() || !d.steps.length}>{t("save")}</Button></div>
    </div>
  );
}

/** While NOVA observes: a banner on every page; at the end, the review and the draft Skill. */
export function TeachBanner() {
  const t = useT(M);
  const lang = useLang();
  const { data } = useTeach();
  const { cancel, finish } = useTeachActions();
  const [review, setReview] = useState(false);
  const [outside, setOutside] = useState("");
  const [draft, setDraft] = useState<LearnedDraft | null>(null);
  const observed = data?.observed ?? [];
  const close = () => { setReview(false); setDraft(null); setOutside(""); };
  const create = async () => {
    try {
      setDraft(await finish.mutateAsync({ description: outside, lang }));
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : String(err));
    }
  };
  return (
    <>
      {data?.active ? (
        <motion.div initial={{ y: 40, opacity: 0 }} animate={{ y: 0, opacity: 1 }} className="fixed inset-x-3 bottom-20 z-50 mx-auto flex max-w-[640px] flex-wrap items-center gap-3 rounded-[16px] border border-accent/40 bg-surface px-4 py-3 shadow-panel md:bottom-6" data-testid="teach-banner" role="status">
          <span className="relative grid size-8 place-items-center rounded-full bg-accent-soft text-accent">
            <Eye className="size-4" />
            <span className="absolute inset-0 animate-ping rounded-full bg-accent/20" />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-[13.5px] font-medium">{t("watching")}</div>
            <div className="text-[12px] text-subtle">{t("observed", { n: observed.length })}</div>
          </div>
          <Button variant="ghost" size="sm" onClick={() => cancel.mutate()}>{t("cancel")}</Button>
          <Button variant="primary" size="sm" onClick={() => setReview(true)}>{t("finish")}</Button>
        </motion.div>
      ) : null}
      {review || draft ? (
        <Dialog open onOpenChange={(open) => !open && close()}>
          <DialogContent title={draft ? t("teach") : t("reviewTitle")} description={draft ? undefined : t("reviewHint")} className="max-h-[84vh] overflow-y-auto sm:w-[min(92vw,640px)]">
            {draft ? (
              <DraftEditor draft={draft} onDone={close} />
            ) : (
              <div className="space-y-3">
                {observed.length ? (
                  <ol className="space-y-1" data-testid="observed">
                    {observed.map((o, i) => (
                      <li key={i} className="flex gap-2 text-[13px]"><span className="tabular-nums text-subtle">{i + 1}.</span><span className="text-subtle">[{t(`k_${o.kind}`)}]</span><span className="text-text">{o.text}</span></li>
                    ))}
                  </ol>
                ) : <p className="text-[13px] text-subtle">{t("nothingYet")}</p>}
                <div className="space-y-1.5"><Label htmlFor="t-out">{t("outside")}</Label><Textarea id="t-out" rows={4} value={outside} onChange={(e) => setOutside(e.target.value)} placeholder={t("outsidePlaceholder")} /></div>
                <div className="flex justify-end"><Button variant="primary" onClick={create} disabled={finish.isPending}>{finish.isPending ? t("creating") : t("create")}</Button></div>
              </div>
            )}
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  );
}
