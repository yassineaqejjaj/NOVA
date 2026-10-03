"use client";

import { Badge, Button, cn, Dialog, DialogContent, Skeleton } from "@nova/ui";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDashed, ExternalLink, FileText, ShieldCheck } from "lucide-react";

import { api } from "@/lib/api/client";
import { useArtifact, useResume } from "@/lib/api/hooks";
import type { ArtifactContent, ArtifactItem, QualityCheck, SectionDiff } from "@/lib/api/types";

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

function QualityList({ checks }: { checks: QualityCheck[] }) {
  return (
    <ul className="space-y-1.5">
      {checks.map((c) => (
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

  const titles = Object.fromEntries(proposed.definition.sections.map((s) => [s.key, s.title]));
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
    return items.length ? items : [{ key: `s-${s.key}`, title: s.after_text.slice(0, 90) || "Section text", section, change: "Rewritten" as const }];
  });
  const count = (fn: (s: SectionDiff) => number) => changed.reduce((n, s) => n + fn(s), 0);
  const impact = [
    { label: "Sections changed", value: changed.length },
    { label: "Items added", value: count((s) => s.added_items.length) },
    { label: "Items updated", value: count((s) => s.changed_items.length) },
    { label: "Items removed", value: count((s) => s.removed_items.length) },
  ];

  return (
    <div className="space-y-5">
      <section>
        <Heading>What will happen</Heading>
        <ul className="space-y-1.5 text-[13px] text-muted">
          <li className="flex gap-2"><FileText className="mt-0.5 size-4 shrink-0 text-accent" /> Version {proposedVersion} of “{proposed.title}” becomes the current version.</li>
          <li className="flex gap-2"><ShieldCheck className="mt-0.5 size-4 shrink-0 text-accent" /> Version {current.version} stays in the history — you can compare or restore it at any time.</li>
        </ul>
      </section>
      <section>
        <Heading>Impact</Heading>
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
        <Heading>Preview of changes</Heading>
        <div className="max-h-56 overflow-auto rounded-[12px] border border-border">
          <table className="w-full text-left text-[12.5px]">
            <thead className="sticky top-0 bg-surface-2 text-[11.5px] text-subtle">
              <tr><th className="px-3 py-2 font-medium">Item</th><th className="px-3 py-2 font-medium max-sm:hidden">Section</th><th className="px-3 py-2 font-medium">Change</th><th className="px-3 py-2 font-medium max-sm:hidden">Priority</th></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((r) => (
                <tr key={r.key}>
                  <td className="px-3 py-2"><span className="line-clamp-2">{r.title}</span></td>
                  <td className="px-3 py-2 text-muted max-sm:hidden">{r.section}</td>
                  <td className="px-3 py-2"><Badge tone={CHANGE_TONE[r.change]}>{r.change}</Badge></td>
                  <td className="px-3 py-2 text-muted max-sm:hidden">{r.priority ?? "—"}</td>
                </tr>
              ))}
              {!rows.length ? <tr><td colSpan={4} className="px-3 py-3 text-subtle">No content change.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
      <section>
        <Heading>Quality check</Heading>
        <QualityList checks={proposed.quality} />
      </section>
    </div>
  );
}

function ExternalWrite({ approval }: { approval: ApprovalData }) {
  const request = approval.tool_request;
  const entries = Object.entries(request?.arguments ?? {});
  return (
    <div className="space-y-5">
      <section>
        <Heading>What will happen</Heading>
        <ul className="space-y-1.5 text-[13px] text-muted">
          <li className="flex gap-2"><ExternalLink className="mt-0.5 size-4 shrink-0 text-accent" /> NOVA calls <code className="rounded bg-surface-2 px-1">{request?.tool ?? "a tool"}</code>{request?.reason ? ` — ${request.reason}` : "."}</li>
          <li className="flex gap-2"><AlertTriangle className="mt-0.5 size-4 shrink-0 text-warning" /> This changes data outside NOVA and may not be reversible from here.</li>
        </ul>
      </section>
      {entries.length ? (
        <section>
          <Heading>Preview of changes</Heading>
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
  const decide = (action: "approve" | "reject") => {
    if (!taskId) return;
    resume.mutate({ taskId, value: { action } }, { onSuccess: () => onOpenChange(false) });
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={approval.title} description={approval.description} className="top-[6vh] max-h-[88vh] w-[min(94vw,680px)] overflow-y-auto rounded-[20px]">
        {approval.action === "external_write" ? <ExternalWrite approval={approval} /> : <ArtifactChanges approval={approval} />}
        <div className={cn("mt-6 flex flex-wrap items-center justify-end gap-2 border-t border-border pt-4")}>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="secondary" onClick={() => decide("reject")} disabled={resume.isPending}>Reject</Button>
          <Button variant="primary" onClick={() => decide("approve")} disabled={resume.isPending}>
            {approval.action === "external_write" ? "Approve" : "Approve all"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
