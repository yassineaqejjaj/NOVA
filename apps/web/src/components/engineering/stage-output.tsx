"use client";

import { Badge } from "@nova/ui";

import type { Stage } from "@/lib/api/engineering";
import { useT } from "@/lib/i18n";

import { M } from "./engineering.messages";

type Out = Record<string, unknown>;
const list = (v: unknown): string[] => (Array.isArray(v) ? v.map((x) => String(x)) : []);
const objs = (v: unknown): Out[] => (Array.isArray(v) ? (v as Out[]) : []);

function Bullets({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mt-3">
      <h4 className="text-[12px] font-semibold uppercase tracking-wide text-subtle">{title}</h4>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[13px]">{items.map((i, n) => <li key={n}>{i}</li>)}</ul>
    </div>
  );
}

function Files({ title, files }: { title: string; files: Out[] }) {
  if (files.length === 0) return null;
  return (
    <div className="mt-3">
      <h4 className="text-[12px] font-semibold uppercase tracking-wide text-subtle">{title}</h4>
      <ul className="mt-1 space-y-0.5 text-[13px]">
        {files.map((f, n) => (
          <li key={n} className="flex items-center gap-2">
            <Badge tone={f.action === "delete" ? "danger" : f.action === "create" ? "success" : "neutral"}>{String(f.action)}</Badge>
            <code className="truncate text-[12.5px]">{String(f.path)}</code>
            {f.reason ? <span className="truncate text-muted">— {String(f.reason)}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The structured result of a stage (specification, design, files, review findings, CI, release notes). */
export function StageOutput({ stage, design }: { stage: Stage; design?: Out }) {
  const t = useT(M);
  const o = (stage.output ?? {}) as Out;
  if (Object.keys(o).length === 0 && !design) return null;
  switch (stage.key) {
    case "spec":
      return (
        <div>
          {o.root_cause ? <p className="mt-2 text-[13px]"><strong>{t("rootCause")}:</strong> {String(o.root_cause)}</p> : null}
          <Bullets title={t("stories")} items={list(o.user_stories)} />
          <Bullets title={t("criteria")} items={list(o.acceptance_criteria)} />
          <Bullets title={t("outOfScope")} items={list(o.out_of_scope)} />
          <Bullets title={t("risks")} items={list(o.risks)} />
          <Bullets title={t("questions")} items={list(o.open_questions)} />
        </div>
      );
    case "design":
      return (
        <div>
          <p className="mt-2 whitespace-pre-wrap text-[13px]">{String(o.approach ?? "")}</p>
          <Files title={t("plannedChanges")} files={objs(o.changes)} />
          <Bullets title={t("testPlan")} items={list(o.test_plan)} />
          <Bullets title={t("risks")} items={list(o.risks)} />
        </div>
      );
    case "implement":
      return <Files title={t("filesChanged")} files={objs(o.changes)} />;
    case "tests":
      return <Files title={t("filesChanged")} files={objs(o.tests)} />;
    case "review":
      return (
        <div>
          {objs(o.rounds).map((round, n) => (
            <div key={n} className="mt-3">
              <h4 className="text-[12px] font-semibold uppercase tracking-wide text-subtle">{t("round", { n: n + 1 })} · {String(round.verdict)}</h4>
              <p className="mt-1 text-[13px]">{String(round.summary ?? "")}</p>
              <ul className="mt-1 space-y-1 text-[13px]">
                {objs(round.findings).length === 0 ? <li className="text-muted">{t("noFindings")}</li> : null}
                {objs(round.findings).map((f, i) => (
                  <li key={i} className="flex gap-2">
                    <Badge tone={f.severity === "blocker" ? "danger" : f.severity === "major" ? "warning" : "neutral"}>{String(f.severity)}</Badge>
                    <span>{f.path ? <code className="text-[12.5px]">{String(f.path)}{f.line ? `:${String(f.line)}` : ""}</code> : null} {String(f.message)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      );
    case "ci":
      return (
        <p className="mt-2 text-[13px]">
          {t("ciState", { state: String(o.state ?? "") })}
          {Number(o.fix_rounds) > 0 ? ` · ${t("fixRounds", { n: Number(o.fix_rounds) })}` : ""}
        </p>
      );
    case "release":
      return (
        <div className="mt-2">
          <p className="text-[13px] font-medium">{String(o.title ?? "")} {o.version ? <Badge>{String(o.version)}</Badge> : null}</p>
          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap rounded-[10px] bg-surface-2 p-3 text-[12.5px]">{String(o.notes ?? "")}</pre>
        </div>
      );
    default:
      return null;
  }
}
