"use client";

import { Badge, Button, Skeleton } from "@nova/ui";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { EmptyState, ErrorNotice, Page, PageHeader } from "@/components/shell/page";
import { api } from "@/lib/api/client";
import { timeAgo } from "@/lib/format";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    title: "Nova Quality",
    description: "How your work was evaluated by Nova Quality. NOVA sends outcomes for evaluation; the scenarios and judges live there.",
    open: "Open Nova Quality",
    loadFailed: "Nova Quality could not be loaded",
    link: "Link",
    linkOk: "Connected",
    linkDegraded: "Degraded",
    linkOff: "Not configured",
    evaluated: "Evaluated",
    average: "Average score",
    passRate: "Pass rate",
    recent: "Recent evaluations",
    empty: "No evaluation yet",
    emptyHint: "Evaluations appear here once Nova Quality has scored your work.",
    passed: "Passed",
    failed: "Failed",
    pending: "Pending",
    training: "Teach NOVA from evaluations",
  },
  fr: {
    title: "Nova Quality",
    description: "Comment votre travail a été évalué par Nova Quality. NOVA envoie les résultats à évaluer ; les scénarios et les juges y vivent.",
    open: "Ouvrir Nova Quality",
    loadFailed: "Nova Quality n’a pas pu être chargé",
    link: "Lien",
    linkOk: "Connecté",
    linkDegraded: "Dégradé",
    linkOff: "Non configuré",
    evaluated: "Évalués",
    average: "Score moyen",
    passRate: "Taux de réussite",
    recent: "Évaluations récentes",
    empty: "Aucune évaluation pour l’instant",
    emptyHint: "Les évaluations apparaissent ici dès que Nova Quality a noté votre travail.",
    passed: "Réussi",
    failed: "Échoué",
    pending: "En attente",
    training: "Faire progresser NOVA avec les évaluations",
  },
});

interface Evaluation {
  task_id: string;
  objective: string;
  score: number | null;
  passed: boolean | null;
  status: string | null;
  url: string | null;
  at: string;
}

interface Overview {
  forge_url: string;
  monitoring: boolean;
  link: { last_success_at: string | null; last_error_at: string | null; last_error: string | null };
  summary: { evaluated: number; average_score: number | null; pass_rate: number | null };
  recent: Evaluation[];
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[12px] border border-border bg-surface p-4">
      <div className="text-[12px] font-medium uppercase tracking-wider text-subtle">{label}</div>
      <div className="mt-1 text-[24px] font-semibold tracking-tight">{value}</div>
    </div>
  );
}

export default function QualityPage() {
  const t = useT(M);
  const { data, isLoading, isError } = useQuery({ queryKey: ["quality"], queryFn: () => api.get<Overview>("/quality") });

  if (isLoading) return <Page><Skeleton className="h-40" /></Page>;
  if (isError || !data) return <Page><ErrorNotice title={t("loadFailed")} /></Page>;

  const failing = data.link.last_error_at && (!data.link.last_success_at || data.link.last_error_at > data.link.last_success_at);
  const linkLabel = !data.monitoring ? t("linkOff") : failing ? t("linkDegraded") : t("linkOk");
  const verdict = (e: Evaluation) => (e.passed === null ? t("pending") : e.passed ? t("passed") : t("failed"));

  return (
    <Page wide>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={<Button variant="ghost" size="sm" asChild><a href={data.forge_url} target="_blank" rel="noreferrer">{t("open")} <ExternalLink /></a></Button>}
      />
      <div className="mb-6 flex items-center gap-2 text-[13px] text-muted" data-testid="quality-link">
        {t("link")} <Badge>{linkLabel}</Badge>
      </div>
      <div className="mb-8 grid gap-3 sm:grid-cols-3">
        <Stat label={t("evaluated")} value={String(data.summary.evaluated)} />
        <Stat label={t("average")} value={data.summary.average_score === null ? "—" : String(data.summary.average_score)} />
        <Stat label={t("passRate")} value={data.summary.pass_rate === null ? "—" : `${data.summary.pass_rate}%`} />
      </div>
      <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">{t("recent")}</h2>
      {data.recent.length === 0 ? (
        <EmptyState icon={<ShieldCheck />} title={t("empty")} description={t("emptyHint")} />
      ) : (
        <ul className="divide-y divide-border rounded-[12px] border border-border bg-surface">
          {data.recent.map((e) => (
            <li key={e.task_id} className="flex items-center gap-3 px-4 py-3 text-[13.5px]">
              <Link href={`/work?task=${e.task_id}`} className="min-w-0 flex-1 truncate hover:underline">{e.objective}</Link>
              <Badge>{verdict(e)}</Badge>
              <span className="w-12 text-right tabular-nums">{e.score ?? "—"}</span>
              <span className="w-24 text-right text-[12px] text-subtle">{timeAgo(e.at)}</span>
              {e.url ? <a href={e.url} target="_blank" rel="noreferrer" className="text-accent"><ExternalLink className="size-3.5" /></a> : <span className="size-3.5" />}
            </li>
          ))}
        </ul>
      )}
      <Link href="/team/training" className="mt-6 inline-block text-[13px] text-accent hover:underline">{t("training")}</Link>
    </Page>
  );
}
