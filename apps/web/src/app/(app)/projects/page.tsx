"use client";

import { Button, Dialog, DialogContent, Input, Label, Skeleton, Textarea } from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { FolderKanban, Orbit, Plus, RefreshCw } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState, Page, PageHeader } from "@/components/shell/page";
import { api } from "@/lib/api/client";
import { keys, useMe, useProjects } from "@/lib/api/hooks";
import type { Project } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";

export default function ProjectsPage() {
  const { data: projects, isLoading } = useProjects();
  const { data: me } = useMe();
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const sync = useMutation({
    mutationFn: () => api.post<{ synced: number }>("/projects/sync"),
    onSuccess: (r) => { toast(`${r.synced} project(s) synced from ORBIT.`); void client.invalidateQueries({ queryKey: keys.projects }); },
  });
  const create = useMutation({
    mutationFn: () => api.post<Project>("/projects", { name, description }),
    onSuccess: () => { setOpen(false); setName(""); setDescription(""); void client.invalidateQueries({ queryKey: keys.projects }); },
  });

  return (
    <Page wide>
      <PageHeader
        title="Projects"
        description="Projects organize NOVA's work. Knowledge stays in ORBIT."
        actions={
          <>
            {me?.orbit.linked ? <Button variant="ghost" size="sm" onClick={() => sync.mutate()} disabled={sync.isPending}><RefreshCw /> Sync from ORBIT</Button> : null}
            <Button size="sm" onClick={() => setOpen(true)}><Plus /> New project</Button>
          </>
        }
      />
      {isLoading ? <div className="grid gap-3 sm:grid-cols-2"><Skeleton className="h-28" /><Skeleton className="h-28" /></div> : null}
      {projects?.length ? (
        <div className="grid gap-3 sm:grid-cols-2">
          {projects.map((p) => (
            <Link key={p.id} href={`/projects/${p.id}`} className="group rounded-[14px] border border-border bg-surface p-4 transition-colors hover:border-border-strong">
              <div className="flex items-center gap-2">
                <span className="text-[15px] font-semibold">{p.name}</span>
                {p.orbit_slug ? <Orbit className="size-3.5 text-subtle" aria-label="Linked to ORBIT" /> : null}
                <span className="ml-auto text-[11.5px] capitalize text-subtle">{p.role}</span>
              </div>
              <p className="mt-0.5 line-clamp-2 text-[13px] text-muted">{p.description || "No description"}</p>
              <div className="mt-3 flex gap-4 text-[12px] text-subtle">
                <span>{p.stats.artifacts ?? 0} artifacts</span>
                <span>{p.stats.active_work ?? 0} active</span>
                <span className="ml-auto">{timeAgo(p.updated_at)}</span>
              </div>
            </Link>
          ))}
        </div>
      ) : !isLoading ? (
        <EmptyState
          icon={<FolderKanban />}
          title="Your projects will appear here when context is available."
          description={me?.orbit.linked ? "Sync your ORBIT projects or create one." : "Connect ORBIT to bring your projects, or create one."}
          action={me?.orbit.linked ? <Button onClick={() => sync.mutate()}>Sync from ORBIT</Button> : <Button asChild><Link href="/settings#orbit">Connect ORBIT</Link></Button>}
        />
      ) : null}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title="New project" description="Link it to ORBIT later to give NOVA its context.">
          <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} className="space-y-3">
            <div className="space-y-1.5"><Label htmlFor="pname">Name</Label><Input id="pname" required value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="pdesc">Description</Label><Textarea id="pdesc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></div>
            <div className="flex justify-end"><Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>Create</Button></div>
          </form>
        </DialogContent>
      </Dialog>
    </Page>
  );
}
