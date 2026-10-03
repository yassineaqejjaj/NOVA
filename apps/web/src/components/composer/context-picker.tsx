"use client";

import { Button, Dialog, DialogContent, Input } from "@nova/ui";
import { useMutation } from "@tanstack/react-query";
import { Orbit, Search } from "lucide-react";
import { useState } from "react";

import { ClassificationBadge, ErrorNotice } from "@/components/shell/page";
import { api, ApiError } from "@/lib/api/client";
import type { ContextSource } from "@/lib/api/types";
import type { ComposerContextRef } from "@/stores/ui";

interface RetrieveResult {
  reference_id: string;
  retrieval_id: string | null;
  warnings: string[];
  items: ContextSource[];
}

/** Explicit context: ask ORBIT for governed context on a topic, review it, then pin it to the next message. */
export function ContextPicker({
  open,
  onOpenChange,
  projectId,
  onPin,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string | null;
  onPin: (ref: ComposerContextRef) => void;
}) {
  const [query, setQuery] = useState("");
  const retrieve = useMutation({
    mutationFn: () => api.post<RetrieveResult>("/context/retrieve", { project_id: projectId, query }),
  });
  const error = retrieve.error instanceof ApiError ? retrieve.error : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Add context from ORBIT" description="ORBIT returns only what you are allowed to see, with sources." className="w-[min(92vw,640px)]">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (query.trim().length >= 2) retrieve.mutate();
          }}
        >
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. Sprint 19 objective and unfinished stories" autoFocus />
          <Button type="submit" disabled={retrieve.isPending || query.trim().length < 2}>
            <Search /> Find
          </Button>
        </form>
        {error ? <ErrorNotice title="ORBIT could not provide context" message={error.message} /> : null}
        {retrieve.isPending ? <p className="mt-4 text-sm text-subtle">Retrieving context…</p> : null}
        {retrieve.data ? (
          <div className="mt-4">
            <div className="mb-2 text-[12px] text-subtle">
              {retrieve.data.items.length} sources found{retrieve.data.warnings.length ? ` · ${retrieve.data.warnings.join(" ")}` : ""}
            </div>
            <ul className="max-h-[42vh] space-y-1.5 overflow-y-auto">
              {retrieve.data.items.map((item) => (
                <li key={`${item.citation}-${item.title}`} className="rounded-[10px] border border-border bg-surface-2 px-3 py-2">
                  <div className="flex items-center gap-2 text-[13px]">
                    <Orbit className="size-3.5 text-subtle" />
                    <span className="truncate font-medium">{item.title}</span>
                    <ClassificationBadge level={item.classification} />
                    <span className="ml-auto text-[11px] text-subtle">{item.type ?? item.kind}</span>
                  </div>
                  {item.excerpt ? <p className="mt-1 line-clamp-2 text-[12px] text-muted">{item.excerpt}</p> : null}
                </li>
              ))}
            </ul>
            <div className="mt-4 flex justify-end">
              <Button
                variant="primary"
                disabled={!retrieve.data.items.length}
                onClick={() => {
                  onPin({ reference_id: retrieve.data!.reference_id, label: query.slice(0, 40), count: retrieve.data!.items.length });
                  onOpenChange(false);
                  setQuery("");
                  retrieve.reset();
                }}
              >
                Use this context
              </Button>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
