"use client";

import { Button, Dialog, DialogContent, Input } from "@nova/ui";
import { useMutation } from "@tanstack/react-query";
import { Orbit, Search } from "lucide-react";
import { useState } from "react";

import { systemLabel } from "@/components/conversation/blocks.messages";
import { ClassificationBadge, ErrorNotice } from "@/components/shell/page";
import { api, ApiError } from "@/lib/api/client";
import type { ContextSource } from "@/lib/api/types";
import { defineMessages, useLang, useT } from "@/lib/i18n";
import type { ComposerContextRef } from "@/stores/ui";

const M = defineMessages({
  en: {
    title: "Add context from ORBIT",
    description: "ORBIT returns only what you are allowed to see, with sources.",
    placeholder: "e.g. Sprint 19 objective and unfinished stories",
    find: "Find",
    error: "ORBIT could not provide context",
    retrieving: "Retrieving context…",
    found: (v: { n: number }) => `${v.n} source${v.n === 1 ? "" : "s"} found`,
    use: "Use this context",
  },
  fr: {
    title: "Ajouter du contexte depuis ORBIT",
    description: "ORBIT ne renvoie que ce que vous êtes autorisé à consulter, avec les sources.",
    placeholder: "ex. Objectif du sprint 19 et stories non terminées",
    find: "Rechercher",
    error: "ORBIT n’a pas pu fournir de contexte",
    retrieving: "Récupération du contexte…",
    found: (v: { n: number }) => `${v.n} source${v.n > 1 ? "s" : ""} trouvée${v.n > 1 ? "s" : ""}`,
    use: "Utiliser ce contexte",
  },
});

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
  const t = useT(M);
  const lang = useLang();
  const [query, setQuery] = useState("");
  const retrieve = useMutation({
    mutationFn: () => api.post<RetrieveResult>("/context/retrieve", { project_id: projectId, query }),
  });
  const error = retrieve.error instanceof ApiError ? retrieve.error : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={t("title")} description={t("description")} className="w-[min(92vw,640px)]">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (query.trim().length >= 2) retrieve.mutate();
          }}
        >
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("placeholder")} autoFocus />
          <Button type="submit" disabled={retrieve.isPending || query.trim().length < 2}>
            <Search /> {t("find")}
          </Button>
        </form>
        {error ? <ErrorNotice title={t("error")} message={error.message} /> : null}
        {retrieve.isPending ? <p className="mt-4 text-sm text-subtle">{t("retrieving")}</p> : null}
        {retrieve.data ? (
          <div className="mt-4">
            <div className="mb-2 text-[12px] text-subtle">
              {t("found", { n: retrieve.data.items.length })}{retrieve.data.warnings.length ? ` · ${retrieve.data.warnings.map((w) => systemLabel(w, lang)).join(" ")}` : ""}
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
                {t("use")}
              </Button>
            </div>
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
