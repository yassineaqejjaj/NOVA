"use client";

import { Badge, Button, cn, Input, Popover, PopoverContent, PopoverTrigger, Select, Switch, Textarea } from "@nova/ui";
import { ChevronRight, CornerDownRight, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { ClassificationBadge } from "@/components/shell/page";
import { type JsonSchema, useItemKinds, useProvenance } from "@/lib/api/hooks";
import type { ArtifactItem, Citation } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";
import { useLang, useT } from "@/lib/i18n";

import { fieldLabel, kindLabel, M, valueLabel } from "./items-editor.messages";

/** [S2] chip: opens the recorded source (what ORBIT served when NOVA wrote this). */
export function CitationChip({ citation, artifactId, itemId, section }: { citation: Citation; artifactId: string; itemId?: string; section?: string }) {
  const t = useT(M);
  const [open, setOpen] = useState(false);
  const { data, isLoading } = useProvenance(artifactId, itemId ? { item: itemId } : { section }, open);
  const source = data?.sources.find((s) => s.label === citation.label && (!citation.ref || s.reference_id === citation.ref));
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button className="rounded bg-accent-soft px-1 font-mono text-[10.5px] text-accent hover:bg-accent/20" title={citation.title ?? undefined}>
          {citation.label}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-96">
        {isLoading ? <p className="text-[13px] text-subtle">{t("loadingSource")}</p> : null}
        {source ? (
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className="text-[13px] font-medium">{source.title}</span>
              <ClassificationBadge level={source.classification} />
            </div>
            <div className="text-[11.5px] text-subtle">{[source.type, source.project, source.updated ? t("updated", { when: timeAgo(source.updated) }) : null].filter(Boolean).join(" · ")}</div>
            {source.excerpt ? <p className="rounded-md bg-surface-2 p-2 text-[12.5px] text-muted">“{source.excerpt}”</p> : null}
            {source.uri ? (
              <a href={source.uri} target="_blank" rel="noreferrer" className="text-[12.5px] text-accent hover:underline">{t("openInOrbit")}</a>
            ) : null}
          </div>
        ) : !isLoading ? (
          <p className="text-[13px] text-subtle">{t("sourceUnavailable", { title: citation.title ?? citation.label })}</p>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}

function AttributeField({ name, schema, value, onChange, editable }: { name: string; schema: JsonSchema; value: unknown; onChange: (v: unknown) => void; editable: boolean }) {
  const lang = useLang();
  const label = fieldLabel(name, lang);
  const type = Array.isArray(schema.type) ? schema.type.find((t) => t !== "null") : schema.type;
  if (schema.enum) {
    return (
      <label className="flex items-center gap-2 text-[12.5px]">
        <span className="w-28 shrink-0 capitalize text-subtle">{label}</span>
        {editable ? (
          <Select value={(value as string) ?? undefined} onValueChange={onChange} placeholder="—" options={schema.enum.map((v) => ({ value: v, label: valueLabel(name, v, lang) }))} className="h-7 w-44 text-[12.5px]" />
        ) : (
          <span className="text-muted">{lang === "fr" && typeof value === "string" ? valueLabel(name, value, lang) : String(value ?? "—")}</span>
        )}
      </label>
    );
  }
  if (type === "boolean") {
    return (
      <label className="flex items-center gap-2 text-[12.5px]">
        <span className="w-28 shrink-0 capitalize text-subtle">{label}</span>
        <Switch checked={!!value} onCheckedChange={onChange} disabled={!editable} />
      </label>
    );
  }
  if (type === "array" && schema.items?.type === "string") {
    const list = (value as string[] | undefined) ?? [];
    return (
      <label className="flex items-start gap-2 text-[12.5px]">
        <span className="w-28 shrink-0 pt-1.5 capitalize text-subtle">{label}</span>
        <Input disabled={!editable} value={list.join(", ")} onChange={(e) => onChange(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} className="h-7 text-[12.5px]" />
      </label>
    );
  }
  if (type === "object" || type === "array") {
    return (
      <div className="flex items-start gap-2 text-[12.5px]">
        <span className="w-28 shrink-0 capitalize text-subtle">{label}</span>
        <code className="text-muted">{JSON.stringify(value ?? {})}</code>
      </div>
    );
  }
  return (
    <label className="flex items-center gap-2 text-[12.5px]">
      <span className="w-28 shrink-0 capitalize text-subtle">{label}</span>
      <Input
        disabled={!editable}
        type={type === "number" || type === "integer" ? "number" : "text"}
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange(type === "number" || type === "integer" ? (e.target.value === "" ? undefined : Number(e.target.value)) : e.target.value)}
        className="h-7 text-[12.5px]"
      />
    </label>
  );
}

/** Badge tone of an `a11y_finding` severity. */
const SEVERITY_TONE: Record<string, "neutral" | "warning" | "danger"> = { low: "neutral", medium: "warning", high: "danger", critical: "danger" };

type Criterion = { given: string; when: string; then: string };

function StoryFields({ item, editable, update }: { item: ArtifactItem; editable: boolean; update: (attrs: Record<string, unknown>) => void }) {
  const t = useT(M);
  const a = item.attributes as { as_a?: string; i_want?: string; so_that?: string; acceptance_criteria?: Criterion[] };
  const criteria = a.acceptance_criteria ?? [];
  const setCriteria = (next: Criterion[]) => update({ acceptance_criteria: next });
  return (
    <div className="space-y-2">
      <div className="grid gap-1.5 text-[13px]">
        {(["as_a", "i_want", "so_that"] as const).map((key) => (
          <label key={key} className="flex items-center gap-2">
            <span className="w-20 shrink-0 text-[12px] text-subtle">{{ as_a: t("asA"), i_want: t("iWant"), so_that: t("soThat") }[key]}</span>
            <Input disabled={!editable} value={a[key] ?? ""} onChange={(e) => update({ [key]: e.target.value })} className="h-7 text-[13px]" />
          </label>
        ))}
      </div>
      <div>
        <div className="mb-1 flex items-center gap-2 text-[12px] text-subtle">
          {t("acceptanceCriteria")}
          {criteria.length === 0 ? <Badge tone="warning">{t("missing")}</Badge> : null}
        </div>
        <ul className="space-y-1">
          {criteria.map((c, i) => (
            <li key={i} className="grid grid-cols-[auto_1fr_auto_1fr_auto_1fr_auto] items-center gap-1.5 text-[12.5px]">
              {(["given", "when", "then"] as const).map((k) => (
                <span key={k} className="contents">
                  <span className="text-subtle capitalize">{t(k)}</span>
                  <Input disabled={!editable} value={c[k]} onChange={(e) => setCriteria(criteria.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} className="h-7 text-[12.5px]" />
                </span>
              ))}
              {editable ? (
                <Button variant="ghost" size="icon" className="size-7" onClick={() => setCriteria(criteria.filter((_, j) => j !== i))} aria-label={t("removeCriterion")}><Trash2 className="!size-3.5" /></Button>
              ) : <span />}
            </li>
          ))}
        </ul>
        {editable ? (
          <Button variant="ghost" size="sm" className="mt-1 h-7 text-[12px]" onClick={() => setCriteria([...criteria, { given: "", when: "", then: "" }])}>
            <Plus /> {t("criterion")}
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function ItemCard({ item, kindSchema, editable, depth, parentTitle, artifactId, onChange, onDelete }: {
  item: ArtifactItem;
  kindSchema?: JsonSchema;
  editable: boolean;
  depth: number;
  parentTitle?: string;
  artifactId: string;
  onChange: (item: ArtifactItem) => void;
  onDelete: () => void;
}) {
  const t = useT(M);
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const update = (attrs: Record<string, unknown>) => onChange({ ...item, attributes: { ...item.attributes, ...attrs } });
  const props = kindSchema?.properties ?? {};
  const summary = Object.entries(item.attributes)
    .filter(([k, v]) => typeof v === "string" && !["as_a", "i_want", "so_that"].includes(k) && props[k]?.enum)
    .map(([k, v]) => ({ key: k, label: `${k === "likelihood" || k === "impact" ? `${fieldLabel(k, lang)} ` : ""}${valueLabel(k, String(v), lang)}` }));
  const missingAc = item.kind === "story" && !(item.attributes.acceptance_criteria as unknown[] | undefined)?.length;

  return (
    <div className={cn("group rounded-[10px] border border-transparent px-2 py-1.5 hover:border-border hover:bg-surface-2/50", open && "border-border bg-surface-2/50")} style={{ marginLeft: depth * 18 }}>
      <div className="flex items-start gap-2">
        <button onClick={() => setOpen(!open)} className="mt-1 text-subtle hover:text-text" aria-label={open ? t("collapseItem") : t("expandItem")}>
          <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            {editable ? (
              <input value={item.title} onChange={(e) => onChange({ ...item, title: e.target.value })} className="min-w-0 flex-1 bg-transparent text-[14px] font-medium text-text outline-none" aria-label={t("itemTitle")} />
            ) : (
              <span className="text-[14px] font-medium">{item.title}</span>
            )}
            {summary.map((s) => <Badge key={s.key} tone={s.key === "severity" ? SEVERITY_TONE[String(item.attributes.severity)] : undefined}>{s.label}</Badge>)}
            {missingAc ? <Badge tone="warning">{t("noAcceptanceCriteria")}</Badge> : null}
            {item.citations.map((c) => <CitationChip key={`${c.label}-${c.ref}`} citation={c} artifactId={artifactId} itemId={item.id} />)}
          </div>
          {parentTitle ? (
            <div className="mt-0.5 flex items-center gap-1 text-[11.5px] text-subtle"><CornerDownRight className="size-3" />{parentTitle}</div>
          ) : null}
          {item.description || editable ? (
            editable ? (
              <Textarea rows={1} value={item.description} onChange={(e) => onChange({ ...item, description: e.target.value })} placeholder={t("description")} className="mt-1 min-h-0 resize-none border-transparent bg-transparent px-0 py-0.5 text-[13px] text-muted focus:ring-0" />
            ) : (
              <p className="mt-0.5 text-[13px] text-muted">{item.description}</p>
            )
          ) : null}
        </div>
        {editable ? (
          <Button variant="ghost" size="icon" className="size-7 opacity-0 group-hover:opacity-100" onClick={onDelete} aria-label={t("deleteItem")}><Trash2 className="!size-3.5" /></Button>
        ) : null}
      </div>
      {open ? (
        <div className="mt-2 space-y-2 border-t border-border pl-5 pt-2">
          {item.kind === "story" ? <StoryFields item={item} editable={editable} update={update} /> : null}
          {Object.entries(props)
            .filter(([k]) => item.kind !== "story" || !["as_a", "i_want", "so_that", "acceptance_criteria"].includes(k))
            .map(([key, schema]) => (
              <AttributeField key={key} name={key} schema={schema} value={item.attributes[key]} editable={editable} onChange={(v) => update({ [key]: v })} />
            ))}
          {item.rationale ? <p className="text-[12px] text-subtle">{t("why", { rationale: item.rationale })}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

export function ItemsEditor({ items, itemKind, editable, allItems, artifactId, onChange }: {
  items: ArtifactItem[];
  itemKind: string;
  editable: boolean;
  allItems: ArtifactItem[];
  artifactId: string;
  onChange: (items: ArtifactItem[]) => void;
}) {
  const t = useT(M);
  const lang = useLang();
  const { data: kinds } = useItemKinds();
  const ids = new Set(items.map((i) => i.id));
  const titles = new Map(allItems.map((i) => [i.id, i.title]));
  // Hierarchy inside the section (parent_id within the same section) — cross-section parents are shown as a reference.
  const children = new Map<string | null, ArtifactItem[]>();
  for (const item of items) {
    const parent = item.parent_id && ids.has(item.parent_id) ? item.parent_id : null;
    children.set(parent, [...(children.get(parent) ?? []), item]);
  }
  const ordered: { item: ArtifactItem; depth: number }[] = [];
  const walk = (parent: string | null, depth: number) => {
    for (const item of children.get(parent) ?? []) {
      ordered.push({ item, depth });
      walk(item.id, depth + 1);
    }
  };
  walk(null, 0);

  const replace = (next: ArtifactItem) => onChange(items.map((i) => (i.id === next.id ? next : i)));
  const add = () =>
    onChange([...items, { id: `${itemKind}-${Math.random().toString(36).slice(2, 7)}`, kind: itemKind, title: "", description: "", parent_id: null, rationale: "", citations: [], attributes: {} }]);

  return (
    <div className="space-y-0.5">
      {ordered.map(({ item, depth }) => (
        <ItemCard
          key={item.id}
          item={item}
          depth={depth}
          kindSchema={kinds?.[item.kind]}
          editable={editable}
          artifactId={artifactId}
          parentTitle={item.parent_id && !ids.has(item.parent_id) ? titles.get(item.parent_id) : undefined}
          onChange={replace}
          onDelete={() => onChange(items.filter((i) => i.id !== item.id))}
        />
      ))}
      {items.length === 0 && !editable ? <p className="px-2 text-[13px] text-subtle">{t("nothingYet")}</p> : null}
      {editable ? (
        <Button variant="ghost" size="sm" className="ml-1 h-7 text-[12.5px] text-subtle" onClick={add}>
          <Plus /> {t("add", { kind: kindLabel(itemKind, lang) })}
        </Button>
      ) : null}
    </div>
  );
}
