"use client";

import { Badge, Button, cn, Dialog, DialogContent, Skeleton } from "@nova/ui";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDashed, ExternalLink, FileText, ShieldCheck } from "lucide-react";

import { api } from "@/lib/api/client";
import { useArtifact, useResume } from "@/lib/api/hooks";
import { localizeCheck } from "@/components/artifact/document.messages";
import type { ArtifactContent, ArtifactItem, ArtifactTypeDef, QualityCheck, SectionDiff } from "@/lib/api/types";
import { defineMessages, useLang, useT } from "@/lib/i18n";
import { sectionTitle, useCatalogNames } from "@/lib/i18n/catalog";

import { systemLabel } from "./blocks.messages";

const M = defineMessages({
  en: {
    whatWillHappen: "What will happen",
    impact: "Impact",
    preview: "Preview of changes",
    qualityCheck: "Quality check",
    becomesCurrent: (v: { version: number | null; title: string }) => `Version ${v.version} of “${v.title}” becomes the current version.`,
    staysInHistory: "Version {version} stays in the history — you can compare or restore it at any time.",
    sectionsChanged: "Sections changed",
    itemsAdded: "Items added",
    itemsUpdated: "Items updated",
    itemsRemoved: "Items removed",
    colItem: "Item",
    colSection: "Section",
    colChange: "Change",
    colPriority: "Priority",
    change_New: "New",
    change_Updated: "Updated",
    change_Removed: "Removed",
    change_Rewritten: "Rewritten",
    sectionText: "Section text",
    noChange: "No content change.",
    novaCalls: "NOVA calls",
    aTool: "a tool",
    externalWarning: "This changes data outside NOVA and may not be reversible from here.",
    cancel: "Cancel",
    reject: "Reject",
    approve: "Approve",
    approveAll: "Approve all",
  },
  fr: {
    whatWillHappen: "Ce qui va se passer",
    impact: "Impact",
    preview: "Aperçu des modifications",
    qualityCheck: "Contrôle qualité",
    becomesCurrent: (v: { version: number | null; title: string }) => `La version ${v.version} de « ${v.title} » devient la version courante.`,
    staysInHistory: "La version {version} reste dans l’historique — vous pouvez la comparer ou la restaurer à tout moment.",
    sectionsChanged: "Sections modifiées",
    itemsAdded: "Éléments ajoutés",
    itemsUpdated: "Éléments mis à jour",
    itemsRemoved: "Éléments supprimés",
    colItem: "Élément",
    colSection: "Section",
    colChange: "Modification",
    colPriority: "Priorité",
    change_New: "Nouveau",
    change_Updated: "Mis à jour",
    change_Removed: "Supprimé",
    change_Rewritten: "Réécrit",
    sectionText: "Texte de la section",
    noChange: "Aucune modification de contenu.",
    novaCalls: "NOVA appelle",
    aTool: "un outil",
    externalWarning: "Cette action modifie des données en dehors de NOVA et pourrait ne pas être réversible depuis ici.",
    cancel: "Annuler",
    reject: "Rejeter",
    approve: "Approuver",
    approveAll: "Tout approuver",
  },
});

export interface ApprovalData {
  id: string;
  action: "confirm_workflow" | "apply_artifact_changes" | "external_write";
  title: string;
  description: string;
  status: string;
  artifact_id?: string | null;
  proposed_version?: number | null;
  tool_request?: { tool: string; arguments: Record<string, unknown>; reason: string } | null;
}

interface PreviewRow {
  key: string;
  title: string;
  section: string;
  change: "New" | "Updated" | "Removed" | "Rewritten";
  priority?: string;
}

const CHANGE_TONE: Record<PreviewRow["change"], "success" | "accent" | "danger" | "neutral"> = {
  New: "success",
  Updated: "accent",
  Removed: "danger",
  Rewritten: "neutral",
};

function findItem(content: ArtifactContent | undefined, section: string, id: string): ArtifactItem | undefined {
  return content?.sections[section]?.items.find((i) => i.id === id);
}

function priorityOf(item: ArtifactItem | undefined): string | undefined {
  const value = item?.attributes?.priority ?? item?.attributes?.moscow ?? item?.attributes?.severity;
  return typeof value === "string" || typeof value === "number" ? String(value) : undefined;
}

function Heading({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-2 text-[13px] font-semibold text-text">{children}</h3>;
}

function QualityList({ checks, definition }: { checks: QualityCheck[]; definition: ArtifactTypeDef }) {
  const lang = useLang();
  // The API computes the checks in English; known labels and details are localized.
  return (
    <ul className="space-y-1.5">
      {checks.map((c) => ({ ...c, ...localizeCheck(c, definition, lang) })).map((c) => (
        <li key={c.key} className="flex items-start gap-2 text-[13px]">
          {c.status === "pass" ? (
            <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
          ) : c.status === "warn" ? (
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" />
          ) : (
            <CircleDashed className="mt-0.5 size-4 shrink-0 text-subtle" />
          )}
          <span>
            {c.label}
            {c.detail ? <span className="text-subtle"> · {c.detail}</span> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function ArtifactChanges({ approval }: { approval: ApprovalData }) {
  const t = useT(M);
  const lang = useLang();
  const artifactId = approval.artifact_id ?? null;
  const proposedVersion = approval.proposed_version ?? null;
  const { data: current } = useArtifact(artifactId);
  const { data: proposed } = useArtifact(artifactId, proposedVersion);
  const diff = useQuery({
    queryKey: ["artifact-compare", artifactId, current?.version, proposedVersion],
    queryFn: () => api.get<{ sections: SectionDiff[] }>(`/artifacts/${artifactId}/compare?from=${current!.version}&to=${proposedVersion}`),
    enabled: !!artifactId && !!current && !!proposedVersion,
  });
  if (!current || !proposed || !diff.data) return <div className="space-y-3"><Skeleton className="h-20" /><Skeleton className="h-32" /></div>;

  const titles = Object.fromEntries(proposed.definition.sections.map((s) => [s.key, sectionTitle(proposed.definition, s, lang)]));
  const changed = diff.data.sections.filter((s) => s.status !== "unchanged");
  const rows: PreviewRow[] = changed.flatMap((s) => {
    const section = titles[s.key] ?? s.key;
    const items: PreviewRow[] = [
      ...s.added_items.map((id) => {
        const item = findItem(proposed.content, s.key, id);
        return { key: `a-${id}`, title: item?.title ?? id, section, change: "New" as const, priority: priorityOf(item) };
      }),
      ...s.changed_items.map((id) => {
        const item = findItem(proposed.content, s.key, id);
        return { key: `c-${id}`, title: item?.title ?? id, section, change: "Updated" as const, priority: priorityOf(item) };
      }),
      ...s.removed_items.map((id) => ({ key: `r-${id}`, title: findItem(current.content, s.key, id)?.title ?? id, section, change: "Removed" as const })),
    ];
    return items.length ? items : [{ key: `s-${s.key}`, title: s.after_text.slice(0, 90) || t("sectionText"), section, change: "Rewritten" as const }];
  });
  const count = (fn: (s: SectionDiff) => number) => changed.reduce((n, s) => n + fn(s), 0);
  const impact = [
    { label: t("sectionsChanged"), value: changed.length },
    { label: t("itemsAdded"), value: count((s) => s.added_items.length) },
    { label: t("itemsUpdated"), value: count((s) => s.changed_items.length) },
    { label: t("itemsRemoved"), value: count((s) => s.removed_items.length) },
  ];

  return (
    <div className="space-y-5">
      <section>
        <Heading>{t("whatWillHappen")}</Heading>
        <ul className="space-y-1.5 text-[13px] text-muted">
          <li className="flex gap-2"><FileText className="mt-0.5 size-4 shrink-0 text-accent" /> {t("becomesCurrent", { version: proposedVersion, title: proposed.title })}</li>
          <li className="flex gap-2"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" /> {t("staysInHistory", { version: current.version })}</li>
        </ul>
      </section>
      <section>
        <Heading>{t("impact")}</Heading>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {impact.map((i) => (
            <div key={i.label} className="rounded-[12px] border border-border bg-background/60 px-3 py-2.5">
              <div className="text-[20px] font-semibold tabular-nums">{i.value}</div>
              <div className="text-[11.5px] text-subtle">{i.label}</div>
            </div>
          ))}
        </div>
      </section>
      <section>
        <Heading>{t("preview")}</Heading>
        <div className="max-h-56 overflow-auto rounded-[12px] border border-border">
          <table className="w-full text-left text-[12.5px]">
            <thead className="sticky top-0 bg-surface-2 text-[11.5px] text-subtle">
              <tr><th className="px-3 py-2 font-medium">{t("colItem")}</th><th className="px-3 py-2 font-medium max-sm:hidden">{t("colSection")}</th><th className="px-3 py-2 font-medium">{t("colChange")}</th><th className="px-3 py-2 font-medium max-sm:hidden">{t("colPriority")}</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="px-3 py-2"><span className="line-clamp-2">{r.title}</span></td>
                  <td className="px-3 py-2 text-muted max-sm:hidden">{r.section}</td>
                  <td className="px-3 py-2"><Badge tone={CHANGE_TONE[r.change]}>{t(`change_${r.change}`)}</Badge></td>
                  <td className="px-3 py-2 text-muted max-sm:hidden">{r.priority ?? "—"}</td>
                </tr>
              ))}
              {!rows.length ? <tr><td colSpan={4} className="px-3 py-3 text-subtle">{t("noChange")}</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
      <section>
        <Heading>{t("qualityCheck")}</Heading>
        <QualityList checks={proposed.quality} definition={proposed.definition} />
      </section>
    </div>
  );
}

function ExternalWrite({ approval }: { approval: ApprovalData }) {
  const t = useT(M);
  const request = approval.tool_request;
  const entries = Object.entries(request?.arguments ?? {});
  return (
    <div className="space-y-5">
      <section>
        <Heading>{t("whatWillHappen")}</Heading>
        <ul className="space-y-1.5 text-[13px] text-muted">
          <li className="flex gap-2"><ExternalLink className="mt-0.5 size-4 shrink-0 text-accent" /> {t("novaCalls")} <code className="rounded bg-surface-2 px-1">{request?.tool ?? t("aTool")}</code>{request?.reason ? ` — ${request.reason}` : "."}</li>
          <li className="flex gap-2"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" /> {t("externalWarning")}</li>
        </ul>
      </section>
      {entries.length ? (
        <section>
          <Heading>{t("preview")}</Heading>
          <div className="max-h-56 overflow-auto rounded-[12px] border border-border">
            <table className="w-full text-left text-[12.5px]">
              <tbody className="divide-y divide-border">
                {entries.map(([k, v]) => (
                  <tr key={k}>
                    <td className="w-40 px-3 py-2 align-top text-subtle">{k}</td>
                    <td className="px-3 py-2"><pre className="whitespace-pre-wrap break-words font-sans">{typeof v === "string" ? v : JSON.stringify(v, null, 2)}</pre></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </div>
  );
}

export function ApprovalDialog({
  approval,
  taskId,
  open,
  onOpenChange,
}: {
  approval: ApprovalData;
  taskId: string | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const resume = useResume();
  const t = useT(M);
  const lang = useLang();
  const names = useCatalogNames();
  const decide = (action: "approve" | "reject") => {
    if (!taskId) return;
    resume.mutate({ taskId, value: { action } }, { onSuccess: () => onOpenChange(false) });
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={systemLabel(approval.title, lang, names)} description={systemLabel(approval.description, lang, names)} className="top-[6vh] max-h-[88vh] w-[min(94vw,680px)] overflow-y-auto rounded-[20px]">
        {approval.action === "external_write" ? <ExternalWrite approval={approval} /> : <ArtifactChanges approval={approval} />}
        <div className={cn("mt-6 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4")}>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("cancel")}</Button>
          <Button variant="secondary" onClick={() => decide("reject")} disabled={resume.isPending}>{t("reject")}</Button>
          <Button variant="primary" onClick={() => decide("approve")} disabled={resume.isPending}>
            {approval.action === "external_write" ? t("approve") : t("approveAll")}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
