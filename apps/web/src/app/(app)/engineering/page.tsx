"use client";

import { Button, Card, Skeleton } from "@nova/ui";
import { GitPullRequest, Plus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { M } from "@/components/engineering/engineering.messages";
import { RunForm } from "@/components/engineering/run-form";
import { RunStatusBadge } from "@/components/engineering/status";
import { EmptyState, Page, PageHeader } from "@/components/shell/page";
import { useGithub, useLlmConfig, useRuns } from "@/lib/api/engineering";
import { timeAgo } from "@/lib/format";
import { useT } from "@/lib/i18n";

/** Engineering: NOVA carries a change through the whole software lifecycle. */
export default function EngineeringPage() {
  const t = useT(M);
  const router = useRouter();
  const { data: runs, isLoading } = useRuns();
  const { data: github } = useGithub();
  const { data: llm } = useLlmConfig();
  const [creating, setCreating] = useState(false);
  const missingLlm = llm ? !llm.configured : false;
  const missingGithub = github ? !github.linked : false;

  return (
    <Page>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button variant="primary" size="sm" onClick={() => setCreating(true)} disabled={creating || missingGithub} data-testid="new-run">
            <Plus className="size-4" /> {t("newRun")}
          </Button>
        }
      />

      {missingLlm || missingGithub ? (
        <Card className="mb-6 border-warning/30 bg-warning/[0.05] p-4" data-testid="eng-setup">
          <h2 className="text-[14px] font-semibold">{t("setupTitle")}</h2>
          <ul className="mt-2 space-y-1 text-[13px] text-muted">
            {missingLlm ? <li>• <Link href="/settings#llm" className="text-accent hover:underline">{t("setupLlm")}</Link></li> : null}
            {missingGithub ? <li>• <Link href="/settings#github" className="text-accent hover:underline">{t("setupGithub")}</Link></li> : null}
          </ul>
        </Card>
      ) : null}

      {creating ? (
        <Card className="mb-6 p-5">
          <RunForm onCreated={(id) => router.push(`/engineering/${id}`)} onCancel={() => setCreating(false)} />
        </Card>
      ) : null}

      {isLoading ? <Skeleton className="h-40" /> : null}
      {runs && runs.length === 0 && !creating ? <EmptyState icon={<GitPullRequest />} title={t("noRuns")} /> : null}
      <ul className="divide-y divide-border/70">
        {runs?.map((run) => (
          <li key={run.id}>
            <Link href={`/engineering/${run.id}`} className="flex items-center gap-3 py-3 hover:bg-surface-2/40" data-testid="run-row">
              <GitPullRequest className="size-4 shrink-0 text-subtle" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[14.5px] font-medium">{run.title}</div>
                <div className="truncate text-[12px] text-muted">
                  {run.repo} · {t(`k_${run.kind}` as "k_feature")}
                  {run.pr_number ? ` · #${run.pr_number}` : ""}
                </div>
              </div>
              <RunStatusBadge status={run.status} />
              {run.created_at ? <span className="hidden shrink-0 text-[12px] text-subtle sm:block">{timeAgo(run.created_at)}</span> : null}
            </Link>
          </li>
        ))}
      </ul>
    </Page>
  );
}
