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
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    title: "Projects",
    description: "Projects organize NOVA's work. Knowledge stays in ORBIT.",
    synced: (v: { n: number }) => `${v.n} project${v.n === 1 ? "" : "s"} synced from ORBIT.`,
    sync: "Sync from ORBIT",
    newProject: "New project",
    linked: "Linked to ORBIT",
    noDescription: "No description",
    artifacts: (v: { n: number }) => `${v.n} Artifact${v.n === 1 ? "" : "s"}`,
    active: (v: { n: number }) => `${v.n} active`,
    emptyTitle: "Your projects will appear here when context is available.",
    emptyLinked: "Sync your ORBIT projects or create one.",
    emptyUnlinked: "Connect ORBIT to bring your projects, or create one.",
    connect: "Connect ORBIT",
    dialogDescription: "Link it to ORBIT later to give NOVA its context.",
    name: "Name",
    descriptionLabel: "Description",
    create: "Create",
    role_owner: "owner",
    role_editor: "editor",
    role_viewer: "viewer",
  },
  fr: {
    title: "Projets",
    description: "Les projets organisent le travail de NOVA. La connaissance reste dans ORBIT.",
    synced: (v: { n: number }) => (v.n > 1 ? `${v.n} projets synchronisés depuis ORBIT.` : `${v.n} projet synchronisé depuis ORBIT.`),
    sync: "Synchroniser depuis ORBIT",
    newProject: "Nouveau projet",
    linked: "Lié à ORBIT",
    noDescription: "Aucune description",
    artifacts: (v: { n: number }) => `${v.n} Artefact${v.n > 1 ? "s" : ""}`,
    active: (v: { n: number }) => `${v.n} en cours`,
    emptyTitle: "Vos projets apparaîtront ici dès que le contexte sera disponible.",
    emptyLinked: "Synchronisez vos projets ORBIT ou créez-en un.",
    emptyUnlinked: "Connectez ORBIT pour importer vos projets, ou créez-en un.",
    connect: "Connecter ORBIT",
    dialogDescription: "Liez-le à ORBIT plus tard pour donner son contexte à NOVA.",
    name: "Nom",
    descriptionLabel: "Description",
    create: "Créer",
    role_owner: "propriétaire",
    role_editor: "éditeur",
    role_viewer: "lecteur",
  },
});

type RoleKey = "role_owner" | "role_editor" | "role_viewer";

export default function ProjectsPage() {
  const { data: projects, isLoading } = useProjects();
  const { data: me } = useMe();
  const t = useT(M);
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const sync = useMutation({
    mutationFn: () => api.post<{ synced: number }>("/projects/sync"),
    onSuccess: (r) => { toast(t("synced", { n: r.synced })); void client.invalidateQueries({ queryKey: keys.projects }); },
  });
  const create = useMutation({
    mutationFn: () => api.post<Project>("/projects", { name, description }),
    onSuccess: () => { setOpen(false); setName(""); setDescription(""); void client.invalidateQueries({ queryKey: keys.projects }); },
  });

  return (
    <Page wide>
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <>
            {me?.orbit.linked ? <Button variant="ghost" size="sm" onClick={() => sync.mutate()} disabled={sync.isPending}><RefreshCw /> {t("sync")}</Button> : null}
            <Button size="sm" onClick={() => setOpen(true)}><Plus /> {t("newProject")}</Button>
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
                {p.orbit_slug ? <Orbit className="size-3.5 text-subtle" aria-label={t("linked")} /> : null}
                <span className="ml-auto text-[11.5px] capitalize text-subtle">{p.role && ["owner", "editor", "viewer"].includes(p.role) ? t(`role_${p.role}` as RoleKey) : p.role}</span>
              </div>
              <p className="mt-0.5 line-clamp-2 text-[13px] text-muted">{p.description || t("noDescription")}</p>
              <div className="mt-3 flex gap-4 text-[12px] text-subtle">
                <span>{t("artifacts", { n: p.stats.artifacts ?? 0 })}</span>
                <span>{t("active", { n: p.stats.active_work ?? 0 })}</span>
                <span className="ml-auto">{timeAgo(p.updated_at)}</span>
              </div>
            </Link>
          ))}
        </div>
      ) : !isLoading ? (
        <EmptyState
          icon={<FolderKanban />}
          title={t("emptyTitle")}
          description={me?.orbit.linked ? t("emptyLinked") : t("emptyUnlinked")}
          action={me?.orbit.linked ? <Button onClick={() => sync.mutate()}>{t("sync")}</Button> : <Button asChild><Link href="/settings#orbit">{t("connect")}</Link></Button>}
        />
      ) : null}
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent title={t("newProject")} description={t("dialogDescription")}>
          <form onSubmit={(e) => { e.preventDefault(); create.mutate(); }} className="space-y-3">
            <div className="space-y-1.5"><Label htmlFor="pname">{t("name")}</Label><Input id="pname" required value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div className="space-y-1.5"><Label htmlFor="pdesc">{t("descriptionLabel")}</Label><Textarea id="pdesc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></div>
            <div className="flex justify-end"><Button type="submit" variant="primary" disabled={!name.trim() || create.isPending}>{t("create")}</Button></div>
          </form>
        </DialogContent>
      </Dialog>
    </Page>
  );
}
