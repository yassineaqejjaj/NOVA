"use client";

import { Button } from "@nova/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Loader2, RefreshCw, TriangleAlert } from "lucide-react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import { timeAgo } from "@/lib/format";
import { defineMessages, useT } from "@/lib/i18n";

/** Living Artifact: do the sources this Artifact cites still say the same thing? (`/artifacts/{id}/freshness`) */
interface Freshness {
  status: "fresh" | "stale" | "unverified";
  reason: "no_citations" | "context_unavailable" | null;
  as_of: string | null;
  sources?: number;
  may_be_incomplete?: boolean;
  stale_sections: string[];
  impacts: { change_id: string; type_label: string; change_title: string; source_title: string; sections: string[]; at: string }[];
}

const M = defineMessages({
  en: {
    stale: (v: { n: number }) => `${v.n} source${v.n === 1 ? "" : "s"} this Artifact cites changed in Nova Context since this version.`,
    sections: (v: { names: string }) => `Affected: ${v.names}`,
    update: "Propose an update",
    updating: "NOVA is preparing an update…",
    more: (v: { n: number }) => `+${v.n} more`,
    fresh: (v: { n: number; when: string }) => `Up to date with its ${v.n} cited source${v.n === 1 ? "" : "s"} (this version ${v.when}).`,
    noCitations: "No citations to check against.",
    unavailable: "Could not check the sources just now.",
    incomplete: "Nova Context reported many changes: older ones may not be listed.",
  },
  fr: {
    stale: (v: { n: number }) => `${v.n} source${v.n === 1 ? "" : "s"} citée${v.n === 1 ? "" : "s"} par cet Artefact a changé dans Nova Context depuis cette version.`,
    sections: (v: { names: string }) => `Concerné : ${v.names}`,
    update: "Proposer une mise à jour",
    updating: "NOVA prépare une mise à jour…",
    more: (v: { n: number }) => `+${v.n} autre${v.n === 1 ? "" : "s"}`,
    fresh: (v: { n: number; when: string }) => `À jour de ses ${v.n} source${v.n === 1 ? "" : "s"} citée${v.n === 1 ? "" : "s"} (cette version ${v.when}).`,
    noCitations: "Aucune citation à vérifier.",
    unavailable: "Impossible de vérifier les sources pour le moment.",
    incomplete: "Nova Context signale de nombreux changements : les plus anciens peuvent manquer.",
  },
});

export function FreshnessBanner({ artifactId, canEdit, sectionName }: { artifactId: string; canEdit: boolean; sectionName: (key: string) => string | undefined }) {
  const t = useT(M);
  const router = useRouter();
  const client = useQueryClient();
  const { data } = useQuery({
    queryKey: ["artifact-freshness", artifactId],
    queryFn: () => api.get<Freshness>(`/artifacts/${artifactId}/freshness`),
    staleTime: 60_000,
  });
  const refresh = useMutation({
    mutationFn: () => api.post<{ conversation_id: string }>(`/artifacts/${artifactId}/refresh`),
    onSuccess: (result) => {
      toast(t("updating"));
      void client.invalidateQueries({ queryKey: ["artifact-freshness", artifactId] });
      router.push(`/c/${result.conversation_id}?artifact=${artifactId}`);
    },
  });
  if (!data) return null;
  if (data.status === "stale") {
    const shown = data.impacts.slice(0, 3);
    return (
      <div role="status" className="mt-4 rounded-[14px] border border-warning/30 bg-warning/[0.07] px-4 py-3 text-[13.5px]">
        <div className="flex items-start gap-2">
          <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
          <div className="min-w-0 flex-1">
            <div className="font-medium">{t("stale", { n: new Set(data.impacts.map((i) => i.source_title)).size })}</div>
            <ul className="mt-1 space-y-0.5 text-muted">
              {shown.map((i) => (
                <li key={i.change_id}>
                  {i.source_title} — {i.type_label ? `${i.type_label} · ` : ""}
                  {i.change_title} <span className="text-subtle">({timeAgo(i.at)})</span>
                </li>
              ))}
              {data.impacts.length > shown.length ? <li className="text-subtle">{t("more", { n: data.impacts.length - shown.length })}</li> : null}
            </ul>
            <div className="mt-1 text-[12.5px] text-subtle">{t("sections", { names: data.stale_sections.map((k) => sectionName(k) ?? k).join(", ") })}</div>
            {data.may_be_incomplete ? <div className="mt-1 text-[12px] text-subtle">{t("incomplete")}</div> : null}
          </div>
          {canEdit ? (
            <Button size="sm" variant="primary" disabled={refresh.isPending} onClick={() => refresh.mutate()}>
              {refresh.isPending ? <Loader2 className="animate-spin" aria-hidden /> : <RefreshCw aria-hidden />} {t("update")}
            </Button>
          ) : null}
        </div>
      </div>
    );
  }
  return (
    <p role="status" className="mt-3 flex items-center gap-1.5 text-[12.5px] text-subtle">
      {data.status === "fresh" ? <CircleCheck className="size-3.5 text-success" aria-hidden /> : null}
      {data.status === "fresh"
        ? t("fresh", { n: data.sources ?? 0, when: data.as_of ? timeAgo(data.as_of) : "" })
        : data.reason === "context_unavailable"
          ? t("unavailable")
          : t("noCitations")}
    </p>
  );
}
