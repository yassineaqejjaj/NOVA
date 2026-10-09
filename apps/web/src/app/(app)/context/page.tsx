"use client";

import { Badge, Button, Input, Select, Skeleton } from "@nova/ui";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Orbit, Search } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { ClassificationBadge, EmptyState, ErrorNotice, Page, PageHeader } from "@/components/shell/page";
import { api, ApiError, qs } from "@/lib/api/client";
import type { ChangeEvent, ContextSource, OrbitIdentity } from "@/lib/api/types";
import { classificationLabel, dateTime, timeAgo } from "@/lib/format";
import { defineMessages, useT } from "@/lib/i18n";

import { SnapshotsSection } from "./snapshots-section";

const M = defineMessages({
  en: {
    title: "ORBIT Context",
    description: "Context powered by ORBIT. NOVA reads it on your behalf, with your permissions; it never stores ORBIT's knowledge.",
    openOrbit: "Open ORBIT",
    notConnected: "ORBIT is not connected",
    notConnectedHint: "Connect your ORBIT account so NOVA can use your projects' documents, decisions and backlog.",
    connect: "Connect ORBIT",
    profile: "Your profile",
    clearance: "Clearance",
    sessionUntil: "· session until {date}",
    projects: "Projects",
    recent: "Recent context used by NOVA",
    contextFallback: "Context",
    items: (v: { n: number }) => `${v.n} item${v.n === 1 ? "" : "s"}`,
    openWork: "Open the work",
    nothingYet: "Nothing yet.",
    snapshotBadge: "Snapshot",
    search: "Search sources in ORBIT",
    project: "Project",
    searchFailed: "ORBIT search failed",
    noMatch: "No sources match.",
    projectContextFailed: "ORBIT could not provide this project's context",
    decisions: "Decisions",
    noDecisionChanges: "No recent decision changes.",
    sources: "Sources",
    noDocumentChanges: "No recent document changes.",
  },
  fr: {
    title: "Contexte ORBIT",
    description: "Contexte fourni par ORBIT. NOVA le consulte en votre nom, avec vos droits ; il ne stocke jamais la connaissance d’ORBIT.",
    openOrbit: "Ouvrir ORBIT",
    notConnected: "ORBIT n’est pas connecté",
    notConnectedHint: "Connectez votre compte ORBIT pour que NOVA puisse utiliser les documents, décisions et backlog de vos projets.",
    connect: "Connecter ORBIT",
    profile: "Votre profil",
    clearance: "Habilitation",
    sessionUntil: "· session valable jusqu’au {date}",
    projects: "Projets",
    recent: "Contexte récemment utilisé par NOVA",
    contextFallback: "Contexte",
    items: (v: { n: number }) => `${v.n} élément${v.n > 1 ? "s" : ""}`,
    openWork: "Ouvrir le travail",
    nothingYet: "Rien pour l’instant.",
    snapshotBadge: "Snapshot",
    search: "Rechercher des sources dans ORBIT",
    project: "Projet",
    searchFailed: "La recherche ORBIT a échoué",
    noMatch: "Aucune source ne correspond.",
    projectContextFailed: "ORBIT n’a pas pu fournir le contexte de ce projet",
    decisions: "Décisions",
    noDecisionChanges: "Aucune modification récente de décision.",
    sources: "Sources",
    noDocumentChanges: "Aucune modification récente de document.",
  },
});

interface Overview {
  orbit_url: string;
  identity: OrbitIdentity;
  projects: { id: string; name: string; orbit_slug: string; orbit_url: string | null }[];
  recent: { id: string; task_id: string | null; project_slug: string | null; query: string; count: number; max_classification: number; snapshot?: { name: string; version: number | null } | null; created_at: string; items: ContextSource[] }[];
}

function ContextPage() {
  const params = useSearchParams();
  const t = useT(M);
  const { data, isLoading } = useQuery({ queryKey: ["context"], queryFn: () => api.get<Overview>("/context") });
  const [project, setProject] = useState<string | null>(null);
  const [q, setQ] = useState(params.get("q") ?? "");
  const [submitted, setSubmitted] = useState(params.get("q") ?? "");
  const projectId = project ?? data?.projects[0]?.id ?? null;
  const projectContext = useQuery({
    queryKey: ["context-project", projectId],
    queryFn: () => api.get<{ decisions: ChangeEvent[]; documents: ChangeEvent[] }>(`/context/projects/${projectId}`),
    enabled: !!projectId && !!data?.identity.linked,
  });
  const search = useQuery({
    queryKey: ["context-search", projectId, submitted],
    queryFn: () => api.get<{ ref_id: string; title: string; snippet: string; source_kind?: string; updated_at?: string }[]>(`/context/search${qs({ project_id: projectId, q: submitted })}`),
    enabled: !!projectId && submitted.length >= 2,
  });

  if (isLoading || !data) return <Page><Skeleton className="h-40" /></Page>;
  const identity = data.identity;

  return (
    <Page wide>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={<Button variant="ghost" size="sm" asChild><a href={data.orbit_url} target="_blank" rel="noreferrer">{t("openOrbit")} <ExternalLink /></a></Button>}
      />
      {!identity.linked ? (
        <EmptyState icon={<Orbit />} title={t("notConnected")} description={t("notConnectedHint")} action={<Button asChild><Link href="/settings#orbit">{t("connect")}</Link></Button>} />
      ) : (
        <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
          <div className="space-y-8">
            <section>
              <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">{t("profile")}</h2>
              <div className="rounded-[12px] border border-border bg-surface p-4 text-[13.5px]">
                <div className="font-medium">{identity.display_name || identity.email}</div>
                <div className="text-[12.5px] text-subtle">{identity.email}</div>
                <div className="mt-2 flex items-center gap-2 text-[12.5px] text-muted">
                  {t("clearance")} <Badge>{identity.clearance != null ? classificationLabel(identity.clearance) : "—"}</Badge>
                  {identity.expires_at ? <span className="text-subtle">{t("sessionUntil", { date: dateTime(identity.expires_at) })}</span> : null}
                </div>
              </div>
            </section>
            <section>
              <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">{t("projects")}</h2>
              {data.projects.map((p) => (
                <button key={p.id} onClick={() => setProject(p.id)} className={`flex w-full items-center gap-2 rounded-[10px] px-3 py-2 text-left text-[13.5px] ${projectId === p.id ? "bg-surface-2 text-text" : "text-muted hover:bg-surface"}`}>
                  <Orbit className="size-3.5" /> {p.name} <span className="ml-auto font-mono text-[11px] text-subtle">{p.orbit_slug}</span>
                </button>
              ))}
            </section>
            <section>
              <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">{t("recent")}</h2>
              {data.recent.length ? data.recent.map((r) => (
                <details key={r.id} className="border-b border-border py-2 text-[13px]">
                  <summary className="flex cursor-pointer items-center gap-2 text-muted">
                    <span className="truncate">{r.query || t("contextFallback")}</span><ClassificationBadge level={r.max_classification} />
                    {r.snapshot ? <Badge tone="accent" title={r.snapshot.name}>{t("snapshotBadge")}{r.snapshot.version ? ` v${r.snapshot.version}` : ""}</Badge> : null}
                    <span className="ml-auto shrink-0 text-[11.5px] text-subtle">{t("items", { n: r.count })} · {timeAgo(r.created_at)}</span>
                  </summary>
                  <ul className="mt-1.5 space-y-1 pl-2">
                    {r.items.map((i) => (
                      <li key={`${r.id}-${i.citation}`} className="flex items-center gap-2 text-[12.5px]">
                        <span className="font-mono text-[10.5px] text-subtle">{i.citation}</span>
                        {i.uri ? <a href={i.uri} target="_blank" rel="noreferrer" className="truncate hover:underline">{i.title}</a> : <span className="truncate">{i.title}</span>}
                        <ClassificationBadge level={i.classification} />
                      </li>
                    ))}
                  </ul>
                  {r.task_id ? <Link href={`/work?task=${r.task_id}`} className="mt-1 inline-block pl-2 text-[12px] text-accent hover:underline">{t("openWork")}</Link> : null}
                </details>
              )) : <p className="text-[13px] text-subtle">{t("nothingYet")}</p>}
            </section>
          </div>
          <div className="space-y-8">
            <section>
              <form onSubmit={(e) => { e.preventDefault(); setSubmitted(q); }} className="flex gap-2">
                <div className="relative flex-1"><Search className="absolute left-3 top-2.5 size-4 text-subtle" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("search")} className="pl-9" /></div>
                <Select ariaLabel={t("project")} value={projectId ?? undefined} onValueChange={setProject} options={data.projects.map((p) => ({ value: p.id, label: p.name }))} className="w-40" />
              </form>
              {search.error instanceof ApiError ? <div className="mt-3"><ErrorNotice title={t("searchFailed")} message={search.error.message} /></div> : null}
              {search.data ? (
                <ul className="mt-3 space-y-2">
                  {search.data.map((hit) => (
                    <li key={hit.ref_id} className="rounded-[10px] border border-border bg-surface px-3 py-2">
                      <div className="flex items-center gap-2 text-[13.5px]"><span className="font-medium">{hit.title}</span><span className="ml-auto text-[11.5px] text-subtle">{hit.source_kind}</span></div>
                      <p className="mt-0.5 line-clamp-2 text-[12.5px] text-muted">{hit.snippet}</p>
                    </li>
                  ))}
                  {search.data.length === 0 ? <p className="text-[13px] text-subtle">{t("noMatch")}</p> : null}
                </ul>
              ) : null}
            </section>
            {projectContext.error instanceof ApiError ? <ErrorNotice title={t("projectContextFailed")} message={projectContext.error.message} /> : null}
            {projectId ? <SnapshotsSection projectId={projectId} /> : null}
            <section>
              <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">{t("decisions")}</h2>
              {projectContext.data?.decisions.length ? projectContext.data.decisions.map((d) => (
                <div key={d.id} className="border-b border-border py-2"><div className="flex items-center gap-2 text-[13.5px]">{d.title}<ClassificationBadge level={d.classification} /></div><div className="text-[12px] text-subtle">{d.type_label} · {timeAgo(d.created_at)}</div></div>
              )) : <p className="text-[13px] text-subtle">{t("noDecisionChanges")}</p>}
            </section>
            <section>
              <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">{t("sources")}</h2>
              {projectContext.data?.documents.length ? projectContext.data.documents.map((d) => (
                <div key={d.id} className="border-b border-border py-2"><div className="text-[13.5px]">{d.title}</div><div className="text-[12px] text-subtle">{d.type_label} · {timeAgo(d.created_at)}</div></div>
              )) : <p className="text-[13px] text-subtle">{t("noDocumentChanges")}</p>}
            </section>
          </div>
        </div>
      )}
    </Page>
  );
}

export default function ContextRoute() {
  return <Suspense><ContextPage /></Suspense>;
}
