"use client";

import { Button, cn, Input, Label } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ArrowLeft, ArrowRight, Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ProfilePicker } from "@/components/agents/profile-picker";
import { OrbitLink } from "@/components/orbit-link";
import { NovaMark } from "@/components/shell/nova-mark";
import { api } from "@/lib/api/client";
import { keys, useMe, useProjects } from "@/lib/api/hooks";
import type { AutonomyMode } from "@/lib/api/types";
import { agentOf, type AgentProfile } from "@/lib/agents";
import { autonomyOptions } from "@/lib/autonomy";
import { defineMessages, useLang, useT } from "@/lib/i18n";
import { useComposer } from "@/stores/ui";

const M = defineMessages({
  en: {
    meet: "Meet your NOVA",
    roleTitle: "What is your role?",
    roleHint: "NOVA adapts its methods and Artifacts to your work.",
    rolePlaceholder: "e.g. Head of AI, Product Manager, Product Owner",
    nameLabel: "Name your NOVA",
    profileTitle: "Which profile fits you best?",
    profileHint: "NOVA's specialist agent for your profile leads your work; the other agents join when a task needs them.",
    teamsTitle: "Which teams do you work with?",
    teamsHint: "Separate with commas.",
    teamsPlaceholder: "AI Platform, Design, Engineering",
    projectsTitle: "Which projects are relevant?",
    projectsPick: "Pick the ones you work on most.",
    projectsEmpty: "Projects appear once ORBIT is connected — you can do it in a moment.",
    methodsTitle: "Which product methods do you prefer?",
    methodsHint: "NOVA will favor them when several Skills fit.",
    autonomyTitle: "How much autonomy should NOVA have?",
    autonomyHint: "Changes to external systems always follow your company’s policy.",
    orbitTitle: "Connect NOVA to your context",
    orbitHint: "ORBIT holds your organization’s documents, decisions and backlog. NOVA reads them as you — never more.",
    ready: "Your {name} is ready.",
    readyHint: "Tell it what you want to achieve. It will find the context, the method and the workflow.",
    back: "Back",
    skip: "Skip for now",
    start: "Start working",
    continue: "Continue",
  },
  fr: {
    meet: "Faites connaissance avec votre NOVA",
    roleTitle: "Quel est votre rôle ?",
    roleHint: "NOVA adapte ses méthodes et ses Artefacts à votre travail.",
    rolePlaceholder: "ex. Head of AI, Product Manager, Product Owner",
    nameLabel: "Nommez votre NOVA",
    profileTitle: "Quel profil vous correspond le mieux ?",
    profileHint: "L’agent spécialiste de votre profil pilote votre travail ; les autres agents interviennent quand une tâche le demande.",
    teamsTitle: "Avec quelles équipes travaillez-vous ?",
    teamsHint: "Séparez-les par des virgules.",
    teamsPlaceholder: "Plateforme IA, Design, Ingénierie",
    projectsTitle: "Quels projets vous concernent ?",
    projectsPick: "Choisissez ceux sur lesquels vous travaillez le plus.",
    projectsEmpty: "Les projets apparaissent une fois ORBIT connecté — vous pourrez le faire dans un instant.",
    methodsTitle: "Quelles méthodes produit préférez-vous ?",
    methodsHint: "NOVA les privilégiera lorsque plusieurs compétences conviennent.",
    autonomyTitle: "Quel degré d’autonomie accorder à NOVA ?",
    autonomyHint: "Les modifications des systèmes externes suivent toujours la politique de votre entreprise.",
    orbitTitle: "Connectez NOVA à votre contexte",
    orbitHint: "ORBIT contient les documents, décisions et backlog de votre organisation. NOVA les consulte avec vos droits — jamais plus.",
    ready: "Votre {name} est prêt.",
    readyHint: "Dites-lui ce que vous voulez accomplir. Il trouvera le contexte, la méthode et le workflow.",
    back: "Retour",
    skip: "Passer pour l’instant",
    start: "Commencer",
    continue: "Continuer",
  },
});

const METHODS = ["RICE", "MoSCoW", "WSJF", "Jobs To Be Done", "Opportunity Solution Tree", "Story Mapping", "OKRs", "PRFAQ", "Kano"];
const STEPS = ["role", "profile", "teams", "projects", "methods", "autonomy", "orbit", "ready"] as const;

function Toggle({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick} className={cn("rounded-[10px] border px-3 py-1.5 text-[13px] transition-colors", active ? "border-accent/50 bg-accent-soft text-text" : "border-border text-muted hover:text-text")}>
      {children}
    </button>
  );
}

export default function WelcomePage() {
  const router = useRouter();
  const t = useT(M);
  const lang = useLang();
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
  const [profile, setProfile] = useState<AgentProfile>("product");
  const setDefaultProject = useComposer((s) => s.setProject);
  useEffect(() => { if (me) { setRole(me.title || me.preferences.role || ""); setNovaName(me.preferences.nova_name); setProfile(agentOf(me.preferences.profile)); } }, [me]);

  const finish = useMutation({
    mutationFn: () =>
      api.post("/me/onboarding", {
        title: role, role, nova_name: novaName, teams: teams.split(",").map((t) => t.trim()).filter(Boolean),
        preferred_methods: methods, default_autonomy: autonomy, profile,
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
            <div className="text-[12px] uppercase tracking-wider text-subtle">{t("meet")}</div>
            <div className="mt-1 flex gap-1">
              {STEPS.map((s, i) => <span key={s} className={cn("h-1 w-6 rounded-full", i <= step ? "bg-accent" : "bg-surface-3")} />)}
            </div>
          </div>
        </div>
        <AnimatePresence mode="wait">
          <motion.div key={current} initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -12 }} transition={{ duration: 0.2 }} className="min-h-[260px]">
            {current === "role" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">{t("roleTitle")}</h1>
                <p className="mt-1 text-muted">{t("roleHint")}</p>
                <Input autoFocus className="mt-6 h-11 text-[15px]" value={role} onChange={(e) => setRole(e.target.value)} placeholder={t("rolePlaceholder")} />
                <Label htmlFor="nova-name" className="mt-5 block">{t("nameLabel")}</Label>
                <Input id="nova-name" className="mt-1.5" value={novaName} onChange={(e) => setNovaName(e.target.value)} />
              </>
            ) : current === "profile" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">{t("profileTitle")}</h1>
                <p className="mt-1 text-muted">{t("profileHint")}</p>
                <div className="mt-6"><ProfilePicker value={profile} onChange={setProfile} /></div>
              </>
            ) : current === "teams" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">{t("teamsTitle")}</h1>
                <p className="mt-1 text-muted">{t("teamsHint")}</p>
                <Input autoFocus className="mt-6 h-11 text-[15px]" value={teams} onChange={(e) => setTeams(e.target.value)} placeholder={t("teamsPlaceholder")} />
              </>
            ) : current === "projects" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">{t("projectsTitle")}</h1>
                <p className="mt-1 text-muted">{projects?.length ? t("projectsPick") : t("projectsEmpty")}</p>
                <div className="mt-6 flex flex-wrap gap-2">
                  {(projects ?? []).map((p) => <Toggle key={p.id} active={focus.includes(p.id)} onClick={() => toggle(focus, setFocus, p.id)}>{p.name}</Toggle>)}
                </div>
              </>
            ) : current === "methods" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">{t("methodsTitle")}</h1>
                <p className="mt-1 text-muted">{t("methodsHint")}</p>
                <div className="mt-6 flex flex-wrap gap-2">
                  {METHODS.map((m) => <Toggle key={m} active={methods.includes(m)} onClick={() => toggle(methods, setMethods, m)}>{m}</Toggle>)}
                </div>
              </>
            ) : current === "autonomy" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">{t("autonomyTitle")}</h1>
                <p className="mt-1 text-muted">{t("autonomyHint")}</p>
                <div className="mt-6 space-y-2">
                  {autonomyOptions(lang).map((a) => (
                    <button key={a.value} type="button" onClick={() => setAutonomy(a.value)} className={cn("flex w-full items-center gap-3 rounded-[12px] border px-4 py-3 text-left", autonomy === a.value ? "border-accent/50 bg-accent-soft" : "border-border hover:border-border-strong")}>
                      <span className={cn("flex size-4 items-center justify-center rounded-full border", autonomy === a.value ? "border-accent bg-accent text-accent-fg" : "border-subtle")}>{autonomy === a.value ? <Check className="size-3" /> : null}</span>
                      <span><span className="block text-[14px]">{a.label}</span><span className="block text-[12.5px] text-subtle">{a.hint}</span></span>
                    </button>
                  ))}
                </div>
              </>
            ) : current === "orbit" ? (
              <>
                <h1 className="text-[24px] font-semibold tracking-tight">{t("orbitTitle")}</h1>
                <p className="mb-6 mt-1 text-muted">{t("orbitHint")}</p>
                <OrbitLink identity={me?.orbit} onLinked={next} />
              </>
            ) : (
              <div className="pt-6 text-center">
                <NovaMark size={44} className="mx-auto" />
                <h1 className="mt-6 text-[26px] font-semibold tracking-tight">{t("ready", { name: novaName })}</h1>
                <p className="mt-2 text-muted">{t("readyHint")}</p>
              </div>
            )}
          </motion.div>
        </AnimatePresence>
        <div className="mt-8 flex items-center">
          {step > 0 ? <Button variant="ghost" onClick={back}><ArrowLeft /> {t("back")}</Button> : null}
          <div className="ml-auto flex gap-2">
            {current === "orbit" ? <Button variant="ghost" onClick={next}>{t("skip")}</Button> : null}
            {current === "ready" ? (
              <Button variant="primary" size="lg" onClick={() => finish.mutate()} disabled={finish.isPending}>{t("start")}</Button>
            ) : current !== "orbit" ? (
              <Button variant="primary" onClick={next} disabled={current === "role" && !role.trim()}>{t("continue")} <ArrowRight /></Button>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
