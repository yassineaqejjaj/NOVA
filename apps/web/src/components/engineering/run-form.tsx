"use client";

import { Button, cn, Input, Label, Select, Switch, Textarea } from "@nova/ui";
import { Bug, GitPullRequestArrow, Hammer, Sparkles } from "lucide-react";
import { useState } from "react";

import { ApiError } from "@/lib/api/client";
import { type RunInput, type RunKind, useCreateRun, useRepos } from "@/lib/api/engineering";
import { useT } from "@/lib/i18n";

import { M } from "./engineering.messages";

const KINDS: { value: RunKind; icon: typeof Sparkles }[] = [
  { value: "feature", icon: Sparkles },
  { value: "bugfix", icon: Bug },
  { value: "refactor", icon: Hammer },
  { value: "review", icon: GitPullRequestArrow },
];

export function RunForm({ onCreated, onCancel }: { onCreated: (id: string) => void; onCancel: () => void }) {
  const t = useT(M);
  const repos = useRepos(true);
  const create = useCreateRun();
  const [kind, setKind] = useState<RunKind>("feature");
  const [repo, setRepo] = useState("");
  const [goal, setGoal] = useState("");
  const [issue, setIssue] = useState("");
  const [pr, setPr] = useState("");
  const [postReview, setPostReview] = useState(false);
  const [autonomy, setAutonomy] = useState<"guided" | "autopilot">("guided");
  const [autoMerge, setAutoMerge] = useState(false);
  const [hook, setHook] = useState("");

  const review = kind === "review";
  const ready = review ? pr.trim().length > 10 : repo.trim().includes("/") && (goal.trim().length >= 10 || issue.trim().length > 10);

  const submit = () => {
    const body: RunInput = review
      ? { kind, pr_url: pr.trim(), post_review: postReview, autonomy: "guided", auto_merge: false }
      : {
          kind,
          repo: repo.trim(),
          goal: goal.trim(),
          issue_url: issue.trim(),
          autonomy,
          auto_merge: autonomy === "autopilot" && autoMerge,
          deploy_hook: hook.trim() || null,
        };
    create.mutate(body, { onSuccess: (run) => onCreated(run.id) });
  };

  return (
    <form
      className="space-y-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (ready && !create.isPending) submit();
      }}
    >
      <div>
        <Label>{t("kind")}</Label>
        <div role="radiogroup" aria-label={t("kind")} className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {KINDS.map(({ value, icon: Icon }) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={kind === value}
              onClick={() => setKind(value)}
              className={cn(
                "flex items-center gap-2 rounded-[12px] border px-3 py-2.5 text-[13.5px] transition-colors",
                kind === value ? "border-accent/50 bg-accent-soft font-medium" : "border-border text-muted hover:border-border-strong",
              )}
            >
              <Icon className="size-4" />
              {t(`k_${value}` as "k_feature")}
            </button>
          ))}
        </div>
      </div>

      {review ? (
        <>
          <div className="space-y-1.5">
            <Label htmlFor="run-pr">{t("pr")}</Label>
            <Input id="run-pr" value={pr} onChange={(e) => setPr(e.target.value)} placeholder={t("prPlaceholder")} autoComplete="off" />
          </div>
          <label className="flex items-center gap-2.5 text-[13.5px]">
            <Switch checked={postReview} onCheckedChange={setPostReview} aria-label={t("postReview")} />
            {t("postReview")}
          </label>
        </>
      ) : (
        <>
          <div className="space-y-1.5">
            <Label htmlFor="run-repo">{t("repo")}</Label>
            {repos.data && repos.data.length > 0 ? (
              <Select
                value={repos.data.some((r) => r.full_name === repo) ? repo : ""}
                onValueChange={setRepo}
                placeholder={t("pickRepo")}
                options={repos.data.filter((r) => r.can_push).map((r) => ({ value: r.full_name, label: r.full_name, hint: r.private ? "private" : undefined }))}
                className="w-full"
                ariaLabel={t("repo")}
              />
            ) : (
              <Input id="run-repo" value={repo} onChange={(e) => setRepo(e.target.value)} placeholder={t("repoPlaceholder")} autoComplete="off" />
            )}
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="run-goal">{t("goal")}</Label>
            <Textarea id="run-goal" value={goal} onChange={(e) => setGoal(e.target.value)} rows={4} placeholder={kind === "bugfix" ? t("bugPlaceholder") : t("goalPlaceholder")} />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="run-issue">{t("issue")}</Label>
            <Input id="run-issue" value={issue} onChange={(e) => setIssue(e.target.value)} placeholder={t("issuePlaceholder")} autoComplete="off" />
          </div>
          <div>
            <Label>{t("autonomy")}</Label>
            <div role="radiogroup" aria-label={t("autonomy")} className="mt-2 grid gap-2 sm:grid-cols-2">
              {(["guided", "autopilot"] as const).map((level) => (
                <button
                  key={level}
                  type="button"
                  role="radio"
                  aria-checked={autonomy === level}
                  onClick={() => setAutonomy(level)}
                  className={cn("rounded-[12px] border px-3 py-2.5 text-left transition-colors", autonomy === level ? "border-accent/50 bg-accent-soft" : "border-border hover:border-border-strong")}
                >
                  <span className="block text-[13.5px] font-medium">{t(level)}</span>
                  <span className="block text-[12.5px] text-muted">{t(`${level}Hint` as "guidedHint")}</span>
                </button>
              ))}
            </div>
          </div>
          {autonomy === "autopilot" ? (
            <label className="flex items-start gap-2.5 text-[13.5px]">
              <Switch checked={autoMerge} onCheckedChange={setAutoMerge} aria-label={t("autoMerge")} className="mt-0.5" />
              {t("autoMerge")}
            </label>
          ) : null}
          <div className="space-y-1.5">
            <Label htmlFor="run-hook">{t("deployHook")}</Label>
            <Input id="run-hook" type="password" value={hook} onChange={(e) => setHook(e.target.value)} placeholder={t("deployHookPlaceholder")} autoComplete="off" />
            <p className="text-[12px] text-subtle">{t("deployHookHint")}</p>
          </div>
        </>
      )}

      {create.error instanceof ApiError ? <p role="alert" className="text-[13px] text-danger">{create.error.message}</p> : null}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" onClick={onCancel}>{t("cancelForm")}</Button>
        <Button type="submit" variant="primary" size="sm" disabled={!ready || create.isPending}>{create.isPending ? t("starting") : t("start")}</Button>
      </div>
    </form>
  );
}
