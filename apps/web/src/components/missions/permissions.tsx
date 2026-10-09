"use client";

import { Card, cn } from "@nova/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import { defineMessages, useT } from "@/lib/i18n";

import { AutonomyLevels } from "./ui";

type Perm = "always" | "ask" | "never";
type Level = "observe" | "suggest" | "assist" | "execute_with_approval" | "execute_automatically";
interface Matrix {
  actions: { id: "orbit.read" | "artifacts.create" | "artifacts.update" | "orbit.write"; defaults: Record<Level, Perm> }[];
  values: Record<string, Perm>;
  default_autonomy: Level;
  external_writes_need_approval: boolean;
  connectors: { id: "jira" | "slack" | "analytics"; available: boolean }[];
}

const M = defineMessages({
  en: {
    title: "Autonomy & permissions",
    hint: "Trust grows step by step: choose how far NOVA goes on its own, then refine each action. Company policy always applies.",
    level: "Default autonomy (conversations, goals and routines)",
    action: "Action",
    "orbit.read": "Read the project context (ORBIT)",
    "artifacts.create": "Create an Artifact",
    "artifacts.update": "Change an existing Artifact",
    "orbit.write": "Write to ORBIT (memories, documents)",
    always: "Always", ask: "Ask", never: "Never",
    byLevel: "follows the level", reset: "Reset",
    saved: "Permissions updated.",
    orgNote: "Your company requires approval for changes to external systems: “Always” still asks for them.",
    connectors: "Connectors", soon: "Soon",
    jira: "Jira — read, create and update stories", slack: "Slack — read channels, prepare and send messages", analytics: "Analytics — read product metrics",
  },
  fr: {
    title: "Autonomie & permissions",
    hint: "La confiance se construit progressivement : choisissez jusqu’où NOVA agit seul, puis affinez action par action. La politique de l’entreprise s’applique toujours.",
    level: "Autonomie par défaut (conversations, objectifs et routines)",
    action: "Action",
    "orbit.read": "Lire le contexte projet (ORBIT)",
    "artifacts.create": "Créer un Artefact",
    "artifacts.update": "Modifier un Artefact existant",
    "orbit.write": "Écrire dans ORBIT (mémoires, documents)",
    always: "Toujours", ask: "Demander", never: "Jamais",
    byLevel: "selon le niveau", reset: "Réinitialiser",
    saved: "Permissions mises à jour.",
    orgNote: "Votre entreprise exige une validation pour toute modification des systèmes externes : « Toujours » la demande quand même.",
    connectors: "Connecteurs", soon: "Bientôt",
    jira: "Jira — lire, créer et modifier des stories", slack: "Slack — lire les canaux, préparer et envoyer des messages", analytics: "Analytics — lire les métriques produit",
  },
});

const PERMS: Perm[] = ["always", "ask", "never"];

export function PermissionsCard() {
  const t = useT(M);
  const client = useQueryClient();
  const { data } = useQuery({ queryKey: ["permissions"], queryFn: () => api.get<Matrix>("/me/permissions") });
  const save = useMutation({
    mutationFn: (patch: { action_permissions?: Record<string, Perm>; default_autonomy?: Level }) => api.patch("/me/preferences", patch),
    onSuccess: () => {
      toast(t("saved"));
      void client.invalidateQueries({ queryKey: ["permissions"] });
      void client.invalidateQueries({ queryKey: keys.me });
    },
  });
  if (!data) return null;
  const level = data.default_autonomy;
  const set = (action: string, value: Perm | null) => {
    const next = { ...data.values };
    if (value === null) delete next[action];
    else next[action] = value;
    save.mutate({ action_permissions: next });
  };
  return (
    <Card className="p-5" id="permissions">
      <h3 className="text-[15px] font-semibold">{t("title")}</h3>
      <p className="mt-0.5 text-[13px] text-muted">{t("hint")}</p>
      <div className="mt-4 space-y-1.5">
        <div className="text-[12.5px] font-medium text-muted">{t("level")}</div>
        <AutonomyLevels value={level} onChange={(v) => save.mutate({ default_autonomy: v })} includeAssist />
      </div>
      <table className="mt-5 w-full text-[13px]" aria-label={t("title")}>
        <thead>
          <tr className="text-left text-[11.5px] uppercase tracking-wider text-subtle">
            <th className="pb-2 font-medium">{t("action")}</th>
            <th className="pb-2 text-right font-medium" />
          </tr>
        </thead>
        <tbody className="divide-y divide-border/70">
          {data.actions.map((a) => {
            const explicit = data.values[a.id];
            const effective = explicit ?? a.defaults[level];
            return (
              <tr key={a.id} data-action={a.id}>
                <td className="py-2.5 pr-3">
                  <div className="text-text">{t(a.id)}</div>
                  <div className="text-[11.5px] text-subtle">{explicit ? <button className="text-accent hover:underline" onClick={() => set(a.id, null)}>{t("reset")}</button> : t("byLevel")}</div>
                </td>
                <td className="py-2.5 text-right">
                  <div role="radiogroup" aria-label={t(a.id)} className="inline-flex rounded-full border border-border p-0.5">
                    {PERMS.map((p) => (
                      <button key={p} role="radio" aria-checked={effective === p} onClick={() => set(a.id, p)} disabled={save.isPending} className={cn("rounded-full px-2.5 py-1 text-[12px] transition-colors", effective === p ? (p === "never" ? "bg-danger/15 text-danger" : p === "ask" ? "bg-warning/15 text-warning" : "bg-success/15 text-success") : "text-muted hover:text-text")}>
                        {t(p)}
                      </button>
                    ))}
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {data.external_writes_need_approval ? <p className="mt-2 text-[12px] text-subtle">{t("orgNote")}</p> : null}
      <div className="mt-5">
        <div className="mb-1.5 text-[12.5px] font-medium text-muted">{t("connectors")}</div>
        <ul className="space-y-1.5">
          {data.connectors.map((c) => (
            <li key={c.id} className="flex items-center justify-between rounded-[10px] border border-dashed border-border px-3 py-2 text-[13px] text-muted">
              <span>{t(c.id)}</span>
              <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-semibold text-accent">{t("soon")}</span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}
