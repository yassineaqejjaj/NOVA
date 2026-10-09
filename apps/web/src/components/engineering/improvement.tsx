"use client";

import { Badge, Button, Card, Collapsible, CollapsibleContent, CollapsibleTrigger } from "@nova/ui";
import { ChevronDown } from "lucide-react";

import { ApiError } from "@/lib/api/client";
import { useMe } from "@/lib/api/hooks";
import { type PolicyVersion, usePolicy, usePolicyActions } from "@/lib/api/engineering";
import { useT } from "@/lib/i18n";

import { M } from "./engineering.messages";
import { num } from "./performance";

const TONE = { active: "success", candidate: "warning", retired: "neutral", rejected: "danger" } as const;

function Lessons({ version }: { version: PolicyVersion }) {
  const t = useT(M);
  const groups = [
    ...(version.standards.length ? [[t("learnStandards"), version.standards] as const] : []),
    ...Object.entries(version.stages).filter(([, l]) => l.length).map(([stage, lessons]) => [t(`st_${stage === "fix" ? "ci" : stage}` as "st_spec"), lessons] as const),
  ];
  if (groups.length === 0) return <p className="mt-2 text-[13px] text-subtle">{t("learnBase")}</p>;
  return (
    <div className="mt-3 space-y-3">
      {groups.map(([label, lessons]) => (
        <div key={label}>
          <h4 className="text-[12px] font-semibold uppercase tracking-wide text-subtle">{label}</h4>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[13px]">{lessons.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </div>
      ))}
      {version.advice.length ? (
        <div>
          <h4 className="text-[12px] font-semibold uppercase tracking-wide text-subtle">{t("learnAdvice")}</h4>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[13px] text-muted">{version.advice.map((l, i) => <li key={i}>{l}</li>)}</ul>
        </div>
      ) : null}
    </div>
  );
}

/** What NOVA's engineering agent learned from runs FORGE scored below its threshold, version by version. */
export function Improvement() {
  const t = useT(M);
  const { data } = usePolicy();
  const { data: me } = useMe();
  const actions = usePolicyActions();
  if (!data || !data.active) return data && !data.enabled ? <p className="mb-6 text-[12.5px] text-subtle">{t("learnDisabled")}</p> : null;
  const { active } = data;
  const others = data.history.filter((p) => p.id !== active.id);
  const error = actions.rollback.error ?? actions.activate.error;
  return (
    <Card className="mb-6 p-5" data-testid="improvement">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="flex items-center gap-2 text-[15px] font-semibold">
            {t("learnTitle")} <Badge tone="success" data-testid="policy-version">{t("learnVersion", { v: active.version })}</Badge>
          </h2>
          <p className="mt-0.5 max-w-2xl text-[12.5px] text-muted">{t("learnHint", { threshold: data.threshold })}</p>
        </div>
        {me?.is_admin && others.some((p) => p.version < active.version) ? (
          <Button size="sm" variant="secondary" onClick={() => actions.rollback.mutate()} disabled={actions.rollback.isPending}>{t("learnRollback")}</Button>
        ) : null}
      </div>
      <p className="mt-2 text-[12.5px] text-subtle">
        {active.runs > 0 ? t("learnRuns", { n: active.runs, score: num(active.avg_score) }) : t("learnNoRuns")}
        {!data.auto_deploy ? ` · ${t("learnManual")}` : ""}
      </p>
      <Lessons version={active} />
      {others.length > 0 ? (
        <Collapsible className="mt-4 border-t border-border/70 pt-3">
          <CollapsibleTrigger asChild>
            <Button variant="ghost" size="sm" className="-ml-2">{t("learnHistory")} ({others.length}) <ChevronDown className="size-4" /></Button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <ul className="mt-2 space-y-2">
              {others.map((p) => (
                <li key={p.id} className="rounded-[10px] bg-surface-2/50 px-3 py-2 text-[13px]" data-version={p.version}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{t("learnVersion", { v: p.version })}</span>
                    <Badge tone={TONE[p.status]}>{p.status === "candidate" ? t("learnCandidate") : p.status === "rejected" ? t("learnRejected") : t("learnRetired")}</Badge>
                    <span className="text-muted">{p.runs > 0 ? t("learnRuns", { n: p.runs, score: num(p.avg_score) }) : t("learnNoRuns")}</span>
                    {me?.is_admin && (p.status === "candidate" || p.status === "retired") ? (
                      <Button size="sm" variant="ghost" className="ml-auto" onClick={() => actions.activate.mutate(p.id)} disabled={actions.activate.isPending}>{t("learnApply")}</Button>
                    ) : null}
                  </div>
                  <p className="mt-1 text-[12px] text-subtle">{p.summary}</p>
                </li>
              ))}
            </ul>
          </CollapsibleContent>
        </Collapsible>
      ) : null}
      {error instanceof ApiError ? <p role="alert" className="mt-2 text-[13px] text-danger">{error.message}</p> : null}
    </Card>
  );
}
