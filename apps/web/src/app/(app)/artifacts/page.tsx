"use client";

import { Badge, Button, Dialog, DialogContent, Input, Label, Select, Skeleton } from "@nova/ui";
import { useMutation } from "@tanstack/react-query";
import { FileStack, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { LibraryTabs } from "@/components/shell/library-tabs";
import { ClassificationBadge, EmptyState, Page, PageHeader } from "@/components/shell/page";
import { api } from "@/lib/api/client";
import { useArtifacts, useArtifactTypes, useProjects } from "@/lib/api/hooks";
import type { ArtifactSummary } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";

function ArtifactsPage() {
  const params = useSearchParams();
  const router = useRouter();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [type, setType] = useState("all");
  const [project, setProject] = useState("all");
  const { data: types } = useArtifactTypes();
  const { data: projects } = useProjects();
  const { data: artifacts, isLoading } = useArtifacts({ q: q || undefined, type: type === "all" ? undefined : type, project_id: project === "all" ? undefined : project });
  const [open, setOpen] = useState(false);
  const [newType, setNewType] = useState("prd");
  const [title, setTitle] = useState("");
  const create = useMutation({
    mutationFn: () => api.post<ArtifactSummary>("/artifacts", { type: newType, title, project_id: project === "all" ? null : project }),
    onSuccess: (a) => router.push(`/artifacts/${a.id}`),
  });
  const names = new Map(projects?.map((p) => [p.id, p.name]));

  return (
    <Page wide>
      <PageHeader title="Library" description="Everything NOVA produced with you, and the Skills it uses." actions={<Button size="sm" onClick={() => setOpen(true)}><Plus /> New</Button>} />
      <LibraryTabs />
      <div className="mb-4 flex flex-wrap gap-2">
        <div className="relative min-w-[240px] flex-1">
          <Search className="absolute left-3 top-2.5 size-4 text-subtle" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search Artifacts" className="pl-9" />
        </div>
        <Select ariaLabel="Type" value={type} onValueChange={setType} options={[{ value: "all", label: "All types" }, ...(types ?? []).map((t) => ({ value: t.type, label: t.name }))]} className="w-48" />
        <Select ariaLabel="Project" value={project} onValueChange={setProject} options={[{ value: "all", label: "All projects" }, ...(projects ?? []).map((p) => ({ value: p.id, label: p.name }))]} className="w-44" />
      </div>
      {isLoading ? <Skeleton className="h-40" /> : null}
      {artifacts?.length ? (
        <div className="overflow-hidden rounded-[14px] border border-border">
          {artifacts.map((a) => (
            <Link key={a.id} href={`/artifacts/${a.id}`} className="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0 hover:bg-surface">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2"><span className="truncate text-[14px]">{a.title}</span><ClassificationBadge level={a.classification} /></div>
                <div className="text-[12px] text-subtle">{[a.type_name, a.project_id ? names.get(a.project_id) : "Personal", `v${a.version}`].filter(Boolean).join(" · ")}</div>
              </div>
              <Badge tone={a.status === "final" ? "success" : a.status === "in_review" ? "accent" : "neutral"}>{a.status.replace("_", " ")}</Badge>
              <span className="w-24 text-right text-[12px] text-subtle">{timeAgo(a.updated_at)}</span>
            </Link>
          ))}
        </div>
      ) : !isLoading ? (
        <EmptyState icon={<FileStack />} title="Your work with NOVA will appear here." description="Ask NOVA for a PRD, a backlog or a sprint plan — or create an Artifact yourself." />
      ) : null}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="New Artifact">
          <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} className="space-y-3">
            <div className="space-y-1.5"><Label>Type</Label><Select value={newType} onValueChange={setNewType} options={(types ?? []).map((t) => ({ value: t.type, label: t.name, hint: t.description }))} className="w-full" /></div>
            <div className="space-y-1.5"><Label htmlFor="atitle">Title</Label><Input id="atitle" required value={title} onChange={(e) => setTitle(e.target.value)} /></div>
            <div className="flex justify-end"><Button type="submit" variant="primary" disabled={!title.trim() || create.isPending}>Create</Button></div>
          </form>
        </DialogContent>
      </Dialog>
    </Page>
  );
}

export default function ArtifactsRoute() {
  return <Suspense><ArtifactsPage /></Suspense>;
}
