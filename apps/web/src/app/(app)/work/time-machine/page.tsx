"use client";

import { Badge, Button, Select, Skeleton } from "@nova/ui";
import { ArrowLeft, History, Loader2, Play } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Page, PageHeader } from "@/components/shell/page";
import { useTask } from "@/lib/api/hooks";
import {
  type Comparison,
  type ReplayRequest,
  type ReplayRow,
  isOpenReplay,
  useComparison,
  useReplayOptions,
  useReplays,
  useStartReplay,
} from "@/lib/api/time-machine";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    title: "Time Machine",
    description: "Replay a finished run with other context, another model or other lessons, and see exactly what changed.",
    back: "Back to tasks",
    original: "Original run",
    whatIf: "What if…",
    context: "Context",
    ctxOriginal: "Same sources as before",
    ctxLive: "Fresh ORBIT retrieval",
    ctxNone: "No context at all",
    model: "Model",
    modelDefault: "Same model",
    lessons: "Lessons",
    lessonsDefault: "Active lessons",
    lessonsOf: (v: { agent: string; v: number; n: number; s: string }) => `${v.agent} v${v.v} · ${v.n} lesson${v.n === 1 ? "" : "s"}${v.s === "active" ? " (active)" : ""}`,
    replay: "Replay",
    replaying: "Replaying…",
    replayCost: "A replay is a real run: it costs tokens. It never writes to external systems.",
    attempts: "Replays",
    none: "No replay yet.",
    open: "Compare",
    running: "Running…",
    failed: "Failed",
    done: "Done",
    metrics: "Run",
    tokens: "Tokens",
    duration: "Duration",
    sources: "Context sources",
    sufficiency: "Context sufficiency",
    modelLabel: "Model",
    status: "Outcome",
    result: "Result",
    unchanged: "The two runs produced the same sections.",
    changedSections: (v: { n: number }) => `${v.n} section${v.n === 1 ? "" : "s"} changed`,
    before: "Before",
    after: "After",
    added: "added",
    removed: "removed",
    changed: "changed",
    words: (v: { a: number; b: number }) => `${v.a} → ${v.b} words`,
    cheaper: (v: { p: number }) => `${v.p}% cheaper`,
    pricier: (v: { p: number }) => `${v.p}% more expensive`,
    faster: (v: { p: number }) => `${v.p}% faster`,
    slower: (v: { p: number }) => `${v.p}% slower`,
    sameCost: "Same cost",
    sameTime: "Same time",
    notFinished: "Pick a finished replay to compare.",
    noTask: "Open the Time Machine from a task.",
    unknown: "—",
    seconds: (v: { n: number }) => `${v.n}s`,
  },
  fr: {
    title: "Machine à remonter le temps",
    description: "Rejouez une exécution terminée avec un autre contexte, un autre modèle ou d'autres leçons, et voyez précisément ce qui change.",
    back: "Retour aux tâches",
    original: "Exécution d'origine",
    whatIf: "Et si…",
    context: "Contexte",
    ctxOriginal: "Mêmes sources qu'avant",
    ctxLive: "Nouvelle recherche ORBIT",
    ctxNone: "Aucun contexte",
    model: "Modèle",
    modelDefault: "Même modèle",
    lessons: "Leçons",
    lessonsDefault: "Leçons actives",
    lessonsOf: (v: { agent: string; v: number; n: number; s: string }) => `${v.agent} v${v.v} · ${v.n} leçon${v.n === 1 ? "" : "s"}${v.s === "active" ? " (active)" : ""}`,
    replay: "Rejouer",
    replaying: "Relecture…",
    replayCost: "Un rejeu est une vraie exécution : il consomme des tokens. Il n'écrit jamais dans un système externe.",
    attempts: "Rejeux",
    none: "Aucun rejeu pour l'instant.",
    open: "Comparer",
    running: "En cours…",
    failed: "Échec",
    done: "Terminé",
    metrics: "Exécution",
    tokens: "Tokens",
    duration: "Durée",
    sources: "Sources de contexte",
    sufficiency: "Suffisance du contexte",
    modelLabel: "Modèle",
    status: "Issue",
    result: "Résultat",
    unchanged: "Les deux exécutions ont produit les mêmes sections.",
    changedSections: (v: { n: number }) => `${v.n} section${v.n === 1 ? "" : "s"} modifiée${v.n === 1 ? "" : "s"}`,
    before: "Avant",
    after: "Après",
    added: "ajoutée",
    removed: "retirée",
    changed: "modifiée",
    words: (v: { a: number; b: number }) => `${v.a} → ${v.b} mots`,
    cheaper: (v: { p: number }) => `${v.p} % moins cher`,
    pricier: (v: { p: number }) => `${v.p} % plus cher`,
    faster: (v: { p: number }) => `${v.p} % plus rapide`,
    slower: (v: { p: number }) => `${v.p} % plus lent`,
    sameCost: "Même coût",
    sameTime: "Même durée",
    notFinished: "Choisissez un rejeu terminé pour comparer.",
    noTask: "Ouvrez la machine à remonter le temps depuis une tâche.",
    unknown: "—",
    seconds: (v: { n: number }) => `${v.n} s`,
  },
});

export default function TimeMachinePage() {
  return (
    <Suspense fallback={<Page wide><Skeleton className="h-64" /></Page>}>
      <TimeMachine />
    </Suspense>
  );
}

function TimeMachine() {
  const t = useT(M);
  const router = useRouter();
  const params = useSearchParams();
  const taskId = params.get("task");
  const replayId = params.get("replay");
  const { data: task } = useTask(taskId);
  const { data: replays } = useReplays(taskId);
  const selected = replays?.find((r) => r.id === replayId) ?? null;
  const finished = !!selected && !isOpenReplay(selected.status);
  const { data: comparison } = useComparison(taskId, replayId, finished);
  const pick = (id: string) => router.replace(`/work/time-machine?task=${taskId}&replay=${id}`, { scroll: false });

  if (!taskId) {
    return (
      <Page wide>
        <p className="text-muted">{t("noTask")}</p>
      </Page>
    );
  }
  return (
    <Page wide>
      <Link href={`/work?task=${taskId}`} className="mb-3 inline-flex items-center gap-1 text-[13px] text-muted hover:text-text">
        <ArrowLeft className="size-3.5" aria-hidden /> {t("back")}
      </Link>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="mb-4 rounded-[12px] border border-border bg-surface p-3 text-[13px]">
        <span className="text-subtle">{t("original")} · </span>
        {task ? task.objective : <Skeleton className="inline-block h-4 w-64 align-middle" />}
      </div>
      <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
        <div className="space-y-4">
          <WhatIf taskId={taskId} onStarted={pick} />
          <ReplayList replays={replays} selected={replayId} onPick={pick} />
        </div>
        <div>{comparison ? <CompareView data={comparison} /> : <p className="text-[13px] text-subtle">{t("notFinished")}</p>}</div>
      </div>
    </Page>
  );
}

function WhatIf({ taskId, onStarted }: { taskId: string; onStarted: (replayId: string) => void }) {
  const t = useT(M);
  const { data: options } = useReplayOptions();
  const start = useStartReplay(taskId);
  const [context, setContext] = useState<ReplayRequest["context"]>("original");
  const [model, setModel] = useState("default");
  const [policy, setPolicy] = useState("default");
  const run = () => {
    const body: ReplayRequest = { context };
    if (model !== "default") body.model = model;
    if (policy !== "default") body.learning_policy_id = policy;
    start.mutate(body, { onSuccess: (r) => onStarted(r.id) });
  };
  return (
    <div className="space-y-3 rounded-[16px] border border-border bg-surface p-4">
      <h2 className="text-[14px] font-semibold">{t("whatIf")}</h2>
      <Field label={t("context")}>
        <Select
          className="w-full"
          ariaLabel={t("context")}
          value={context}
          onValueChange={(v) => setContext(v as ReplayRequest["context"])}
          options={[
            { value: "original", label: t("ctxOriginal") },
            { value: "live", label: t("ctxLive") },
            { value: "none", label: t("ctxNone") },
          ]}
        />
      </Field>
      {options?.models.length ? (
        <Field label={t("model")}>
          <Select
            className="w-full"
            ariaLabel={t("model")}
            value={model}
            onValueChange={setModel}
            options={[{ value: "default", label: t("modelDefault") }, ...options.models.map((m) => ({ value: m, label: m }))]}
          />
        </Field>
      ) : null}
      {options?.policies.length ? (
        <Field label={t("lessons")}>
          <Select
            className="w-full"
            ariaLabel={t("lessons")}
            value={policy}
            onValueChange={setPolicy}
            options={[
              { value: "default", label: t("lessonsDefault") },
              ...options.policies.map((p) => ({ value: p.id, label: t("lessonsOf", { agent: p.agent, v: p.version, n: p.lessons, s: p.status }) })),
            ]}
          />
        </Field>
      ) : null}
      <Button variant="primary" size="sm" className="w-full" disabled={start.isPending} onClick={run}>
        {start.isPending ? <Loader2 className="size-4 animate-spin" aria-hidden /> : <Play className="size-4" aria-hidden />}
        {start.isPending ? t("replaying") : t("replay")}
      </Button>
      <p className="text-[11.5px] text-subtle">{t("replayCost")}</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <div className="text-[11.5px] text-subtle">{label}</div>
      {children}
    </div>
  );
}

function ReplayList({ replays, selected, onPick }: { replays: ReplayRow[] | undefined; selected: string | null; onPick: (id: string) => void }) {
  const t = useT(M);
  return (
    <div className="rounded-[16px] border border-border bg-surface p-4">
      <h2 className="mb-2 flex items-center gap-1.5 text-[14px] font-semibold">
        <History className="size-4" aria-hidden /> {t("attempts")}
      </h2>
      {!replays ? <Skeleton className="h-12" /> : null}
      {replays?.length === 0 ? <p className="text-[12.5px] text-subtle">{t("none")}</p> : null}
      <ul className="space-y-1.5">
        {replays?.map((r) => (
          <li key={r.id}>
            <button
              type="button"
              onClick={() => onPick(r.id)}
              aria-current={r.id === selected}
              className={`flex w-full items-center justify-between gap-2 rounded-[10px] border px-2.5 py-2 text-left text-[12.5px] ${r.id === selected ? "border-accent" : "border-border hover:border-border-strong"}`}
            >
              <span className="min-w-0 truncate">{Object.entries(r.overrides).map(([k, v]) => `${k}: ${v}`).join(" · ") || "—"}</span>
              <Badge tone={isOpenReplay(r.status) ? "accent" : r.status === "completed" ? "success" : "danger"}>
                {isOpenReplay(r.status) ? t("running") : r.status === "completed" ? t("done") : t("failed")}
              </Badge>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function CompareView({ data }: { data: Comparison }) {
  const t = useT(M);
  const seconds = (n: number | null) => (n === null ? t("unknown") : t("seconds", { n }));
  const tokenLine = (d: number | null) => (d === null ? null : d === 0 ? t("sameCost") : d < 0 ? t("cheaper", { p: Math.round(-d * 100) }) : t("pricier", { p: Math.round(d * 100) }));
  const timeLine = (d: number | null) => (d === null ? null : d === 0 ? t("sameTime") : d < 0 ? t("faster", { p: Math.round(-d * 100) }) : t("slower", { p: Math.round(d * 100) }));
  const rows: { label: string; a: string; b: string; note?: string | null; good?: boolean }[] = [
    { label: t("status"), a: data.original.status, b: data.replay.status },
    { label: t("modelLabel"), a: data.original.model ?? t("unknown"), b: data.replay.model ?? t("unknown") },
    { label: t("tokens"), a: String(data.original.tokens ?? t("unknown")), b: String(data.replay.tokens ?? t("unknown")), note: tokenLine(data.delta.tokens), good: (data.delta.tokens ?? 0) < 0 },
    { label: t("duration"), a: seconds(data.original.duration_seconds), b: seconds(data.replay.duration_seconds), note: timeLine(data.delta.duration), good: (data.delta.duration ?? 0) < 0 },
    { label: t("sources"), a: String(data.original.context_items ?? t("unknown")), b: String(data.replay.context_items ?? t("unknown")) },
    { label: t("sufficiency"), a: data.original.context_sufficiency ?? t("unknown"), b: data.replay.context_sufficiency ?? t("unknown") },
  ];
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-[16px] border border-border bg-surface">
        <div className="grid grid-cols-[1fr_1fr_1fr] gap-px bg-border text-[12.5px]">
          <div className="bg-surface-2 px-3 py-2 font-medium">{t("metrics")}</div>
          <div className="bg-surface-2 px-3 py-2 font-medium">{t("original")}</div>
          <div className="bg-surface-2 px-3 py-2 font-medium">{t("whatIf")}</div>
          {rows.map((r) => (
            <div key={r.label} className="contents">
              <div className="bg-surface px-3 py-2 text-subtle">{r.label}</div>
              <div className="bg-surface px-3 py-2 tabular-nums">{r.a}</div>
              <div className="bg-surface px-3 py-2 tabular-nums">
                {r.b}
                {r.note ? <span className={`ml-2 text-[11.5px] ${r.good ? "text-success" : "text-warning"}`}>{r.note}</span> : null}
              </div>
            </div>
          ))}
        </div>
      </div>
      <h2 className="text-[14px] font-semibold">
        {t("result")} · {data.sections_changed ? t("changedSections", { n: data.sections_changed }) : t("unchanged")}
      </h2>
      {data.artifacts.map((a, i) => (
        <div key={`${a.type}-${i}`} className="rounded-[16px] border border-border bg-surface p-4">
          <div className="mb-2 flex items-center justify-between gap-2 text-[13px]">
            <span className="font-medium">{a.title || a.type}</span>
            <span className="text-subtle">{t("words", { a: a.words.original, b: a.words.replay })}</span>
          </div>
          <div className="space-y-3">
            {a.sections.map((s) => (
              <div key={s.key}>
                <div className="mb-1 flex items-center gap-2 text-[12px] text-subtle">
                  <code>{s.key}</code> <Badge>{t(s.status)}</Badge>
                </div>
                <div className="grid gap-2 md:grid-cols-2">
                  <DiffSide label={t("before")} text={s.before} tone="removed" />
                  <DiffSide label={t("after")} text={s.after} tone="added" />
                </div>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function DiffSide({ label, text, tone }: { label: string; text: string; tone: "added" | "removed" }) {
  return (
    <div className={`rounded-[10px] p-2.5 text-[12.5px] ${tone === "added" ? "bg-success/[0.08]" : "bg-danger/[0.06]"}`}>
      <div className="mb-1 text-[11px] uppercase tracking-wider text-subtle">{label}</div>
      <p className="whitespace-pre-wrap">{text || "—"}</p>
    </div>
  );
}
