"use client";

import { Badge, Button, cn, Input, Skeleton } from "@nova/ui";
import { AnimatePresence, motion } from "framer-motion";
import { Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { AgentAvatar } from "@/components/agents/sub-agents";
import { Page, PageHeader } from "@/components/shell/page";
import { useSkill, useSkills } from "@/lib/api/hooks";
import { AGENT_PROFILES, agentOf, AGENTS, type AgentProfile } from "@/lib/agents";
import { defineMessages, useLang, useT } from "@/lib/i18n";
import { skillArtifactTypeName, skillName, skillSummary } from "@/lib/i18n/catalog";
import { useComposer } from "@/stores/ui";

const CATEGORIES = ["strategy", "discovery", "prioritization", "definition", "delivery", "analysis", "communication"] as const;

const M = defineMessages({
  en: {
    cat_strategy: "strategy",
    cat_discovery: "discovery",
    cat_prioritization: "prioritization",
    cat_definition: "definition",
    cat_delivery: "delivery",
    cat_analysis: "analysis",
    cat_communication: "communication",
    close: "Close",
    allAgents: "All agents",
    carriedBy: "Carried out by",
    agentFilter: "Filter by agent",
    method: "Method · {name}",
    workflow: "Workflow",
    produces: "Produces",
    mode_create: "create",
    mode_update: "update",
    orbitContext: "ORBIT context",
    required: " · required",
    tools: "Tools",
    none: "None",
    inputs: "Inputs",
    evaluatedBy: "Evaluated by FORGE on",
    followedBy: "Often followed by: {skills}",
    useSkill: "Use this Skill",
    title: "Skills",
    description: "Versioned product workflows NOVA chooses and combines for you. You never have to pick one — but you can.",
    search: "Search Skills",
  },
  fr: {
    cat_strategy: "stratégie",
    cat_discovery: "découverte",
    cat_prioritization: "priorisation",
    cat_definition: "définition",
    cat_delivery: "livraison",
    cat_analysis: "analyse",
    cat_communication: "communication",
    close: "Fermer",
    allAgents: "Tous les agents",
    carriedBy: "Réalisée par",
    agentFilter: "Filtrer par agent",
    method: "Méthode · {name}",
    workflow: "Workflow",
    produces: "Produit",
    mode_create: "création",
    mode_update: "mise à jour",
    orbitContext: "Contexte ORBIT",
    required: " · requis",
    tools: "Outils",
    none: "Aucun",
    inputs: "Entrées",
    evaluatedBy: "Évalué par FORGE sur",
    followedBy: "Souvent suivie de : {skills}",
    useSkill: "Utiliser cette Skill",
    title: "Skills",
    description: "Des workflows produit versionnés que NOVA choisit et combine pour vous. Vous n’avez jamais à en choisir un — mais vous le pouvez.",
    search: "Rechercher des Skills",
  },
});
type Key = keyof typeof M.en;

function useCategoryLabel() {
  const t = useT(M);
  return (category: string) => ((CATEGORIES as readonly string[]).includes(category) ? t(`cat_${category}` as Key) : category);
}

function SkillDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: skill } = useSkill(id);
  const { data: skills } = useSkills();
  const t = useT(M);
  const lang = useLang();
  const categoryLabel = useCategoryLabel();
  const setDraft = useComposer((s) => s.setDraft);
  const router = useRouter();
  if (!skill) return <div className="p-5"><Skeleton className="h-40" /></div>;
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start gap-2 border-b border-border px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-[12px] text-subtle capitalize">{categoryLabel(skill.category)} <Badge>v{skill.version}</Badge></div>
          <h2 className="mt-1 text-[16px] font-semibold">{skillName(skill, lang)}</h2>
          <div className="mt-2 flex items-center gap-2 text-[12.5px] text-muted">
            <AgentAvatar profile={agentOf(skill.agent)} size={20} />
            <span>{t("carriedBy")} <span className="font-medium" style={{ color: AGENTS[agentOf(skill.agent)].color }}>{AGENTS[agentOf(skill.agent)].name[lang]}</span></span>
          </div>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label={t("close")}><X /></Button>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4 text-[13px]">
        <p className="text-muted">{skill.purpose}</p>
        <section>
          <h3 className="mb-1.5 text-[11.5px] font-medium uppercase tracking-wider text-subtle">{t("method", { name: skill.methodology.name })}</h3>
          <ul className="list-disc space-y-1 pl-4 text-muted">{skill.methodology.principles.map((p) => <li key={p}>{p}</li>)}</ul>
          {skill.methodology.references.length ? <p className="mt-1.5 text-[12px] text-subtle">{skill.methodology.references.join(" · ")}</p> : null}
        </section>
        <section>
          <h3 className="mb-1.5 text-[11.5px] font-medium uppercase tracking-wider text-subtle">{t("workflow")}</h3>
          <ol className="space-y-1.5">{skill.steps.map((s, i) => <li key={s.id} className="flex gap-2"><span className="text-subtle">{i + 1}.</span><span className="text-text">{s.title}</span></li>)}</ol>
        </section>
        <section className="grid grid-cols-2 gap-3">
          <div><div className="text-[11.5px] text-subtle">{t("produces")}</div><div>{skillArtifactTypeName(skill, lang)} ({t(`mode_${skill.mode}`)})</div></div>
          <div><div className="text-[11.5px] text-subtle">{t("orbitContext")}</div><div>{skill.expected_context.orbit_intent}{skill.expected_context.required ? t("required") : ""}</div></div>
          <div><div className="text-[11.5px] text-subtle">{t("tools")}</div><div>{skill.tools.join(", ") || t("none")}</div></div>
          <div><div className="text-[11.5px] text-subtle">{t("inputs")}</div><div>{skill.inputs.map((i) => i.name + (i.required ? "*" : "")).join(", ") || "—"}</div></div>
        </section>
        <section>
          <h3 className="mb-1.5 text-[11.5px] font-medium uppercase tracking-wider text-subtle">{t("evaluatedBy")}</h3>
          <ul className="space-y-1 text-muted">{skill.evaluation.criteria.map((c) => <li key={c.key}>{c.question}</li>)}</ul>
        </section>
        {skill.composes_with.length ? <p className="text-[12px] text-subtle">{t("followedBy", { skills: skill.composes_with.map((ref) => { const s = skills?.find((x) => x.id === ref); return s ? skillName(s, lang) : ref; }).join(", ") })}</p> : null}
        <p className="font-mono text-[10.5px] text-subtle">{skill.content_hash.slice(0, 16)}</p>
      </div>
      <div className="border-t border-border px-5 py-3">
        <Button variant="primary" size="sm" onClick={() => { setDraft(`/${skill.id} `); router.push("/"); }}>{t("useSkill")}</Button>
      </div>
    </div>
  );
}

export default function SkillsPage() {
  const { data: skills, isLoading } = useSkills();
  const t = useT(M);
  const lang = useLang();
  const categoryLabel = useCategoryLabel();
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [agent, setAgent] = useState<AgentProfile | null>(null);
  const count = (p: AgentProfile) => (skills ?? []).filter((s) => s.agent === p).length;
  const filtered = (skills ?? []).filter(
    (s) => (!agent || s.agent === agent) && (!q || `${s.name} ${skillName(s, lang)} ${s.summary} ${skillSummary(s, lang)} ${s.triggers.join(" ")}`.toLowerCase().includes(q.toLowerCase())),
  );
  return (
    <div className="flex min-h-screen">
      <div className="min-w-0 flex-1">
        <Page wide>
          <PageHeader title={t("title")} description={t("description")} />
          <div className="relative mb-6 max-w-md">
            <Search className="absolute left-3 top-2.5 size-4 text-subtle" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("search")} className="pl-9" />
          </div>
          <div role="radiogroup" aria-label={t("agentFilter")} className="-mt-2 mb-6 flex flex-wrap gap-2">
            <button role="radio" aria-checked={!agent} onClick={() => setAgent(null)} className={cn("rounded-full border px-3 py-1 text-[12.5px] transition-colors", !agent ? "border-accent/50 bg-accent-soft text-text" : "border-border text-muted hover:text-text")}>
              {t("allAgents")}
            </button>
            {AGENT_PROFILES.map((p) => (
              <button key={p} role="radio" aria-checked={agent === p} onClick={() => setAgent(agent === p ? null : p)} className={cn("inline-flex items-center gap-1.5 rounded-full border py-1 pl-1 pr-3 text-[12.5px] transition-colors", agent === p ? "border-accent/50 bg-accent-soft text-text" : "border-border text-muted hover:text-text")}>
                <AgentAvatar profile={p} size={20} /> {AGENTS[p].short[lang]} <span className="text-subtle">{count(p)}</span>
              </button>
            ))}
          </div>
          {isLoading ? <Skeleton className="h-60" /> : null}
          <div className="space-y-8">
            {CATEGORIES.map((category) => {
              const list = filtered.filter((s) => s.category === category);
              if (!list.length) return null;
              return (
                <section key={category}>
                  <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">{categoryLabel(category)}</h2>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {list.map((s) => (
                      <button key={s.id} onClick={() => setSelected(s.id)} className={cn("rounded-[12px] border border-border bg-surface px-3.5 py-3 text-left transition-colors hover:border-border-strong", selected === s.id && "border-accent/40")}>
                        <div className="flex items-center gap-2 text-[13.5px] font-medium">
                          <AgentAvatar profile={agentOf(s.agent)} size={18} />
                          <span className="min-w-0 truncate">{skillName(s, lang)}</span>
                          <span className="ml-auto text-[11px] text-subtle">v{s.version}</span>
                        </div>
                        <p className="mt-0.5 line-clamp-2 text-[12.5px] text-muted">{skillSummary(s, lang)}</p>
                      </button>
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        </Page>
      </div>
      <AnimatePresence>
        {selected ? (
          <motion.aside initial={{ opacity: 0, x: 24 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 24 }} transition={{ duration: 0.2 }} className="sticky top-0 h-screen w-[420px] shrink-0 border-l border-border bg-background">
            <SkillDetail id={selected} onClose={() => setSelected(null)} />
          </motion.aside>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
