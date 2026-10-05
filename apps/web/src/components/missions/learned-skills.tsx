"use client";

import { Button } from "@nova/ui";
import { GraduationCap, Play, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { useLearnedSkills, useTeachActions } from "@/lib/api/missions";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    title: "Skills NOVA learned from you",
    hint: "Created with “Teach NOVA”. Run them here, with /name in the composer, or in a routine.",
    steps: (v: { n: number }) => (v.n === 1 ? "1 step" : `${v.n} steps`),
    uses: (v: { n: number }) => (v.n === 1 ? "used once" : `used ${v.n} times`),
    run: "Run", remove: "Delete", removed: "Skill deleted.",
  },
  fr: {
    title: "Les Skills que NOVA a apprises de vous",
    hint: "Créées avec « Apprendre à NOVA ». Lancez-les ici, avec /nom dans le composeur, ou dans une routine.",
    steps: (v: { n: number }) => (v.n > 1 ? `${v.n} étapes` : "1 étape"),
    uses: (v: { n: number }) => (v.n > 1 ? `utilisée ${v.n} fois` : v.n === 1 ? "utilisée 1 fois" : "jamais utilisée"),
    run: "Lancer", remove: "Supprimer", removed: "Skill supprimée.",
  },
});

export function LearnedSkills() {
  const t = useT(M);
  const router = useRouter();
  const { data } = useLearnedSkills();
  const { run, remove } = useTeachActions();
  if (!data?.length) return null;
  return (
    <section className="mb-8" data-testid="learned-skills">
      <h2 className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-wider text-subtle"><GraduationCap className="size-3.5" /> {t("title")}</h2>
      <p className="mb-2 mt-0.5 text-[12.5px] text-subtle">{t("hint")}</p>
      <ul className="grid gap-2 sm:grid-cols-2">
        {data.map((s) => (
          <li key={s.id} className="rounded-[12px] border border-accent/30 bg-accent-soft/30 px-3.5 py-3" data-testid="learned-skill">
            <div className="flex items-center gap-2">
              <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium">{s.name}</span>
              <code className="text-[11.5px] text-accent">/{s.slug}</code>
            </div>
            <p className="mt-0.5 line-clamp-2 text-[12.5px] text-muted">{s.description}</p>
            <ol className="mt-1.5 space-y-0.5 text-[12px] text-subtle">{s.steps.slice(0, 4).map((st, i) => <li key={i}>{i + 1}. {st.title}</li>)}</ol>
            <div className="mt-2 flex items-center gap-2 text-[11.5px] text-subtle">
              <span>{t("steps", { n: s.steps.length })} · {t("uses", { n: s.uses })}</span>
              <Button size="sm" variant="primary" className="ml-auto" disabled={run.isPending} onClick={() => run.mutate(s.id, { onSuccess: (r) => router.push(`/c/${r.conversation_id}`) })}><Play className="!size-3" /> {t("run")}</Button>
              <Button size="icon" variant="ghost" className="size-8 text-subtle" aria-label={t("remove")} onClick={() => remove.mutate(s.id, { onSuccess: () => toast(t("removed")) })}><Trash2 className="!size-3.5" /></Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
