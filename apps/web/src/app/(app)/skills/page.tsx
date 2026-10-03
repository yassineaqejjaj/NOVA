"use client";

import { Badge, Button, cn, Input, Skeleton } from "@nova/ui";
import { AnimatePresence, motion } from "framer-motion";
import { Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Page, PageHeader } from "@/components/shell/page";
import { useSkill, useSkills } from "@/lib/api/hooks";
import { useComposer } from "@/stores/ui";

const CATEGORIES = ["strategy", "discovery", "prioritization", "definition", "delivery", "analysis", "communication"];

function SkillDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const { data: skill } = useSkill(id);
  const setDraft = useComposer((s) => s.setDraft);
  const router = useRouter();
  if (!skill) return <div className="p-5"><Skeleton className="h-40" /></div>;
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start gap-2 border-b border-border px-5 py-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-[12px] text-subtle capitalize">{skill.category} <Badge>v{skill.version}</Badge></div>
          <h2 className="mt-1 text-[16px] font-semibold">{skill.name}</h2>
        </div>
        <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close"><X /></Button>
      </div>
      <div className="flex-1 space-y-5 overflow-y-auto px-5 py-4 text-[13px]">
        <p className="text-muted">{skill.purpose}</p>
        <section>
          <h3 className="mb-1.5 text-[11.5px] font-medium uppercase tracking-wider text-subtle">Method · {skill.methodology.name}</h3>
          <ul className="list-disc space-y-1 pl-4 text-muted">{skill.methodology.principles.map((p) => <li key={p}>{p}</li>)}</ul>
          {skill.methodology.references.length ? <p className="mt-1.5 text-[12px] text-subtle">{skill.methodology.references.join(" · ")}</p> : null}
        </section>
        <section>
          <h3 className="mb-1.5 text-[11.5px] font-medium uppercase tracking-wider text-subtle">Workflow</h3>
          <ol className="space-y-1.5">{skill.steps.map((s, i) => <li key={s.id} className="flex gap-2"><span className="text-subtle">{i + 1}.</span><span className="text-text">{s.title}</span></li>)}</ol>
        </section>
        <section className="grid grid-cols-2 gap-3">
          <div><div className="text-[11.5px] text-subtle">Produces</div><div>{skill.artifact_type_name} ({skill.mode})</div></div>
          <div><div className="text-[11.5px] text-subtle">ORBIT context</div><div>{skill.expected_context.orbit_intent}{skill.expected_context.required ? " · required" : ""}</div></div>
          <div><div className="text-[11.5px] text-subtle">Tools</div><div>{skill.tools.join(", ") || "None"}</div></div>
          <div><div className="text-[11.5px] text-subtle">Inputs</div><div>{skill.inputs.map((i) => i.name + (i.required ? "*" : "")).join(", ") || "—"}</div></div>
        </section>
        <section>
          <h3 className="mb-1.5 text-[11.5px] font-medium uppercase tracking-wider text-subtle">Evaluated by FORGE on</h3>
          <ul className="space-y-1 text-muted">{skill.evaluation.criteria.map((c) => <li key={c.key}>{c.question}</li>)}</ul>
        </section>
        {skill.composes_with.length ? <p className="text-[12px] text-subtle">Often followed by: {skill.composes_with.join(", ")}</p> : null}
        <p className="font-mono text-[10.5px] text-subtle">{skill.content_hash.slice(0, 16)}</p>
      </div>
      <div className="border-t border-border px-5 py-3">
        <Button variant="primary" size="sm" onClick={() => { setDraft(`/${skill.id} `); router.push("/"); }}>Use this Skill</Button>
      </div>
    </div>
  );
}

export default function SkillsPage() {
  const { data: skills, isLoading } = useSkills();
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const filtered = (skills ?? []).filter((s) => !q || `${s.name} ${s.summary} ${s.triggers.join(" ")}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="flex min-h-screen">
      <div className="min-w-0 flex-1">
        <Page wide>
          <PageHeader title="Skills" description="Versioned product workflows NOVA chooses and combines for you. You never have to pick one — but you can." />
          <div className="relative mb-6 max-w-md">
            <Search className="absolute left-3 top-2.5 size-4 text-subtle" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search Skills" className="pl-9" />
          </div>
          {isLoading ? <Skeleton className="h-60" /> : null}
          <div className="space-y-8">
            {CATEGORIES.map((category) => {
              const list = filtered.filter((s) => s.category === category);
              if (!list.length) return null;
              return (
                <section key={category}>
                  <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">{category}</h2>
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {list.map((s) => (
                      <button key={s.id} onClick={() => setSelected(s.id)} className={cn("rounded-[12px] border border-border bg-surface px-3.5 py-3 text-left transition-colors hover:border-border-strong", selected === s.id && "border-accent/40")}>
                        <div className="flex items-center gap-2 text-[13.5px] font-medium">{s.name}<span className="ml-auto text-[11px] text-subtle">v{s.version}</span></div>
                        <p className="mt-0.5 line-clamp-2 text-[12.5px] text-muted">{s.summary}</p>
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
