"use client";

import { Card, Select, Skeleton } from "@nova/ui";
import { useState } from "react";

import { type RunEvaluation, type RunMetrics, useMetrics } from "@/lib/api/engineering";
import { useT } from "@/lib/i18n";

import { M } from "./engineering.messages";

export const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);
export const num = (v: number | null) => (v === null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: 1 }));
export const compact = (v: number | null) => (v === null ? "—" : new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(v));
export function duration(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 90) return `${seconds}s`;
  const minutes = Math.round(seconds / 60);
  return minutes < 90 ? `${minutes} min` : `${(minutes / 60).toFixed(1)} h`;
}

function Tile({ label, value, hint, testId }: { label: string; value: string; hint?: string; testId?: string }) {
  return (
    <div className="rounded-[12px] bg-surface-2/60 px-3.5 py-3" data-testid={testId}>
      <div className="text-[12px] text-muted">{label}</div>
      <div className="mt-0.5 text-[22px] font-semibold tabular-nums tracking-tight">{value}</div>
      {hint ? <div className="mt-0.5 text-[11.5px] text-subtle">{hint}</div> : null}
    </div>
  );
}

/** Evaluation of NOVA's delivery runs: success, CI repairs, cost. */
export function Performance() {
  const t = useT(M);
  const [days, setDays] = useState(30);
  const { data, isLoading } = useMetrics(days);
  const finished = data ? data.completed + data.failed : 0;
  return (
    <Card className="mb-6 p-5" data-testid="performance">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold">{t("perfTitle")}</h2>
          <p className="mt-0.5 text-[12.5px] text-muted">{t("perfHint", { days })}</p>
        </div>
        <Select
          value={String(days)}
          onValueChange={(v) => setDays(Number(v))}
          options={[7, 30, 90].map((d) => ({ value: String(d), label: `${d} d` }))}
          className="w-24"
          ariaLabel={t("perfTitle")}
        />
      </div>
      {isLoading ? <Skeleton className="mt-4 h-24" /> : null}
      {data && finished === 0 ? <p className="mt-4 text-[13px] text-subtle">{t("perfEmpty")}</p> : null}
      {data && finished > 0 ? <Figures data={data} /> : null}
    </Card>
  );
}

function Figures({ data }: { data: RunMetrics }) {
  const t = useT(M);
  const failures = Object.entries(data.failures_by_stage);
  const models = Object.entries(data.by_model);
  return (
    <div className="mt-4 space-y-4">
      <div className="grid grid-cols-2 gap-2.5 md:grid-cols-4">
        <Tile testId="p-success" label={t("p_success")} value={pct(data.success_rate)} hint={t("p_successHint", { done: data.completed, failed: data.failed })} />
        <Tile label={t("p_merged")} value={pct(data.merged_rate)} />
        <Tile label={t("p_firstPass")} value={pct(data.first_pass_ci_rate)} />
        <Tile label={t("p_ciRepairs")} value={num(data.avg_ci_fix_rounds)} />
        <Tile label={t("p_reviewRepairs")} value={num(data.avg_review_fix_rounds)} />
        <Tile label={t("p_tokens")} value={compact(data.avg_tokens)} hint={t("p_tokensHint", { calls: num(data.avg_model_calls) })} />
        <Tile label={t("p_duration")} value={duration(data.avg_duration_seconds)} />
        <Tile label={t("p_interventions")} value={num(data.avg_human_interventions)} />
      </div>
      {failures.length > 0 ? (
        <p className="text-[12.5px] text-muted">
          <span className="font-medium text-text">{t("p_failures")}:</span>{" "}
          {failures.map(([stage, n]) => `${t(`st_${stage}` as "st_spec")} (${n})`).join(" · ")}
        </p>
      ) : null}
      {models.length > 1 ? (
        <p className="text-[12.5px] text-muted">
          <span className="font-medium text-text">{t("p_models")}:</span>{" "}
          {models.map(([model, m]) => `${model} — ${t("p_runsCount", { n: m.runs })}, ${pct(m.success_rate)}`).join(" · ")}
        </p>
      ) : null}
    </div>
  );
}

/** The same signals for one run. */
export function RunEvaluationCard({ evaluation: e }: { evaluation: RunEvaluation }) {
  const t = useT(M);
  const item = (label: string, value: string) => (
    <div>
      <dt className="text-[11.5px] text-subtle">{label}</dt>
      <dd className="text-[14px] font-medium tabular-nums">{value}</dd>
    </div>
  );
  return (
    <section className="mt-8" data-testid="run-evaluation">
      <h2 className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-subtle">{t("evalTitle")}</h2>
      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 md:grid-cols-6">
        {item(t("e_ciRepairs"), String(e.ci_fix_rounds))}
        {item(t("e_firstPass"), e.reached_ci ? (e.first_pass_ci ? t("yes") : t("no")) : "—")}
        {item(t("e_reviewFixes"), String(e.review_fix_rounds))}
        {item(t("e_interventions"), String(e.human_interventions))}
        {item(t("e_tokens"), compact(e.tokens))}
        {item(t("e_duration"), duration(e.duration_seconds))}
      </dl>
    </section>
  );
}
