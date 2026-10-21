"use client";

import { Skeleton } from "@nova/ui";
import { ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";

import { AGENTS } from "@/lib/agents";
import { type AgentProgress, type CurvePoint, useTrainingProgress } from "@/lib/api/training";
import { defineMessages, useLang, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    title: "Is the system getting better?",
    hint: "Measured by Nova Evals on each agent's Skills. A version only counts once it reached users. Nova Evals evaluates, NOVA turns the evidence into lessons in its instructions (no model is retrained), Nova Context keeps the governed knowledge.",
    gain: "Average score gain",
    gainHint: (v: { n: number }) => `across ${v.n} measured agent${v.n > 1 ? "s" : ""}`,
    versions: "Versions shipped",
    lessons: "Lessons applied",
    stopped: "Changes stopped before users",
    stoppedHint: "rejected by Nova Evals or rolled back",
    notMeasured: "Not measured yet — train this agent to start its curve.",
    from: (v: { a: string; b: string }) => `${v.a} → ${v.b}`,
    version: (v: { v: number }) => `v${v.v}`,
    traffic: (v: { d: number }) => `Failed executions, last ${v.d} days`,
    trafficDown: (v: { p: string }) => `${v.p}% fewer failures than the previous period`,
    trafficUp: (v: { p: string }) => `${v.p}% more failures than the previous period`,
    trafficFlat: "Unchanged against the previous period",
    trafficThin: "Not enough executions yet to compare two periods.",
    rollbacks: (v: { n: number }) => `${v.n} rollback${v.n > 1 ? "s" : ""}`,
    curveLabel: (v: { name: string }) => `${v.name} score by version`,
  },
  fr: {
    title: "Le système s'améliore-t-il ?",
    hint: "Mesuré par Nova Evals sur les compétences de chaque agent. Une version ne compte qu'une fois arrivée chez les utilisateurs. Nova Evals évalue, NOVA transforme les preuves en leçons dans ses consignes (aucun modèle n'est ré-entraîné), Nova Context conserve les connaissances gouvernées.",
    gain: "Gain de score moyen",
    gainHint: (v: { n: number }) => `sur ${v.n} agent${v.n > 1 ? "s" : ""} mesuré${v.n > 1 ? "s" : ""}`,
    versions: "Versions déployées",
    lessons: "Leçons appliquées",
    stopped: "Changements arrêtés avant les utilisateurs",
    stoppedHint: "rejetés par Nova Evals ou retirés",
    notMeasured: "Pas encore mesuré — entraînez cet agent pour démarrer sa courbe.",
    from: (v: { a: string; b: string }) => `${v.a} → ${v.b}`,
    version: (v: { v: number }) => `v${v.v}`,
    traffic: (v: { d: number }) => `Exécutions en échec, ${v.d} derniers jours`,
    trafficDown: (v: { p: string }) => `${v.p} % d'échecs en moins que la période précédente`,
    trafficUp: (v: { p: string }) => `${v.p} % d'échecs en plus que la période précédente`,
    trafficFlat: "Inchangé par rapport à la période précédente",
    trafficThin: "Pas encore assez d'exécutions pour comparer deux périodes.",
    rollbacks: (v: { n: number }) => `${v.n} retrait${v.n > 1 ? "s" : ""}`,
    curveLabel: (v: { name: string }) => `Score de ${v.name} par version`,
  },
});

const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}`;

/** One agent's score by version; the scale is fixed to the agent's own range so a small gain stays visible. */
function Curve({ points, color, label }: { points: CurvePoint[]; color: string; label: string }) {
  const W = 220;
  const H = 56;
  const pad = 6;
  const scores = points.map((p) => p.score);
  const lo = Math.min(...scores);
  const hi = Math.max(...scores);
  const x = (i: number) => pad + (points.length === 1 ? (W - 2 * pad) / 2 : (i * (W - 2 * pad)) / (points.length - 1));
  const y = (s: number) => (hi === lo ? H / 2 : H - pad - ((s - lo) / (hi - lo)) * (H - 2 * pad));
  const path = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)} ${y(p.score).toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} className="h-14 w-full" style={{ color }}>
      {points.length > 1 ? <path d={path} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" /> : null}
      {points.map((p, i) => (
        <circle key={p.version} cx={x(i)} cy={y(p.score)} r={i === points.length - 1 ? 4 : 3} fill="currentColor" />
      ))}
    </svg>
  );
}

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-[14px] border border-border bg-surface p-3.5">
      <div className="text-[11.5px] text-subtle">{label}</div>
      <div className="mt-0.5 text-[22px] font-semibold tabular-nums">{value}</div>
      {hint ? <div className="text-[11.5px] text-muted">{hint}</div> : null}
    </div>
  );
}

function AgentCurve({ item }: { item: AgentProgress }) {
  const t = useT(M);
  const lang = useLang();
  const agent = AGENTS[item.agent];
  const first = item.curve[0];
  const last = item.curve[item.curve.length - 1];
  const label = (p: CurvePoint) => `${t("version", { v: p.version })} · ${p.score.toFixed(1)}`;
  return (
    <div className="rounded-[14px] border border-border bg-surface p-3.5" data-agent={item.agent}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[13px] font-semibold" style={{ color: agent.color }}>
          {agent.name[lang]}
        </span>
        {item.gain !== null ? (
          <span className={`whitespace-nowrap text-[13px] font-semibold tabular-nums ${item.gain >= 0 ? "text-success" : "text-danger"}`}>{signed(item.gain)} pts</span>
        ) : null}
      </div>
      {first && last ? (
        <>
          <Curve points={item.curve} color={agent.color} label={t("curveLabel", { name: agent.name[lang] })} />
          <div className="flex items-center justify-between text-[11.5px] text-muted">
            <span>{item.curve.length > 1 ? t("from", { a: label(first), b: label(last) }) : label(first)}</span>
            {item.rollbacks > 0 ? <span>{t("rollbacks", { n: item.rollbacks })}</span> : null}
          </div>
        </>
      ) : (
        <p className="mt-2 text-[12px] text-subtle">{t("notMeasured")}</p>
      )}
    </div>
  );
}

export function ImprovementSection() {
  const t = useT(M);
  const { data } = useTrainingProgress();
  if (!data) return <Skeleton className="mb-6 h-48" />;
  const { headline, traffic } = data;
  const change = traffic.relative_change;
  const pctChange = change === null ? null : Math.abs(change * 100).toFixed(0);
  return (
    <section className="mb-6" aria-labelledby="improvement-title">
      <h2 id="improvement-title" className="text-[15px] font-semibold">
        {t("title")}
      </h2>
      <p className="mb-3 text-[12.5px] text-subtle">{t("hint")}</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          label={t("gain")}
          value={headline.mean_gain === null ? "—" : `${signed(headline.mean_gain)} pts`}
          hint={headline.agents_measured ? t("gainHint", { n: headline.agents_measured }) : undefined}
        />
        <Tile label={t("versions")} value={String(headline.versions_shipped)} />
        <Tile label={t("lessons")} value={String(headline.lessons_learned)} />
        <Tile label={t("stopped")} value={String(headline.changes_stopped)} hint={t("stoppedHint")} />
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {data.agents.map((a) => (
          <AgentCurve key={a.agent} item={a} />
        ))}
      </div>
      <div className="mt-3 flex items-center gap-2 text-[12.5px] text-muted" role="status">
        {!traffic.comparable ? (
          <>
            <ShieldCheck className="size-4 text-subtle" aria-hidden /> {t("trafficThin")}
          </>
        ) : change === null || change === 0 ? (
          <>
            <ShieldCheck className="size-4 text-subtle" aria-hidden /> {t("traffic", { d: data.window_days })} · {t("trafficFlat")}
          </>
        ) : change < 0 ? (
          <>
            <TrendingDown className="size-4 text-success" aria-hidden /> {t("traffic", { d: data.window_days })} · {t("trafficDown", { p: pctChange ?? "0" })}
          </>
        ) : (
          <>
            <TrendingUp className="size-4 text-danger" aria-hidden /> {t("traffic", { d: data.window_days })} · {t("trafficUp", { p: pctChange ?? "0" })}
          </>
        )}
      </div>
    </section>
  );
}
