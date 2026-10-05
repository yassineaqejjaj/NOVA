"use client";

import { Button, cn } from "@nova/ui";
import { ArrowRight, Check, Hand, Plus, Repeat, Target } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { GoalDialog } from "@/components/missions/goal-dialog";
import { InboxItemCard, MISSION_ORB, MissionChip, ProgressBar } from "@/components/missions/ui";
import { NovaOrb, ORB_LABEL } from "@/components/shell/nova-orb";
import { useVoiceAvailable } from "@/components/voice/voice-button";
import { api } from "@/lib/api/client";
import type { Today } from "@/lib/api/types";
import { defineMessages, useT } from "@/lib/i18n";
import { useComposer, useUi } from "@/stores/ui";

const M = defineMessages({
  en: {
    morning: "Good morning", afternoon: "Good afternoon", evening: "Good evening",
    workedOn: (v: { n: number }) => (v.n === 1 ? "I worked on 1 topic since your last visit." : `I worked on ${v.n} topics since your last visit.`),
    quiet: "Nothing new since your last visit — I’m ready when you are.",
    decisions: (v: { n: number }) => (v.n === 1 ? "1 decision needs your opinion" : `${v.n} decisions need your opinion`),
    openInbox: "Open the Inbox",
    more: (v: { n: number }) => `and ${v.n} more`,
    recommended: "What NOVA recommends today",
    allInInbox: "Everything in the Inbox",
    nothingRecommended: "Nothing urgent. Give NOVA a goal, it will figure out the work.",
    goals: "Your goals",
    newGoal: "Give NOVA a goal",
    goalHint: "Tell NOVA what you want to achieve. It will figure out the work.",
    routine: "routine",
    talk: "Talk to NOVA",
  },
  fr: {
    morning: "Bonjour", afternoon: "Bon après-midi", evening: "Bonsoir",
    workedOn: (v: { n: number }) => (v.n > 1 ? `J’ai travaillé sur ${v.n} sujets depuis votre dernière visite.` : "J’ai travaillé sur 1 sujet depuis votre dernière visite."),
    quiet: "Rien de nouveau depuis votre dernière visite — je suis prêt quand vous l’êtes.",
    decisions: (v: { n: number }) => (v.n > 1 ? `${v.n} décisions nécessitent votre avis` : "1 décision nécessite votre avis"),
    openInbox: "Ouvrir l’Inbox",
    more: (v: { n: number }) => `et ${v.n} autre${v.n > 1 ? "s" : ""}`,
    recommended: "Ce que NOVA recommande aujourd’hui",
    allInInbox: "Tout dans l’Inbox",
    nothingRecommended: "Rien d’urgent. Donnez un goal à NOVA, il s’occupe du travail.",
    goals: "Vos goals",
    newGoal: "Confier un goal à NOVA",
    goalHint: "Dites à NOVA ce que vous voulez atteindre. Il s’occupe du travail.",
    routine: "routine",
    talk: "Parler à NOVA",
  },
});

/** NOVA comes to the user: what it did since the last visit and what needs a decision. */
export function ProactiveHero({ today }: { today: Today }) {
  const t = useT(M);
  const voice = useVoiceAvailable();
  const openVoice = useUi((s) => s.openVoice);
  const state = today.nova.state;
  const [hello, setHello] = useState("");
  useEffect(() => {
    const h = new Date().getHours();
    setHello(t(h >= 5 && h < 12 ? "morning" : h >= 12 && h < 18 ? "afternoon" : "evening"));
  }, [t]);
  useEffect(() => {
    const id = setTimeout(() => void api.post("/today/seen").catch(() => undefined), 4000); // the next visit starts from now
    return () => clearTimeout(id);
  }, []);
  const worked = today.since.worked_on;
  const orb = (
    <NovaOrb state={state} size={112} reflection title={`NOVA — ${ORB_LABEL[state]}`} />
  );
  return (
    <section className="relative overflow-hidden rounded-[28px] bg-[radial-gradient(120%_140%_at_85%_10%,rgb(248_72_94/0.16),transparent_55%),linear-gradient(180deg,var(--surface),var(--surface-2))] px-6 py-7 md:px-9 md:py-8" data-testid="today-hero">
      <div className="flex flex-col-reverse gap-6 md:flex-row md:items-center">
        <div className="min-w-0 flex-1">
          <h1 className="text-[32px] font-semibold leading-[1.1] tracking-tight md:text-[40px]">
            {hello ? `${hello} ${today.user.first_name}.` : `${today.user.first_name}.`}
          </h1>
          <p className="mt-2 text-[16px] text-text/85" aria-live="polite">{today.since.count ? t("workedOn", { n: today.since.count }) : t("quiet")}</p>
          {worked.length ? (
            <ul className="mt-3 space-y-1">
              {worked.slice(0, 4).map((w) => (
                <li key={w.task_id}>
                  <Link href={w.conversation_id ? `/c/${w.conversation_id}` : `/work?task=${w.task_id}`} className="flex items-center gap-2 text-[14px] text-text/85 hover:text-accent">
                    <Check className="size-4 shrink-0 text-success" />
                    <span className="truncate">{w.title}</span>
                    {w.origin === "routine" ? <span className="inline-flex shrink-0 items-center gap-1 text-[11.5px] text-subtle"><Repeat className="size-3" /> {t("routine")}</span> : w.origin === "goal" ? <Target className="size-3 shrink-0 text-subtle" /> : null}
                  </Link>
                </li>
              ))}
              {worked.length > 4 ? <li className="pl-6 text-[12.5px] text-subtle">{t("more", { n: today.since.count - 4 })}</li> : null}
            </ul>
          ) : null}
          {today.since.decisions ? (
            <Link href="/inbox" className="mt-4 inline-flex items-center gap-2 rounded-full bg-warning/12 px-3.5 py-1.5 text-[13.5px] font-medium text-warning hover:bg-warning/20" data-testid="decisions-callout">
              <Hand className="size-4" /> {t("decisions", { n: today.since.decisions })} <ArrowRight className="size-3.5" />
            </Link>
          ) : null}
        </div>
        <div className="flex shrink-0 flex-col items-center gap-3 md:pr-4">
          {voice ? (
            <button type="button" onClick={() => openVoice({ conversationId: null, projectId: useComposer.getState().projectId })} aria-label={t("talk")} className="rounded-full outline-none transition-transform hover:scale-[1.03] focus-visible:ring-2 focus-visible:ring-accent">{orb}</button>
          ) : orb}
          <span className="mt-3 rounded-full bg-surface/80 px-3 py-1 text-[12px] font-medium text-muted backdrop-blur">{ORB_LABEL[state]}</span>
        </div>
      </div>
    </section>
  );
}

export function RecommendedToday({ today }: { today: Today }) {
  const t = useT(M);
  return (
    <section id="attention" aria-labelledby="recommended-title" className="scroll-mt-6">
      <div className="mb-1 flex items-center justify-between">
        <h2 id="recommended-title" className="text-[15px] font-semibold tracking-tight">{t("recommended")}</h2>
        <Link href="/inbox" className="text-[12.5px] text-subtle hover:text-accent">{t("allInInbox")} · {today.inbox.counts.total}</Link>
      </div>
      {today.recommended.length ? (
        <ol className="divide-y divide-border/70" data-testid="recommended">
          {today.recommended.map((item, i) => (
            <div key={item.id} className="flex gap-3">
              <span className="pt-4 text-[15px] font-semibold tabular-nums text-subtle">{i + 1}.</span>
              <div className="min-w-0 flex-1"><InboxItemCard item={item} large /></div>
            </div>
          ))}
        </ol>
      ) : (
        <p className="py-3 text-[13.5px] text-subtle">{t("nothingRecommended")}</p>
      )}
    </section>
  );
}

export function GoalsStrip({ today }: { today: Today }) {
  const t = useT(M);
  const [open, setOpen] = useState(false);
  return (
    <section aria-labelledby="goals-title">
      <div className="mb-2 flex items-center justify-between">
        <h2 id="goals-title" className="text-[15px] font-semibold tracking-tight">{t("goals")}</h2>
        <Button variant="secondary" size="sm" className="rounded-full" onClick={() => setOpen(true)}><Plus className="!size-3.5" /> {t("newGoal")}</Button>
      </div>
      {today.goals.length ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {today.goals.map((g) => (
            <Link key={g.id} href={`/goals?goal=${g.id}`} className="rounded-[14px] border border-border bg-surface px-3.5 py-3 transition-colors hover:border-accent/40" data-testid="today-goal">
              <div className="flex items-center gap-2.5">
                <NovaOrb state={MISSION_ORB[g.mission]} size={26} />
                <span className="min-w-0 flex-1 truncate text-[14px] font-medium">{g.title}</span>
                <span className="text-[13px] font-semibold tabular-nums">{g.progress.percent}%</span>
              </div>
              <ProgressBar percent={g.progress.percent} className="mt-2" />
              <div className="mt-1.5 flex items-center justify-between gap-2 text-[12px]">
                <MissionChip state={g.mission} />
                <span className="truncate text-subtle">{g.current?.title ?? g.next?.title ?? ""}</span>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <button onClick={() => setOpen(true)} className={cn("flex w-full items-center gap-3 rounded-[14px] border border-dashed border-border px-4 py-3.5 text-left text-[13.5px] text-muted hover:border-accent/40 hover:text-text")}>
          <Target className="size-4 text-accent" /> {t("goalHint")}
        </button>
      )}
      {open ? <GoalDialog open={open} onOpenChange={setOpen} /> : null}
    </section>
  );
}
