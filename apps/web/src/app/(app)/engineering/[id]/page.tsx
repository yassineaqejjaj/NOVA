"use client";

import { Badge, Button, Card, Collapsible, CollapsibleContent, CollapsibleTrigger, cn, Input, Label, Skeleton, Switch, Textarea } from "@nova/ui";
import { ArrowLeft, ChevronDown, ExternalLink, GitBranch, Rocket } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { M } from "@/components/engineering/engineering.messages";
import { StageOutput } from "@/components/engineering/stage-output";
import { RunStatusBadge, StageIcon } from "@/components/engineering/status";
import { ErrorNotice, Page } from "@/components/shell/page";
import { ApiError } from "@/lib/api/client";
import { type Run, useRun, useRunAction } from "@/lib/api/engineering";
import { clock } from "@/lib/format";
import { useT } from "@/lib/i18n";

const err = (e: unknown) => (e instanceof ApiError ? <p role="alert" className="mt-2 text-[13px] text-danger">{e.message}</p> : null);

function Gate({ run }: { run: Run }) {
  const t = useT(M);
  const act = useRunAction(run.id);
  const [notes, setNotes] = useState("");
  if (run.status !== "waiting_user" || !run.gate) return null;
  const plan = run.gate === "plan";
  return (
    <Card className="mb-6 border-warning/40 bg-warning/[0.05] p-5" data-testid="gate">
      <h2 className="text-[15px] font-semibold">{plan ? t("approvePlan") : t("approveMerge")}</h2>
      <p className="mt-1 text-[13px] text-muted">{plan ? t("approvePlanHint") : t("approveMergeHint", { branch: run.base_branch })}</p>
      {plan ? (
        <div className="mt-3 space-y-1.5">
          <Label htmlFor="gate-notes">{t("notes")}</Label>
          <Textarea id="gate-notes" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
        </div>
      ) : null}
      {err(act.approve.error)}
      <div className="mt-4 flex flex-wrap gap-2">
        <Button variant="primary" size="sm" onClick={() => act.approve.mutate(notes)} disabled={act.approve.isPending} data-testid="approve">
          {plan ? t("approvePlan") : t("approveMerge")}
        </Button>
        {run.pr_url ? (
          <Button asChild variant="secondary" size="sm"><a href={run.pr_url} target="_blank" rel="noreferrer"><ExternalLink className="size-3.5" /> {t("openPr")}</a></Button>
        ) : null}
        <Button variant="ghost" size="sm" onClick={() => act.cancel.mutate()} disabled={act.cancel.isPending}>{t("cancelRun")}</Button>
      </div>
    </Card>
  );
}

function ReleaseCard({ run }: { run: Run }) {
  const t = useT(M);
  const act = useRunAction(run.id);
  const [edited, setTag] = useState<string | null>(null);
  const tag = edited ?? run.release?.version ?? "";
  const [draft, setDraft] = useState(true);
  if (run.status !== "completed" || !run.merge_sha) return null;
  return (
    <Card className="mb-6 p-5" data-testid="release-card">
      <h2 className="flex items-center gap-2 text-[15px] font-semibold"><Rocket className="size-4" /> {t("releaseTitle")}</h2>
      {run.release_url ? (
        <p className="mt-2 text-[13px]"><a className="text-accent hover:underline" href={run.release_url} target="_blank" rel="noreferrer">{t("releaseDone")} <ExternalLink className="inline size-3" /></a></p>
      ) : run.release ? (
        <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-end">
          <div className="space-y-1.5">
            <Label htmlFor="rel-tag">{t("releaseTag")}</Label>
            <Input id="rel-tag" value={tag} onChange={(e) => setTag(e.target.value)} placeholder="v1.0.0" />
          </div>
          <label className="flex items-center gap-2 pb-2 text-[13px]"><Switch checked={draft} onCheckedChange={setDraft} aria-label={t("releaseDraft")} />{t("releaseDraft")}</label>
          <Button size="sm" variant="secondary" disabled={!tag.trim() || act.release.isPending} onClick={() => act.release.mutate({ tag: tag.trim(), draft }, { onSuccess: () => toast(t("releaseDone")) })}>
            {t("releasePublish")}
          </Button>
        </div>
      ) : null}
      {err(act.release.error)}
      {run.has_deploy_hook ? (
        <div className="mt-4 border-t border-border/70 pt-4">
          <h3 className="text-[13.5px] font-medium">{t("deployTitle")}</h3>
          <p className="text-[12.5px] text-muted">{t("deployHint")}</p>
          <Button className="mt-2" size="sm" variant="secondary" disabled={act.deploy.isPending} onClick={() => act.deploy.mutate(undefined, { onSuccess: () => toast(t("deployDone")) })}>{t("deploy")}</Button>
          {err(act.deploy.error)}
        </div>
      ) : null}
    </Card>
  );
}

export default function RunPage() {
  const t = useT(M);
  const { id } = useParams<{ id: string }>();
  const { data: run, isLoading, error } = useRun(id);
  const act = useRunAction(id);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  if (error instanceof ApiError) return <Page><ErrorNotice title={error.message} actions={<Button asChild size="sm" variant="secondary"><Link href="/engineering">{t("back")}</Link></Button>} /></Page>;
  if (isLoading || !run) return <Page><Skeleton className="h-60" /></Page>;
  const total = (run.usage.input_tokens ?? 0) + (run.usage.output_tokens ?? 0);

  return (
    <Page>
      <Link href="/engineering" className="mb-4 inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ArrowLeft className="size-3.5" /> {t("back")}</Link>
      <header className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[24px] font-semibold tracking-tight" data-testid="run-title">{run.title}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted">
            <span>{run.repo}</span>
            <Badge>{t(`k_${run.kind}` as "k_feature")}</Badge>
            {run.kind !== "review" ? <Badge>{t(run.autonomy)}</Badge> : null}
            {run.branch ? <span className="inline-flex items-center gap-1"><GitBranch className="size-3.5" /> {run.branch}</span> : null}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <RunStatusBadge status={run.status} />
          {run.pr_url ? <Button asChild size="sm" variant="secondary"><a href={run.pr_url} target="_blank" rel="noreferrer"><ExternalLink className="size-3.5" /> #{run.pr_number}</a></Button> : null}
          {run.status === "running" || run.status === "queued" ? <Button size="sm" variant="ghost" onClick={() => act.cancel.mutate()} disabled={act.cancel.isPending}>{t("cancelRun")}</Button> : null}
        </div>
      </header>

      {run.status === "failed" ? (
        <div className="mb-6" data-testid="run-error">
          <ErrorNotice
            title={t("errorTitle")}
            message={run.error}
            actions={<Button size="sm" variant="secondary" onClick={() => act.retry.mutate()} disabled={act.retry.isPending}>{t("retry")}</Button>}
          />
          {err(act.retry.error)}
        </div>
      ) : null}

      <Gate run={run} />
      <ReleaseCard run={run} />

      <ol className="space-y-2" data-testid="stages">
        {run.stages.map((stage) => {
          const expandable = stage.status === "done" && stage.output && Object.keys(stage.output).length > 0;
          return (
            <li key={stage.key} data-stage={stage.key} data-status={stage.status}>
              <Collapsible open={!!open[stage.key]} onOpenChange={(v) => setOpen((s) => ({ ...s, [stage.key]: v }))}>
                <div className={cn("rounded-[14px] border px-4 py-3", stage.status === "running" || stage.status === "waiting" ? "border-accent/40 bg-accent-soft/40" : "border-border")}>
                  <div className="flex items-center gap-3">
                    <StageIcon status={stage.status} />
                    <div className="min-w-0 flex-1">
                      <div className="text-[14px] font-medium">{t(`st_${stage.key}` as "st_spec")}</div>
                      {stage.summary ? <div className="line-clamp-2 text-[12.5px] text-muted">{stage.summary}</div> : null}
                    </div>
                    {stage.finished_at ? <span className="hidden text-[11.5px] text-subtle sm:block">{clock(stage.finished_at)}</span> : null}
                    {expandable ? <CollapsibleTrigger asChild><Button variant="ghost" size="sm" aria-label={t(`st_${stage.key}` as "st_spec")}><ChevronDown className="size-4" /></Button></CollapsibleTrigger> : null}
                  </div>
                  {expandable ? <CollapsibleContent><StageOutput stage={stage} /></CollapsibleContent> : null}
                </div>
              </Collapsible>
            </li>
          );
        })}
      </ol>

      {run.log && run.log.length > 0 ? (
        <section className="mt-8">
          <h2 className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-subtle">{t("activity")}</h2>
          <ul className="space-y-1 text-[12.5px]">
            {[...run.log].reverse().slice(0, 40).map((l, n) => (
              <li key={n} className={cn("flex gap-2", l.level === "error" ? "text-danger" : "text-muted")}>
                <span className="w-12 shrink-0 tabular-nums text-subtle">{clock(l.at)}</span>
                <span>{l.message}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {run.model ? <p className="mt-6 text-[12px] text-subtle">{t("usage", { calls: run.usage.model_calls ?? 0, tokens: total.toLocaleString(), model: run.model })}</p> : null}
    </Page>
  );
}
