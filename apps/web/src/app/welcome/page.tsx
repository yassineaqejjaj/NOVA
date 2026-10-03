"use client";

import { Button, cn, Input, Label } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { OrbitLink } from "@/components/orbit-link";
import { NovaMark } from "@/components/shell/nova-mark";
import { api } from "@/lib/api/client";
import { keys, useMe, useProjects } from "@/lib/api/hooks";
import type { AutonomyMode } from "@/lib/api/types";
import { AUTONOMY } from "@/lib/autonomy";
import { useComposer } from "@/stores/ui";

const METHODS = ["RICE", "MoSCoW", "WSJF", "Jobs To Be Done", "Opportunity Solution Tree", "Story Mapping", "OKRs", "PRFAQ", "Kano"];
const STEPS = ["role", "teams", "projects", "methods", "autonomy", "orbit", "ready"] as const;

function Toggle({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={cn("rounded-[10px] border px-3 py-1.5 text-[13px] transition-colors", active ? "border-accent/50 bg-accent-soft text-text" : "border-border text-muted hover:text-text")}>
      {children}
    </button>
  );
}

export default function WelcomePage() {
  const router = useRouter();
  const client = useQueryClient();
  const { data: me } = useMe();
  const { data: projects } = useProjects();
  const [step, setStep] = useState(0);
  const [role, setRole] = useState("");
  const [teams, setTeams] = useState("");
  const [focus, setFocus] = useState<string[]>([]);
  const [methods, setMethods] = useState<string[]>([]);
  const [autonomy, setAutonomy] = useState<AutonomyMode>("assist");
  const [novaName, setNovaName] = useState("NOVA");
  const setDefaultProject = useComposer((s) => s.setProject);
  useEffect(() => { if (me) { setRole(me.title || me.preferences.role || ""); setNovaName(me.preferences.nova_name); } }, [me]);

  const finish = useMutation({
    mutationFn: () =>
      api.post("/me/onboarding", {
        title: role, role, nova_name: novaName, teams: teams.split(",").map((t) => t.trim()).filter(Boolean),
        preferred_methods: methods, default_autonomy: autonomy,
      }),
    onSuccess: async () => {
      if (focus[0]) setDefaultProject(focus[0]); // the composer starts on your main project
      await client.invalidateQueries({ queryKey: keys.me });
      router.replace("/");
    },
  });

  const current = STEPS[step]!;
  const next = () => setStep((s) => Math.min(s + 1, STEPS.length - 1));
  const back = () => setStep((s) => Math.max(s - 1, 0));
  const toggle = (list: string[], set: (v: string[]) => void, value: string) => set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);

  return (
    <div className="flex min-h-screen items-center justify-center px-6">
      <div className="w-full max-w-[560px]">
        <div className="mb-8 flex items-center gap-3">
          <NovaMark size={28} phase={current === "ready" ? "completed" : "idle"} />
          <div>
            <div className="text-[12px] uppercase tracking-wider text-subtle">Meet your NOVA</div>
            <div className="mt-1 flex gap-1">
              {STEPS.map((s, i) => <span key={s} className={cn("h-1 w-6 rounded-full", i <= step ? "bg-accent" : "bg-surface-3")} />)}
            </div>
          </div>
        </div>
        <AnimatePresence mode="wait">
          <motion.div key={current} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.2 }} className="min-h-[260px]">
            {current === "role" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">What is your role?</h1>
                <p className="mt-1 text-muted">NOVA adapts its methods and Artifacts to your work.</p>
                <Input autoFocus className="mt-6 h-11 text-[15px]" value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. Head of AI, Product Manager, Product Owner" />
                <Label htmlFor="nova-name" className="mt-5 block">Name your NOVA</Label>
                <Input id="nova-name" className="mt-1.5" value={novaName} onChange={(e) => setNovaName(e.target.value)} />
              </>
            ) : current === "teams" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">Which teams do you work with?</h1>
                <p className="mt-1 text-muted">Separate with commas.</p>
                <Input autoFocus className="mt-6 h-11 text-[15px]" value={teams} onChange={(e) => setTeams(e.target.value)} placeholder="AI Platform, Design, Engineering" />
              </>
            ) : current === "projects" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">Which projects are relevant?</h1>
                <p className="mt-1 text-muted">{projects?.length ? "Pick the ones you work on most." : "Projects appear once ORBIT is connected — you can do it in a moment."}</p>
                <div className="mt-6 flex flex-wrap gap-2">
                  {(projects ?? []).map((p) => <Toggle key={p.id} active={focus.includes(p.id)} onClick={() => toggle(focus, setFocus, p.id)}>{p.name}</Toggle>)}
                </div>
              </>
            ) : current === "methods" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">Which product methods do you prefer?</h1>
                <p className="mt-1 text-muted">NOVA will favor them when several Skills fit.</p>
                <div className="mt-6 flex flex-wrap gap-2">
                  {METHODS.map((m) => <Toggle key={m} active={methods.includes(m)} onClick={() => toggle(methods, setMethods, m)}>{m}</Toggle>)}
                </div>
              </>
            ) : current === "autonomy" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">How much autonomy should NOVA have?</h1>
                <p className="mt-1 text-muted">Changes to external systems always follow your company’s policy.</p>
                <div className="mt-6 space-y-2">
                  {AUTONOMY.map((a) => (
                    <button key={a.value} type="button" onClick={() => setAutonomy(a.value)} className={cn("flex w-full items-center gap-3 rounded-[12px] border px-4 py-3 text-left", autonomy === a.value ? "border-accent/50 bg-accent-soft" : "border-border hover:border-border-strong")}>
                      <span className={cn("flex size-4 items-center justify-center rounded-full border", autonomy === a.value ? "border-accent bg-accent text-accent-fg" : "border-subtle")}>{autonomy === a.value ? <Check className="size-3" /> : null}</span>
                      <span><span className="block text-[14px]">{a.label}</span><span className="block text-[12.5px] text-subtle">{a.hint}</span></span>
                    </button>
                  ))}
                </div>
              </>
            ) : current === "orbit" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">Connect NOVA to your context</h1>
                <p className="mb-6 mt-1 text-muted">ORBIT holds your organization’s documents, decisions and backlog. NOVA reads them as you — never more.</p>
                <OrbitLink identity={me?.orbit} onLinked={next} />
              </>
            ) : (
              <div className="pt-6 text-center">
                <NovaMark size={44} className="mx-auto" />
                <h1 className="mt-6 text-[26px] font-semibold tracking-tight">Your {novaName} is ready.</h1>
                <p className="mt-2 text-muted">Tell it what you want to achieve. It will find the context, the method and the workflow.</p>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
        <div className="mt-8 flex items-center">
          {step > 0 ? <Button variant="ghost" onClick={back}><ArrowLeft /> Back</Button> : null}
          <div className="ml-auto flex gap-2">
            {current === "orbit" ? <Button variant="ghost" onClick={next}>Skip for now</Button> : null}
            {current === "ready" ? (
              <Button variant="primary" size="lg" onClick={() => finish.mutate()} disabled={finish.isPending}>Start working</Button>
            ) : current !== "orbit" ? (
              <Button variant="primary" onClick={next} disabled={current === "role" && !role.trim()}>Continue <ArrowRight /></Button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
