"use client";

import { Badge, Button } from "@nova/ui";
import { CheckCircle2, Loader2, RefreshCw, RotateCcw } from "lucide-react";

import type { AgentProfile } from "@/lib/agents";
import {
  type ReleaseStatus,
  type ReleaseView,
  useApproveRelease,
  useEvaluateRelease,
  useReleases,
  useRollbackRelease,
} from "@/lib/api/releases";
import { dateTime, timeAgo } from "@/lib/format";
import { defineMessages, type Lang, useLang, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    title: "Releases",
    hint: "A version Nova Evals validated is first served to a share of users, compared with everyone else, then approved before it reaches all.",
    none: "No release yet.",
    exposure: (v: { p: number }) => `${v.p}% of users`,
    runs: (v: { n: number; min: number }) => `${v.n}/${v.min} runs observed`,
    withRelease: "With the new version",
    others: "Everyone else",
    failures: (v: { r: string; n: number; f: number }) => `${v.r} failed (${v.f}/${v.n})`,
    noRuns: "No run yet",
    gain: (v: { d: string }) => `Nova Evals gain ${v.d} pts`,
    approve: "Approve for everyone",
    rollback: "Roll back",
    evaluate: "Compare now",
    confirmRollback: "Withdraw this release? Users go back to the previous version.",
    confirmApprove: "Apply this version to every user?",
    by: (v: { who: string }) => `by ${v.who}`,
    system: "automatically",
    manual: "applied by an administrator",
    history: "History",
    watch: "Nova Evals watch",
    healthy: "no degradation on real traffic",
    degraded: "degradation detected",
    insufficient_data: "not enough runs yet",
  },
  fr: {
    title: "Déploiements",
    hint: "Une version validée par Nova Evals est d'abord servie à une part des utilisateurs, comparée aux autres, puis approuvée avant d'atteindre tout le monde.",
    none: "Aucun déploiement pour l'instant.",
    exposure: (v: { p: number }) => `${v.p} % des utilisateurs`,
    runs: (v: { n: number; min: number }) => `${v.n}/${v.min} exécutions observées`,
    withRelease: "Avec la nouvelle version",
    others: "Tous les autres",
    failures: (v: { r: string; n: number; f: number }) => `${v.r} en échec (${v.f}/${v.n})`,
    noRuns: "Aucune exécution",
    gain: (v: { d: string }) => `Gain Nova Evals ${v.d} pts`,
    approve: "Approuver pour tous",
    rollback: "Retirer",
    evaluate: "Comparer maintenant",
    confirmRollback: "Retirer ce déploiement ? Les utilisateurs reviennent à la version précédente.",
    confirmApprove: "Appliquer cette version à tous les utilisateurs ?",
    by: (v: { who: string }) => `par ${v.who}`,
    system: "automatiquement",
    manual: "appliquée par un administrateur",
    history: "Historique",
    watch: "Surveillance Nova Evals",
    healthy: "aucune dégradation sur le trafic réel",
    degraded: "dégradation détectée",
    insufficient_data: "pas encore assez d'exécutions",
  },
});

const STATUS: Record<ReleaseStatus, { tone: "neutral" | "accent" | "success" | "warning" | "danger"; en: string; fr: string }> = {
  awaiting_proof: { tone: "warning", en: "Awaiting proof", fr: "En attente de preuve" },
  canary: { tone: "accent", en: "Canary", fr: "Déploiement progressif" },
  awaiting_approval: { tone: "warning", en: "Awaiting approval", fr: "En attente d'approbation" },
  active: { tone: "success", en: "Active", fr: "Active" },
  rolled_back: { tone: "danger", en: "Rolled back", fr: "Retirée" },
  rejected: { tone: "neutral", en: "Not released", fr: "Non déployée" },
  superseded: { tone: "neutral", en: "Replaced", fr: "Remplacée" },
};

const OPEN: ReleaseStatus[] = ["awaiting_proof", "canary", "awaiting_approval"];
const rate = (v: number) => `${Math.round(v * 100)}%`;

function StatusBadge({ status, lang }: { status: ReleaseStatus; lang: Lang }) {
  const meta = STATUS[status];
  return <Badge tone={meta.tone}>{meta[lang]}</Badge>;
}

function CohortBox({ label, runs, failed, failureRate }: { label: string; runs: number; failed: number; failureRate: number }) {
  const t = useT(M);
  return (
    <div className="rounded-[10px] border border-border bg-bg/50 p-2.5">
      <div className="text-[11.5px] text-subtle">{label}</div>
      <div className="mt-0.5 text-[13px] font-medium tabular-nums">
        {runs ? t("failures", { r: rate(failureRate), n: runs, f: failed }) : <span className="text-muted">{t("noRuns")}</span>}
      </div>
    </div>
  );
}

function OpenRelease({ release, canManage }: { release: ReleaseView; canManage: boolean }) {
  const t = useT(M);
  const lang = useLang();
  const approve = useApproveRelease();
  const rollback = useRollbackRelease();
  const evaluate = useEvaluateRelease();
  const busy = approve.isPending || rollback.isPending || evaluate.isPending;
  const delta = release.evidence.delta;
  return (
    <div className="rounded-[12px] border border-accent/40 bg-accent/5 p-3" data-release={release.id} aria-live="polite">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[13px] font-semibold">{release.label}</span>
        <StatusBadge status={release.status} lang={lang} />
        <span className="text-[12px] text-subtle">{t("exposure", { p: release.canary_percent })}</span>
        {typeof delta === "number" ? <span className="text-[12px] text-subtle">· {t("gain", { d: `${delta > 0 ? "+" : ""}${delta.toFixed(1)}` })}</span> : null}
      </div>
      <p className="mt-1 text-[12.5px] text-muted">{release.reason}</p>
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <CohortBox label={t("withRelease")} runs={release.canary.runs} failed={release.canary.failed} failureRate={release.canary.failure_rate} />
        <CohortBox label={t("others")} runs={release.control.runs} failed={release.control.failed} failureRate={release.control.failure_rate} />
      </div>
      {release.status === "canary" ? (
        <div className="mt-2 flex items-center gap-2 text-[12px] text-subtle">
          <Loader2 className="size-3 animate-spin" aria-hidden />
          {t("runs", { n: release.canary.runs, min: release.min_runs })}
        </div>
      ) : null}
      {canManage ? (
        <div className="mt-3 flex flex-wrap gap-2">
          {release.status === "awaiting_approval" ? (
            <Button
              size="sm"
              variant="primary"
              disabled={busy}
              onClick={() => {
                if (window.confirm(t("confirmApprove"))) approve.mutate(release.id);
              }}
            >
              <CheckCircle2 className="size-3.5" aria-hidden /> {t("approve")}
            </Button>
          ) : null}
          {release.status === "canary" ? (
            <Button size="sm" variant="outline" disabled={busy} onClick={() => evaluate.mutate(release.id)}>
              <RefreshCw className="size-3.5" aria-hidden /> {t("evaluate")}
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => {
              if (window.confirm(t("confirmRollback"))) rollback.mutate(release.id);
            }}
          >
            <RotateCcw className="size-3.5" aria-hidden /> {t("rollback")}
          </Button>
        </div>
      ) : null}
    </div>
  );
}

/** Releases of one agent: the one in progress with its canary-versus-control comparison, then the history. */
export function ReleasesSection({ agent }: { agent: AgentProfile }) {
  const t = useT(M);
  const lang = useLang();
  const { data } = useReleases();
  if (!data) return null;
  const mine = data.releases.filter((r) => r.agent === agent);
  const open = mine.filter((r) => OPEN.includes(r.status));
  const past = mine.filter((r) => !OPEN.includes(r.status));
  const who = (r: ReleaseView) => {
    if (r.evidence.manual) return t("manual");
    if (!r.decided_by) return "";
    return r.decided_by === "system" ? t("system") : t("by", { who: r.decided_by.slice(0, 8) });
  };
  return (
    <section className="rounded-[16px] border border-border bg-surface p-4" aria-label={t("title")}>
      <h2 className="text-[13px] font-semibold">{t("title")}</h2>
      <p className="mb-3 text-[12px] text-subtle">{t("hint")}</p>
      {mine.length === 0 ? <p className="text-[13px] text-muted">{t("none")}</p> : null}
      <div className="space-y-3">
        {open.map((r) => (
          <OpenRelease key={r.id} release={r} canManage={data.can_manage} />
        ))}
      </div>
      {past.length ? (
        <ol className="mt-3 space-y-2" aria-label={t("history")}>
          {past.map((r) => (
            <li key={r.id} className="text-[12.5px]">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="font-medium">{r.label}</span>
                <StatusBadge status={r.status} lang={lang} />
                <span className="text-subtle" title={dateTime(r.decided_at ?? r.created_at)}>
                  {timeAgo(r.decided_at ?? r.created_at)} {who(r)}
                </span>
              </div>
              {r.reason ? <p className="text-muted">{r.reason}</p> : null}
              {r.status === "active" && r.evidence.health?.status ? (
                <p className="text-subtle" title={r.evidence.health.alerts.join(" · ") || undefined}>
                  {t("watch")} · {t(r.evidence.health.status)} · {timeAgo(r.evidence.health.checked_at)}
                </p>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}
