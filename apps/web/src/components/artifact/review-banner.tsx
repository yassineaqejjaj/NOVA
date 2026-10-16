"use client";

import { Button } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { TriangleAlert } from "lucide-react";
import { toast } from "sonner";

import { api } from "@/lib/api/client";
import type { ArtifactSummary } from "@/lib/api/types";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    title: "To review: a source of this Artifact was changed in ORBIT",
    forgotten: "ORBIT forgot a source this Artifact cites.",
    sourceRemoved: "A source this Artifact cites was removed: its excerpts were erased.",
    changed: "Who may read a source this Artifact cites changed in ORBIT.",
    removed: "ORBIT removed a member whose context this Artifact was built from.",
    locked: "It cannot be exported or published until it has been reviewed.",
    review: "Mark as reviewed",
    reviewed: "Marked as reviewed.",
    readOnly: "An editor of the project has to review it.",
  },
  fr: {
    title: "À revoir : une source de cet Artefact a changé dans ORBIT",
    forgotten: "ORBIT a oublié une source citée par cet Artefact.",
    sourceRemoved: "Une source citée par cet Artefact a été retirée : ses extraits ont été effacés.",
    changed: "Les droits de lecture d’une source citée par cet Artefact ont changé dans ORBIT.",
    removed: "ORBIT a retiré un membre dont le contexte a servi à construire cet Artefact.",
    locked: "Il ne peut pas être exporté ni publié tant qu’il n’a pas été revu.",
    review: "Marquer comme revu",
    reviewed: "Marqué comme revu.",
    readOnly: "Un éditeur du projet doit le revoir.",
  },
});

/** An Artifact flagged because ORBIT forgot or restricted one of its sources (NOV-81): banner, no export until reviewed. */
export function ReviewBanner({ artifactId, review, canEdit }: { artifactId: string; review: ArtifactSummary["review"]; canEdit: boolean }) {
  const t = useT(M);
  const client = useQueryClient();
  const done = useMutation({
    mutationFn: () => api.post(`/artifacts/${artifactId}/review`),
    onSuccess: () => {
      toast(t("reviewed"));
      void client.invalidateQueries({ queryKey: ["artifact"] });
      void client.invalidateQueries({ queryKey: ["artifacts"] });
    },
  });
  if (!review?.pending) return null;
  const reason = review.reason ?? "";
  const why = reason === "source_removed" ? t("sourceRemoved") : reason.endsWith("forgotten") ? t("forgotten") : reason === "member.removed" ? t("removed") : t("changed");
  return (
    <div role="alert" className="mt-4 rounded-[14px] border border-warning/40 bg-warning/[0.07] px-4 py-3 text-[13.5px]" data-testid="review-banner">
      <div className="flex items-start gap-2">
        <TriangleAlert className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="font-medium">{t("title")}</div>
          <p className="mt-0.5 text-muted">{why} {t("locked")}</p>
        </div>
        {canEdit ? (
          <Button size="sm" variant="secondary" onClick={() => done.mutate()} disabled={done.isPending}>{t("review")}</Button>
        ) : (
          <span className="text-[12px] text-subtle">{t("readOnly")}</span>
        )}
      </div>
    </div>
  );
}
