"use client";

import { Badge, Button, cn } from "@nova/ui";
import { GitCompare, Sparkles, User } from "lucide-react";
import { useState } from "react";

import { useArtifactVersions, useCompare } from "@/lib/api/hooks";
import type { ArtifactTypeDef } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";

export function VersionHistory({ artifactId, current, viewing, onView, definition }: {
  artifactId: string;
  current: number;
  viewing: number | null;
  onView: (version: number) => void;
  definition: ArtifactTypeDef;
}) {
  const { data: versions } = useArtifactVersions(artifactId);
  const [compare, setCompare] = useState<number[]>([]);
  const pair = compare.length === 2 ? [Math.min(...compare), Math.max(...compare)] : null;
  const { data: diff } = useCompare(artifactId, pair?.[0] ?? null, pair?.[1] ?? null);
  const title = (key: string) => definition.sections.find((s) => s.key === key)?.title ?? key;
  const toggle = (v: number) => setCompare((prev) => (prev.includes(v) ? prev.filter((x) => x !== v) : [...prev, v].slice(-2)));

  return (
    <div className="flex h-full w-[320px] flex-col">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <span className="text-[13px] font-medium">Versions</span>
        <span className="text-[11.5px] text-subtle">{compare.length === 2 ? "Comparing" : "Select two to compare"}</span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {pair && diff ? (
          <div className="border-b border-border p-4">
            <div className="mb-2 flex items-center justify-between text-[12.5px]">
              <span className="font-medium">v{pair[0]} → v{pair[1]}</span>
              <Button variant="ghost" size="sm" className="h-6 text-[11.5px]" onClick={() => setCompare([])}>Clear</Button>
            </div>
            {diff.sections.filter((d) => d.status !== "unchanged").map((d) => (
              <div key={d.key} className="mb-3">
                <div className="flex items-center gap-1.5 text-[12.5px] font-medium">
                  {title(d.key)} <Badge tone={d.status === "added" ? "success" : d.status === "removed" ? "danger" : "accent"}>{d.status}</Badge>
                </div>
                {d.added_items.length || d.removed_items.length || d.changed_items.length ? (
                  <div className="mt-0.5 text-[11.5px] text-subtle">
                    {[d.added_items.length && `+${d.added_items.length}`, d.removed_items.length && `−${d.removed_items.length}`, d.changed_items.length && `~${d.changed_items.length}`].filter(Boolean).join(" ")} items
                  </div>
                ) : null}
                {d.before_text ? <pre className="mt-1 max-h-24 overflow-hidden whitespace-pre-wrap rounded-md bg-danger/[0.06] p-1.5 text-[11.5px] text-muted line-through decoration-danger/40">{d.before_text.slice(0, 400)}</pre> : null}
                {d.after_text ? <pre className="mt-1 max-h-24 overflow-hidden whitespace-pre-wrap rounded-md bg-success/[0.07] p-1.5 text-[11.5px] text-text">{d.after_text.slice(0, 400)}</pre> : null}
              </div>
            ))}
            {diff.sections.every((d) => d.status === "unchanged") ? <p className="text-[12px] text-subtle">No differences.</p> : null}
          </div>
        ) : null}
        <ul>
          {(versions ?? []).map((v) => (
            <li key={v.version} className={cn("border-b border-border px-4 py-2.5", viewing === v.version && "bg-surface-2")}>
              <div className="flex items-center gap-2">
                <button onClick={() => onView(v.version)} className="flex items-center gap-2 text-left">
                  {v.author_type === "nova" ? <Sparkles className="size-3.5 text-accent" /> : <User className="size-3.5 text-subtle" />}
                  <span className="text-[13px] font-medium">v{v.version}</span>
                </button>
                {v.version === current ? <Badge tone="accent">current</Badge> : null}
                {v.state === "proposed" ? <Badge tone="warning">proposed</Badge> : null}
                {v.state === "rejected" ? <Badge>rejected</Badge> : null}
                <button onClick={() => toggle(v.version)} className={cn("ml-auto rounded p-1 text-subtle hover:text-text", compare.includes(v.version) && "text-accent")} aria-label={`Compare v${v.version}`}>
                  <GitCompare className="size-3.5" />
                </button>
              </div>
              <div className="mt-0.5 text-[11.5px] text-subtle">
                {v.author_name ?? "Unknown"}
                {v.skill_id ? ` · ${v.skill_id}@${v.skill_version}` : ""} · {timeAgo(v.created_at)}
              </div>
              {v.changed_sections.length ? <div className="mt-0.5 truncate text-[11.5px] text-muted">{v.changed_sections.map(title).join(", ")}</div> : null}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
