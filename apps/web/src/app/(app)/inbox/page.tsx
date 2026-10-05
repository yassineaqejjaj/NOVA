"use client";

import { cn, Skeleton } from "@nova/ui";
import { Inbox as InboxIcon } from "lucide-react";
import { useState } from "react";

import { InboxItemCard, KIND_ICON } from "@/components/missions/ui";
import { M } from "@/components/missions/missions.messages";
import { EmptyState, Page, PageHeader } from "@/components/shell/page";
import { type InboxKind, useInbox } from "@/lib/api/missions";
import { useT } from "@/lib/i18n";

const KINDS: InboxKind[] = ["decision", "validation", "anomaly", "suggestion", "result"];

/** NOVA Inbox: NOVA works, filters, and brings only what needs a human. */
export default function InboxPage() {
  const t = useT(M);
  const { data, isLoading } = useInbox();
  const [kind, setKind] = useState<InboxKind | "all">("all");
  const items = (data?.items ?? []).filter((i) => kind === "all" || i.kind === kind);
  return (
    <Page>
      <PageHeader title={t("inboxTitle")} description={t("inboxDescription")} />
      <div role="tablist" aria-label={t("inboxTitle")} className="mb-4 flex flex-wrap gap-2">
        <button role="tab" aria-selected={kind === "all"} onClick={() => setKind("all")} className={cn("rounded-full border px-3 py-1 text-[13px]", kind === "all" ? "border-accent/50 bg-accent-soft text-text" : "border-border text-muted hover:text-text")}>
          {t("all")} <span className="text-subtle">{data?.counts.total ?? 0}</span>
        </button>
        {KINDS.map((k) => {
          const Icon = KIND_ICON[k];
          return (
            <button key={k} role="tab" aria-selected={kind === k} onClick={() => setKind(k)} className={cn("inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px]", kind === k ? "border-accent/50 bg-accent-soft text-text" : "border-border text-muted hover:text-text")}>
              <Icon className="size-3.5" /> {t(`k_${k}`)} <span className="text-subtle">{data?.counts[k] ?? 0}</span>
            </button>
          );
        })}
      </div>
      {isLoading ? <Skeleton className="h-48" /> : null}
      {data && items.length === 0 ? <EmptyState icon={<InboxIcon />} title={t("inboxEmpty")} description={t("inboxEmptyHint")} /> : null}
      <ul className="divide-y divide-border/70" aria-label={t("inboxTitle")}>
        {items.map((item) => <InboxItemCard key={item.id} item={item} />)}
      </ul>
    </Page>
  );
}
