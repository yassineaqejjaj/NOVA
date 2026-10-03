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

import { ArtifactSection } from "./section";
import { VersionHistory } from "./version-history";

export function ArtifactPanel({ artifactId, onClose, showOpenFull = true }: { artifactId: string; onClose?: () => void; showOpenFull?: boolean }) {
  const { artifact, isLoading, error, comments, draft, dirty, baseVersion, save, viewVersion, setViewVersion, viewingOld, editable, schedule, approve, setStatus, reload } =
    useArtifactEditor(artifactId);
  const [historyOpen, setHistoryOpen] = useState(false);

  if (isLoading || !draft || !artifact) {
    return (
      <div className="space-y-3 p-6">
        {error ? <p className="text-sm text-muted">This Artifact is not available.</p> : <><Skeleton className="h-7 w-2/3" /><Skeleton className="h-40 w-full" /></>}
      </div>
    );
  }
  const allItems = Object.values(draft.sections).flatMap((s) => s.items);

  return (
    <div className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border px-5 py-3">
        <div className="flex min-w-0 flex-1 items-center gap-2 text-[11.5px] uppercase tracking-wider text-subtle">
          <span className="truncate">{artifact.type_name}</span>
          <ClassificationBadge level={artifact.classification} />
        </div>
        <SaveIndicator state={save} version={baseVersion ?? artifact.version} onReload={reload} />
        {artifact.evaluation ? (
          <Tooltip content={`FORGE evaluation · ${artifact.evaluation.status ?? "pending"}`}>
            <a href={artifact.evaluation.url ?? "#"} target="_blank" rel="noreferrer">
              <Badge tone={artifact.evaluation.passed ? "success" : "neutral"}>
                <FlaskConical className="size-3" />
                {artifact.evaluation.composite_score != null ? Math.round(artifact.evaluation.composite_score) : artifact.evaluation.status ?? "queued"}
              </Badge>
            </a>
          </Tooltip>
        ) : null}
        <Select
          ariaLabel="Status"
          value={artifact.status}
          onValueChange={(v) => setStatus.mutate(v)}
          options={[
            { value: "draft", label: "Draft" },
            { value: "in_review", label: "In review" },
            { value: "final", label: "Final" },
          ]}
          className="h-8 w-[112px] text-[12.5px]"
        />
        <Tooltip content="Version history">
          <Button variant="ghost" size="icon" onClick={() => setHistoryOpen(!historyOpen)} aria-label="Version history"><History /></Button>
        </Tooltip>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Export"><Download /></Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem asChild><a href={`/api/v1/artifacts/${artifactId}/export?format=md`}>Markdown</a></DropdownMenuItem>
            <DropdownMenuItem asChild><a href={`/api/v1/artifacts/${artifactId}/export?format=json`}>JSON</a></DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        {showOpenFull ? (
          <Tooltip content="Open full page">
            <Button variant="ghost" size="icon" asChild><Link href={`/artifacts/${artifactId}`} aria-label="Open full page"><Maximize2 /></Link></Button>
          </Tooltip>
        ) : null}
        {onClose ? <Button variant="ghost" size="icon" onClick={onClose} aria-label="Close Artifact"><X /></Button> : null}
        <div className="order-last w-full min-w-0">
          {editable ? (
            <input
              value={draft.title}
              onChange={(e) => schedule({ ...draft, title: e.target.value }, "title")}
              className="w-full truncate bg-transparent text-[17px] font-semibold tracking-tight outline-none"
              aria-label="Artifact title"
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
              NOVA proposed version {artifact.proposed_version}.
              <Button size="sm" variant="ghost" onClick={() => setViewVersion(artifact.proposed_version)}>Review</Button>
              <Button size="sm" variant="primary" onClick={() => approve.mutate(artifact.proposed_version!)} disabled={approve.isPending}><Check /> Approve</Button>
            </div>
          </motion.div>
        ) : null}
        {viewingOld ? (
          <motion.div initial={{ height: 0 }} animate={{ height: "auto" }} exit={{ height: 0 }} className="overflow-hidden border-b border-border bg-surface-2">
            <div className="flex items-center gap-3 px-5 py-2 text-[13px] text-muted">
              Viewing version {viewVersion} ({artifact.version_state}) — read-only.
              {artifact.version_state === "proposed" ? (
                <Button size="sm" variant="primary" onClick={() => approve.mutate(viewVersion!)}><Check /> Approve</Button>
              ) : null}
              <Button size="sm" variant="ghost" onClick={() => setViewVersion(null)}>Back to current</Button>
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
                  {s.title}
                </button>
              ))}
            </div>
          ) : null}
          {artifact.definition.sections.map((definition) => (
            <ArtifactSection
              key={definition.key}
              artifactId={artifactId}
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
  if (state.kind === "saving") return <span className="flex items-center gap-1 text-[12px] text-subtle"><Loader2 className="size-3 animate-spin" /> Saving</span>;
  if (state.kind === "conflict")
    return (
      <span className="flex items-center gap-2 text-[12px] text-warning">
        Changed elsewhere
        <Button size="sm" variant="secondary" className="h-7" onClick={onReload}>Reload</Button>
      </span>
    );
  if (state.kind === "error") return <span className="text-[12px] text-danger">{state.message}</span>;
  return (
    <span data-testid="save-state" className="text-[12px] text-subtle">
      {state.kind === "saved" ? "Saved · " : ""}v{version}
    </span>
  );
}

