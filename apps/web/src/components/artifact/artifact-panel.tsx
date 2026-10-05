"use client";

import {
  Badge,
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Select,
  Skeleton,
  Tooltip,
} from "@nova/ui";
import { AnimatePresence, motion } from "framer-motion";
import { Check, Download, FlaskConical, History, Loader2, Maximize2, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { ClassificationBadge } from "@/components/shell/page";
import { type SaveState, useArtifactEditor } from "@/hooks/use-artifact-editor";
import { defineMessages, useLang, useT } from "@/lib/i18n";
import { sectionTitle, typeName } from "@/lib/i18n/catalog";

import { ArtifactSection } from "./section";
import { VersionHistory } from "./version-history";

const M = defineMessages({
  en: {
    unavailable: "This Artifact is not available.",
    forgeEvaluation: (v: { status: string }) => `FORGE evaluation · ${v.status}`,
    pending: "pending",
    queued: "queued",
    running: "running",
    completed: "completed",
    failed: "failed",
    status: "Status",
    draft: "Draft",
    in_review: "In review",
    final: "Final",
    versionHistory: "Version history",
    export: "Export",
    openFullPage: "Open full page",
    closeArtifact: "Close Artifact",
    artifactTitle: "Artifact title",
    proposed: (v: { version: number }) => `NOVA proposed version ${v.version}.`,
    review: "Review",
    approve: "Approve",
    viewing: (v: { version: number; state: string }) => `Viewing version ${v.version} (${v.state}) — read-only.`,
    state_current: "current",
    state_proposed: "proposed",
    state_superseded: "superseded",
    state_rejected: "rejected",
    backToCurrent: "Back to current",
    saving: "Saving",
    changedElsewhere: "Changed elsewhere",
    reload: "Reload",
    saved: "Saved · ",
  },
  fr: {
    unavailable: "Cet Artefact n’est pas disponible.",
    forgeEvaluation: (v: { status: string }) => `Évaluation FORGE · ${v.status}`,
    pending: "en attente",
    queued: "en file d’attente",
    running: "en cours",
    completed: "terminée",
    failed: "échouée",
    status: "Statut",
    draft: "Brouillon",
    in_review: "En revue",
    final: "Final",
    versionHistory: "Historique des versions",
    export: "Exporter",
    openFullPage: "Ouvrir en pleine page",
    closeArtifact: "Fermer l’Artefact",
    artifactTitle: "Titre de l’Artefact",
    proposed: (v: { version: number }) => `NOVA propose la version ${v.version}.`,
    review: "Examiner",
    approve: "Approuver",
    viewing: (v: { version: number; state: string }) => `Version ${v.version} (${v.state}) — lecture seule.`,
    state_current: "actuelle",
    state_proposed: "proposée",
    state_superseded: "remplacée",
    state_rejected: "rejetée",
    backToCurrent: "Revenir à la version actuelle",
    saving: "Enregistrement",
    changedElsewhere: "Modifié ailleurs",
    reload: "Recharger",
    saved: "Enregistré · ",
  },
});

const EVALUATION_STATUSES = ["pending", "queued", "running", "completed", "failed"] as const;
const VERSION_STATES = ["current", "proposed", "superseded", "rejected"] as const;

export function ArtifactPanel({ artifactId, onClose, showOpenFull = true }: { artifactId: string; onClose?: () => void; showOpenFull?: boolean }) {
  const { artifact, isLoading, error, comments, draft, dirty, baseVersion, save, viewVersion, setViewVersion, viewingOld, editable, schedule, approve, setStatus, reload } =
    useArtifactEditor(artifactId);
  const [historyOpen, setHistoryOpen] = useState(false);
  const t = useT(M);
  const lang = useLang();
  const evaluationStatus = (status: string | null | undefined, fallback: "pending" | "queued") =>
    !status ? t(fallback) : (EVALUATION_STATUSES as readonly string[]).includes(status) ? t(status as (typeof EVALUATION_STATUSES)[number]) : status;
  const versionState = (state: string) => ((VERSION_STATES as readonly string[]).includes(state) ? t(`state_${state as (typeof VERSION_STATES)[number]}`) : state);

  if (isLoading || !draft || !artifact) {
    return (
      <div className="space-y-3 p-6">
        {error ? <p className="text-sm text-muted">{t("unavailable")}</p> : <><Skeleton className="h-7 w-2/3" /><Skeleton className="h-40 w-full" /></>}
      </div>
    );
  }
  const allItems = Object.values(draft.sections).flatMap((s) => s.items);

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border px-5 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-2 text-[11.5px] uppercase tracking-wider text-subtle">
          <span className="truncate">{typeName(artifact.definition, lang, artifact.type_name)}</span>
          <ClassificationBadge level={artifact.classification} />
        </div>
        <SaveIndicator state={save} version={baseVersion ?? artifact.version} onReload={reload} />
        {artifact.evaluation ? (
          <Tooltip content={t("forgeEvaluation", { status: evaluationStatus(artifact.evaluation.status, "pending") })}>
            <a href={artifact.evaluation.url ?? "#"} target="_blank" rel="noreferrer">
              <Badge tone={artifact.evaluation.passed ? "success" : "neutral"}>
                <FlaskConical className="size-3" />
                {artifact.evaluation.composite_score != null ? Math.round(artifact.evaluation.composite_score) : evaluationStatus(artifact.evaluation.status, "queued")}
              </Badge>
            </a>
          </Tooltip>
        ) : null}
        <Select
          ariaLabel={t("status")}
          value={artifact.status}
          onValueChange={(v) => setStatus.mutate(v)}
          options={[
            { value: "draft", label: t("draft") },
            { value: "in_review", label: t("in_review") },
            { value: "final", label: t("final") },
          ]}
          className="h-8 w-[112px] text-[12.5px]"
        />
        <Tooltip content={t("versionHistory")}>
          <Button variant="ghost" size="icon" onClick={() => setHistoryOpen(!historyOpen)} aria-label={t("versionHistory")}><History /></Button>
        </Tooltip>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t("export")}><Download /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem asChild><a href={`/api/v1/artifacts/${artifactId}/export?format=md`}>Markdown</a></DropdownMenuItem>
            <DropdownMenuItem asChild><a href={`/api/v1/artifacts/${artifactId}/export?format=json`}>JSON</a></DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {showOpenFull ? (
          <Tooltip content={t("openFullPage")}>
            <Button variant="ghost" size="icon" asChild><Link href={`/artifacts/${artifactId}`} aria-label={t("openFullPage")}><Maximize2 /></Link></Button>
          </Tooltip>
        ) : null}
        {onClose ? <Button variant="ghost" size="icon" onClick={onClose} aria-label={t("closeArtifact")}><X /></Button> : null}
        <div className="order-last w-full min-w-0">
          {editable ? (
            <input
              value={draft.title}
              onChange={(e) => schedule({ ...draft, title: e.target.value }, "title")}
              className="w-full truncate bg-transparent text-[17px] font-semibold tracking-tight outline-none"
              aria-label={t("artifactTitle")}
            />
          ) : (
            <h2 className="truncate text-[17px] font-semibold tracking-tight">{draft.title}</h2>
          )}
        </div>
      </header>

      <AnimatePresence>
        {artifact.proposed_version && !viewingOld ? (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden border-b border-warning/25 bg-warning/[0.06]">
            <div className="flex items-center gap-3 px-5 py-2 text-[13px]">
              {t("proposed", { version: artifact.proposed_version })}
              <Button size="sm" variant="ghost" onClick={() => setViewVersion(artifact.proposed_version)}>{t("review")}</Button>
              <Button size="sm" variant="primary" onClick={() => approve.mutate(artifact.proposed_version!)} disabled={approve.isPending}><Check /> {t("approve")}</Button>
            </div>
          </motion.div>
        ) : null}
        {viewingOld ? (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden border-b border-border bg-surface-2">
            <div className="flex items-center gap-3 px-5 py-2 text-[13px] text-muted">
              {t("viewing", { version: viewVersion ?? artifact.viewing_version, state: versionState(artifact.version_state) })}
              {artifact.version_state === "proposed" ? (
                <Button size="sm" variant="primary" onClick={() => approve.mutate(viewVersion!)}><Check /> {t("approve")}</Button>
              ) : null}
              <Button size="sm" variant="ghost" onClick={() => setViewVersion(null)}>{t("backToCurrent")}</Button>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <div className="flex min-h-0 flex-1">
        <div className="min-w-0 flex-1 overflow-y-auto px-5 pb-16">
          {artifact.definition.sections.length > 8 ? (
            <div className="sticky top-0 z-10 -mx-5 mb-1 flex gap-1 overflow-x-auto border-b border-border bg-background/90 px-5 py-2 backdrop-blur">
              {artifact.definition.sections.map((s) => (
                <button
                  key={s.key}
                  onClick={() => document.getElementById(`section-${s.key}`)?.scrollIntoView({ behavior: "smooth" })}
                  className={cn("shrink-0 rounded-md px-2 py-0.5 text-[12px] text-subtle hover:bg-surface-2 hover:text-text", dirty.has(s.key) && "text-accent")}
                >
                  {sectionTitle(artifact.definition, s, lang)}
                </button>
              ))}
            </div>
          ) : null}
          {artifact.definition.sections.map((definition) => (
            <ArtifactSection
              key={definition.key}
              artifactId={artifactId}
              artifactType={artifact.definition}
              definition={definition}
              content={draft.sections[definition.key] ?? { kind: definition.kind, blocks: [], items: [] }}
              editable={editable}
              allItems={allItems}
              comments={(comments ?? []).filter((c) => c.section_key === definition.key)}
              versionKey={`${definition.key}-${artifact.viewing_version}-${baseVersion === artifact.viewing_version ? "s" : "l"}`}
              conversationId={artifact.conversation_id}
              onChange={(section) => schedule({ ...draft, sections: { ...draft.sections, [definition.key]: section } }, definition.key)}
            />
          ))}
        </div>
        <AnimatePresence>
          {historyOpen ? (
            <motion.aside initial={{ width: 0, opacity: 0 }} animate={{ width: 320, opacity: 1 }} exit={{ width: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="shrink-0 overflow-hidden border-l border-border">
              <VersionHistory artifactId={artifactId} current={artifact.version} viewing={viewVersion} onView={(v) => setViewVersion(v === artifact.version ? null : v)} definition={artifact.definition} />
            </motion.aside>
          ) : null}
        </AnimatePresence>
      </div>
    </div>
  );
}

function SaveIndicator({ state, version, onReload }: { state: SaveState; version: number; onReload: () => void }) {
  const t = useT(M);
  if (state.kind === "saving") return <span className="flex items-center gap-1 text-[12px] text-subtle"><Loader2 className="size-3 animate-spin" /> {t("saving")}</span>;
  if (state.kind === "conflict")
    return (
      <span className="flex items-center gap-2 text-[12px] text-warning">
        {t("changedElsewhere")}
        <Button size="sm" variant="secondary" className="h-7" onClick={onReload}>{t("reload")}</Button>
      </span>
    );
  if (state.kind === "error") return <span className="text-[12px] text-danger">{state.message}</span>;
  return (
    <span data-testid="save-state" className="text-[12px] text-subtle">
      {state.kind === "saved" ? t("saved") : ""}v{version}
    </span>
  );
}

