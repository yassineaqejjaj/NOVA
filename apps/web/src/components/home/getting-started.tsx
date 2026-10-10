"use client";

import { Button, cn } from "@nova/ui";
import { ArrowRight, Check, X } from "lucide-react";
import Link from "next/link";

import { ProgressBar } from "@/components/missions/ui";
import { useArtifacts, useConversations, useMe } from "@/lib/api/hooks";
import type { Today } from "@/lib/api/types";
import { defineMessages, useT } from "@/lib/i18n";
import { useUi } from "@/stores/ui";

const M = defineMessages({
  en: {
    title: "Get started with NOVA",
    hint: "Four minutes to your first deliverable.",
    progress: "{done} of {total} done",
    dismiss: "Hide the checklist",
    allDone: "You're all set — NOVA is ready for real work.",
    orbit: "Connect ORBIT",
    orbitHint: "Give NOVA your documents, decisions and backlog.",
    request: "Make your first request",
    requestHint: "Say what you want to get done, in your own words.",
    artifact: "Get your first Artifact",
    artifactHint: "A PRD, a backlog, a sprint plan — editable and versioned.",
    goal: "Give NOVA a goal",
    goalHint: "NOVA works out the steps and keeps you posted.",
    skills: "Browse the Skills",
    skillsHint: "See the workflows NOVA can run for you.",
  },
  fr: {
    title: "Premiers pas avec NOVA",
    hint: "Quatre minutes pour votre premier livrable.",
    progress: "{done} sur {total} terminées",
    dismiss: "Masquer la checklist",
    allDone: "Tout est prêt — NOVA peut passer au vrai travail.",
    orbit: "Connecter ORBIT",
    orbitHint: "Donnez à NOVA vos documents, décisions et backlog.",
    request: "Faites votre première demande",
    requestHint: "Dites ce que vous voulez accomplir, avec vos mots.",
    artifact: "Obtenez votre premier Artefact",
    artifactHint: "Un PRD, un backlog, un plan de sprint — modifiable et versionné.",
    goal: "Confiez un objectif à NOVA",
    goalHint: "NOVA détermine les étapes et vous tient au courant.",
    skills: "Parcourir les Skills",
    skillsHint: "Découvrez les workflows que NOVA peut exécuter pour vous.",
  },
});

/**
 * New-user checklist on Home. Progress is derived from what the user has actually done (nothing to sync);
 * only "hidden" and "visited the Skills" live in the browser, per user.
 */
export function GettingStarted({ today }: { today: Today }) {
  const t = useT(M);
  const { data: me } = useMe();
  const { data: conversations } = useConversations();
  const { data: artifacts } = useArtifacts({});
  const dismissed = useUi((s) => s.startedDismissed);
  const skillsOpened = useUi((s) => s.skillsOpened);
  const dismiss = useUi((s) => s.dismissStarted);
  const markSkills = useUi((s) => s.markSkillsOpened);

  const userId = me?.id;
  // Wait for the lists: a returning user must never see the checklist flash while they load.
  if (!userId || !conversations || !artifacts || dismissed.includes(userId)) return null;

  const steps = [
    { id: "orbit", done: today.context.linked, href: "/settings#orbit" },
    { id: "request", done: conversations.length > 0, href: "#composer" },
    { id: "artifact", done: artifacts.length > 0, href: "#composer" },
    { id: "goal", done: today.goals.length > 0, href: "/goals" },
    { id: "skills", done: skillsOpened.includes(userId), href: "/skills", onOpen: () => markSkills(userId) },
  ] as const;
  const done = steps.filter((s) => s.done).length;
  const complete = done === steps.length;
  // The "request" and "artifact" steps both start in the composer right above.
  const focusComposer = () => {
    const field = document.getElementById("nova-composer");
    field?.scrollIntoView({ behavior: "smooth", block: "center" });
    field?.focus({ preventScroll: true });
  };

  return (
    <section aria-label={t("title")} className="mt-6 rounded-[20px] bg-surface-2/60 p-5">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold">{t("title")}</h2>
          <p className="mt-0.5 text-[12.5px] text-muted">{complete ? t("allDone") : t("hint")}</p>
        </div>
        <button type="button" onClick={() => dismiss(userId)} aria-label={t("dismiss")} title={t("dismiss")} className="rounded-md p-1 text-subtle transition-colors hover:text-text">
          <X className="size-4" />
        </button>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <ProgressBar percent={(done / steps.length) * 100} className="flex-1" />
        <span className="text-[12px] tabular-nums text-subtle">{t("progress", { done, total: steps.length })}</span>
      </div>
      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {steps.map((s) => {
          const body = (
            <>
              <span className={cn("mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full border", s.done ? "border-accent bg-accent text-accent-fg" : "border-subtle")}>
                {s.done ? <Check className="size-3" /> : null}
              </span>
              <span className="min-w-0 flex-1">
                <span className={cn("block text-[13.5px] font-medium", s.done && "text-muted line-through decoration-subtle")}>{t(s.id)}</span>
                <span className="block text-[12px] text-subtle">{t(`${s.id}Hint` as `${typeof s.id}Hint`)}</span>
              </span>
              {s.done ? null : <ArrowRight className="mt-1 size-3.5 shrink-0 text-subtle" />}
            </>
          );
          const cls = "flex items-start gap-3 rounded-[14px] bg-surface px-3.5 py-3 text-left transition-colors hover:bg-surface-3/60";
          return (
            <li key={s.id}>
              {s.href.startsWith("#") ? (
                <button type="button" className={cn(cls, "w-full")} onClick={focusComposer}>{body}</button>
              ) : (
                <Link href={s.href} className={cls} onClick={"onOpen" in s ? s.onOpen : undefined}>{body}</Link>
              )}
            </li>
          );
        })}
      </ul>
      {complete ? <Button variant="ghost" size="sm" className="mt-3" onClick={() => dismiss(userId)}>{t("dismiss")}</Button> : null}
    </section>
  );
}
