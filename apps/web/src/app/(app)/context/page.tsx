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
import { CLASSIFICATION, timeAgo } from "@/lib/format";

interface Overview {
  orbit_url: string;
  identity: OrbitIdentity;
  projects: { id: string; name: string; orbit_slug: string; orbit_url: string | null }[];
  recent: { id: string; task_id: string | null; project_slug: string | null; query: string; count: number; max_classification: number; created_at: string; items: ContextSource[] }[];
}

function ContextPage() {
  const params = useSearchParams();
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
        title="ORBIT Context"
        description="Context powered by ORBIT. NOVA reads it on your behalf, with your permissions; it never stores ORBIT's knowledge."
        actions={<Button variant="ghost" size="sm" asChild><a href={data.orbit_url} target="_blank" rel="noreferrer">Open ORBIT <ExternalLink /></a></Button>}
      />
      {!identity.linked ? (
        <EmptyState icon={<Orbit />} title="ORBIT is not connected" description="Connect your ORBIT account so NOVA can use your projects' documents, decisions and backlog." action={<Button asChild><Link href="/settings#orbit">Connect ORBIT</Link></Button>} />
      ) : (
        <div className="grid gap-8 lg:grid-cols-[1fr_1.4fr]">
          <div className="space-y-8">
            <section>
              <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">Your profile</h2>
              <div className="rounded-[12px] border border-border bg-surface p-4 text-[13.5px]">
                <div className="font-medium">{identity.display_name || identity.email}</div>
                <div className="text-[12.5px] text-subtle">{identity.email}</div>
                <div className="mt-2 flex items-center gap-2 text-[12.5px] text-muted">
                  Clearance <Badge>{identity.clearance != null ? CLASSIFICATION[identity.clearance] : "—"}</Badge>
                  {identity.expires_at ? <span className="text-subtle">· session until {new Date(identity.expires_at).toLocaleString()}</span> : null}
                </div>
              </div>
            </section>
            <section>
              <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">Projects</h2>
              {data.projects.map((p) => (
                <button key={p.id} onClick={() => setProject(p.id)} className={`flex w-full items-center gap-2 rounded-[10px] px-3 py-2 text-left text-[13.5px] ${projectId === p.id ? "bg-surface-2 text-text" : "text-muted hover:bg-surface"}`}>
                  <Orbit className="size-3.5" /> {p.name} <span className="ml-auto font-mono text-[11px] text-subtle">{p.orbit_slug}</span>
                </button>
              ))}
            </section>
            <section>
              <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">Recent context used by NOVA</h2>
              {data.recent.length ? data.recent.map((r) => (
                <details key={r.id} className="border-b border-border py-2 text-[13px]">
                  <summary className="flex cursor-pointer items-center gap-2 text-muted">
                    <span className="truncate">{r.query || "Context"}</span><ClassificationBadge level={r.max_classification} />
                    <span className="ml-auto shrink-0 text-[11.5px] text-subtle">{r.count} items · {timeAgo(r.created_at)}</span>
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
                  {r.task_id ? <Link href={`/work?task=${r.task_id}`} className="mt-1 inline-block pl-2 text-[12px] text-accent hover:underline">Open the work</Link> : null}
                </details>
              )) : <p className="text-[13px] text-subtle">Nothing yet.</p>}
            </section>
          </div>
          <div className="space-y-8">
            <section>
              <form onSubmit={(e) => { e.preventDefault(); setSubmitted(q); }} className="flex gap-2">
                <div className="relative flex-1"><Search className="absolute left-3 top-2.5 size-4 text-subtle" /><Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search sources in ORBIT" className="pl-9" /></div>
                <Select ariaLabel="Project" value={projectId ?? undefined} onValueChange={setProject} options={data.projects.map((p) => ({ value: p.id, label: p.name }))} className="w-40" />
              </form>
              {search.error instanceof ApiError ? <div className="mt-3"><ErrorNotice title="ORBIT search failed" message={search.error.message} /></div> : null}
              {search.data ? (
                <ul className="mt-3 space-y-2">
                  {search.data.map((hit) => (
                    <li key={hit.ref_id} className="rounded-[10px] border border-border bg-surface px-3 py-2">
                      <div className="flex items-center gap-2 text-[13.5px]"><span className="font-medium">{hit.title}</span><span className="ml-auto text-[11.5px] text-subtle">{hit.source_kind}</span></div>
                      <p className="mt-0.5 line-clamp-2 text-[12.5px] text-muted">{hit.snippet}</p>
                    </li>
                  ))}
                  {search.data.length === 0 ? <p className="text-[13px] text-subtle">No sources match.</p> : null}
                </ul>
              ) : null}
            </section>
            {projectContext.error instanceof ApiError ? <ErrorNotice title="ORBIT could not provide this project's context" message={projectContext.error.message} /> : null}
            <section>
              <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">Decisions</h2>
              {projectContext.data?.decisions.length ? projectContext.data.decisions.map((d) => (
                <div key={d.id} className="border-b border-border py-2"><div className="flex items-center gap-2 text-[13.5px]">{d.title}<ClassificationBadge level={d.classification} /></div><div className="text-[12px] text-subtle">{d.type_label} · {timeAgo(d.created_at)}</div></div>
              )) : <p className="text-[13px] text-subtle">No recent decision changes.</p>}
            </section>
            <section>
              <h2 className="mb-2 text-[12px] font-medium uppercase tracking-wider text-subtle">Sources</h2>
              {projectContext.data?.documents.length ? projectContext.data.documents.map((d) => (
                <div key={d.id} className="border-b border-border py-2"><div className="text-[13.5px]">{d.title}</div><div className="text-[12px] text-subtle">{d.type_label} · {timeAgo(d.created_at)}</div></div>
              )) : <p className="text-[13px] text-subtle">No recent document changes.</p>}
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
