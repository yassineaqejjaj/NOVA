"use client";

import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Skeleton,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@nova/ui";
import { AnimatePresence, motion } from "framer-motion";
import { Check, ChevronRight, CircleAlert, Clock3, Download, ExternalLink, FileText, Loader2, MessageSquare, MoreHorizontal, Orbit, Share2 } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

import { ClassificationBadge } from "@/components/shell/page";
import { type SaveState, useArtifactEditor } from "@/hooks/use-artifact-editor";
import { useProjects } from "@/lib/api/hooks";
import type { ArtifactDetail, ContextSource, QualityCheck } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";

import { EditorToolbar } from "./editor-toolbar";
import { ArtifactSection } from "./section";
import { VersionHistory } from "./version-history";

const STATUS_LABEL: Record<string, string> = { draft: "Draft", in_review: "In review", final: "Final", archived: "Archived" };

function SaveLine({ save, artifact }: { save: SaveState; artifact: ArtifactDetail }) {
  const text =
    save.kind === "saving" ? "Saving…" : save.kind === "conflict" ? "Changed elsewhere — reload to continue" : save.kind === "error" ? save.message : `Last updated ${timeAgo(artifact.updated_at)}`;
  return (
    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[13px] text-muted">
      <span className="flex items-center gap-1.5">
        <span className={cn("size-2 rounded-full", artifact.status === "final" ? "bg-success" : artifact.status === "in_review" ? "bg-accent" : "bg-warning")} />
        {STATUS_LABEL[artifact.status] ?? artifact.status}
      </span>
      <span>·</span>
      <span data-testid="save-state" className={cn("whitespace-nowrap", save.kind === "conflict" && "text-warning")}>
        {save.kind === "saving" ? <Loader2 className="mr-1 inline size-3 animate-spin" /> : null}
        {text} · v{artifact.version}
      </span>
      <ClassificationBadge level={artifact.classification} />
    </div>
  );
}

function RailCard({ title, children, action }: { title: string; children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <section className="rounded-[18px] border border-border bg-surface p-4 shadow-panel">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-[14px] font-semibold">{title}</h3>
        {action}
      </div>
      {children}
    </section>
  );
}

function QualityRail({ checks }: { checks: QualityCheck[] }) {
  const ok = checks.length > 0 && checks.every((c) => c.status === "pass");
  return (
    <RailCard
      title="Quality check"
      action={
        <span className={cn("flex size-6 items-center justify-center rounded-full", ok ? "bg-success text-white" : "bg-warning/15 text-warning")}>
          {ok ? <Check className="size-3.5" /> : <CircleAlert className="size-3.5" />}
        </span>
      }
    >
      <ul className="space-y-2">
        {checks.map((c) => (
          <li key={c.key} className="flex items-start gap-2 text-[13px]">
            <span className="mt-0.5">
              {c.status === "pass" ? <Check className="size-3.5 text-success" /> : c.status === "pending" ? <Clock3 className="size-3.5 text-subtle" /> : <CircleAlert className="size-3.5 text-warning" />}
            </span>
            <span>
              <span className="block text-text">{c.label}</span>
              <span className="block text-[11.5px] text-subtle">{c.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </RailCard>
  );
}

function SourceRow({ s }: { s: ContextSource }) {
  return (
    <li className="rounded-[12px] border border-border px-3 py-2.5">
      <div className="flex items-center gap-2 text-[13.5px]">
        <span className="rounded bg-surface-3 px-1 font-mono text-[10.5px] text-subtle">{s.label}</span>
        {s.uri ? <a href={s.uri} target="_blank" rel="noreferrer" className="truncate font-medium hover:underline">{s.title}</a> : <span className="truncate font-medium">{s.title}</span>}
        <ClassificationBadge level={s.classification} />
        <span className="ml-auto shrink-0 text-[11.5px] text-subtle">{[s.type, s.updated ? timeAgo(s.updated) : null].filter(Boolean).join(" · ")}</span>
      </div>
      {s.excerpt ? <p className="mt-1 line-clamp-3 text-[12.5px] text-muted">“{s.excerpt}”</p> : null}
    </li>
  );
}

export function ArtifactDocument({ artifactId }: { artifactId: string }) {
  const editor = useArtifactEditor(artifactId);
  const { artifact, draft, save, editable, schedule, comments, approve, setStatus, viewingOld, viewVersion, setViewVersion, dirty, reload } = editor;
  const { data: projects } = useProjects();

  if (!artifact || !draft) {
    return (
      <div className="mx-auto max-w-[1120px] space-y-4 p-8">
        {editor.error ? <p className="text-muted">This Artifact is not available.</p> : <><Skeleton className="h-10 w-1/2" /><Skeleton className="h-96" /></>}
      </div>
    );
  }
  const project = projects?.find((p) => p.id === artifact.project_id);
  const allItems = Object.values(draft.sections).flatMap((s) => s.items);
  const share = async () => {
    await navigator.clipboard.writeText(window.location.href);
    toast(project ? `Link copied — visible to ${project.name} members.` : "Link copied — this Artifact is private to you.");
  };

  return (
    <div className="mx-auto w-full max-w-[1180px] px-5 pb-16 pt-6 md:px-8">
      <nav className="flex min-w-0 items-center gap-1.5 whitespace-nowrap text-[12.5px] text-subtle">
        <Link href="/projects" className="shrink-0 hover:text-text">Projects</Link>
        {project ? (<><ChevronRight className="size-3 shrink-0" /><Link href={`/projects/${project.id}`} className="min-w-0 truncate hover:text-text">{project.name}</Link></>) : null}
        <ChevronRight className="size-3 shrink-0" />
        <span className="shrink-0 text-muted">{artifact.type_name}</span>
      </nav>

      <header className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 basis-80">
          {editable ? (
            <input value={draft.title} onChange={(e) => schedule({ ...draft, title: e.target.value }, "title")} aria-label="Artifact title"
              className="w-full text-ellipsis bg-transparent text-[22px] font-semibold tracking-tight outline-none md:text-[26px]" />
          ) : (
            <h1 className="text-[22px] font-semibold tracking-tight md:text-[26px]">{draft.title}</h1>
          )}
          <SaveLine save={save} artifact={artifact} />
        </div>
        <div className="flex items-center gap-2">
          {save.kind === "conflict" ? <Button variant="secondary" size="sm" onClick={reload}>Reload</Button> : null}
          <Button variant="primary" className="rounded-full px-5" onClick={() => void share()}><Share2 /> Share</Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" size="icon" className="rounded-full" aria-label="More"><MoreHorizontal /></Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              {(["draft", "in_review", "final"] as const).map((st) => (
                <DropdownMenuItem key={st} onSelect={() => setStatus.mutate(st)}>{artifact.status === st ? <Check /> : <span className="size-4" />} Mark as {STATUS_LABEL[st]}</DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem asChild><a href={`/api/v1/artifacts/${artifactId}/export?format=md`}><Download /> Export Markdown</a></DropdownMenuItem>
              <DropdownMenuItem asChild><a href={`/api/v1/artifacts/${artifactId}/export?format=json`}><Download /> Export JSON</a></DropdownMenuItem>
              {artifact.conversation_id ? (
                <DropdownMenuItem asChild><Link href={`/c/${artifact.conversation_id}?artifact=${artifactId}`}><MessageSquare /> Open with conversation</Link></DropdownMenuItem>
              ) : null}
              {artifact.evaluation?.url ? (
                <DropdownMenuItem asChild><a href={artifact.evaluation.url} target="_blank" rel="noreferrer"><ExternalLink /> FORGE evaluation</a></DropdownMenuItem>
              ) : null}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>

      <AnimatePresence>
        {artifact.proposed_version && !viewingOld ? (
          <motion.div initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} className="mt-4 flex items-center gap-3 rounded-[14px] border border-warning/30 bg-warning/[0.07] px-4 py-2.5 text-[13.5px]">
            NOVA proposed version {artifact.proposed_version}.
            <Button size="sm" variant="ghost" onClick={() => setViewVersion(artifact.proposed_version)}>Review</Button>
            <Button size="sm" variant="primary" onClick={() => approve.mutate(artifact.proposed_version!)}><Check /> Approve</Button>
          </motion.div>
        ) : null}
        {viewingOld ? (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="mt-4 flex items-center gap-3 rounded-[14px] bg-surface-2 px-4 py-2.5 text-[13.5px] text-muted">
            Viewing version {viewVersion} ({artifact.version_state}) — read-only.
            <Button size="sm" variant="ghost" onClick={() => setViewVersion(null)}>Back to current</Button>
          </motion.div>
        ) : null}
      </AnimatePresence>

      <Tabs defaultValue="write" className="mt-6">
        <TabsList>
          <TabsTrigger value="write">Write</TabsTrigger>
          <TabsTrigger value="review">Review</TabsTrigger>
          <TabsTrigger value="evidence">Evidence</TabsTrigger>
        </TabsList>

        <TabsContent value="write" className="mt-5">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[minmax(0,1fr)_300px]">
            <article className="min-w-0 rounded-[22px] border border-border bg-surface shadow-panel">
              <div className="sticky top-0 z-10 rounded-t-[22px] border-b border-border bg-surface/95 px-5 py-2.5 backdrop-blur">
                <EditorToolbar disabled={!editable} />
              </div>
              <div className="px-6 pb-10 pt-6 md:px-10">
                <h2 className="text-[24px] font-semibold tracking-tight">{artifact.definition.name}</h2>
                <p className="mt-1 text-[14px] text-muted">{[draft.title.replace(/^[^·]+·\s*/, ""), project?.name].filter(Boolean).join(" – ")}</p>
                <div className="mt-4">
                  {artifact.definition.sections.map((definition, index) => (
                    <ArtifactSection
                      key={definition.key}
                      number={index + 1}
                      artifactId={artifactId}
                      definition={definition}
                      content={draft.sections[definition.key] ?? { kind: definition.kind, blocks: [], items: [] }}
                      editable={editable}
                      allItems={allItems}
                      comments={(comments ?? []).filter((c) => c.section_key === definition.key)}
                      versionKey={`${definition.key}-${artifact.viewing_version}-${dirty.size === 0 ? "s" : "l"}`}
                      conversationId={artifact.conversation_id}
                      onChange={(section) => schedule({ ...draft, sections: { ...draft.sections, [definition.key]: section } }, definition.key)}
                    />
                  ))}
                </div>
              </div>
            </article>

            <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
              <RailCard title="Context" action={<Orbit className="size-4 text-subtle" />}>
                <div className="text-[13px] text-muted">
                  <span className="text-[22px] font-semibold text-text">{artifact.evidence.sources_count}</span> source{artifact.evidence.sources_count === 1 ? "" : "s"} cited
                </div>
                <div className="mt-0.5 text-[12px] text-subtle">{artifact.evidence.updated_at ? `Context retrieved ${timeAgo(artifact.evidence.updated_at)}` : "No ORBIT context recorded"}</div>
              </RailCard>
              <RailCard title="Key evidence">
                {artifact.evidence.by_type.length ? (
                  <ul className="space-y-2.5">
                    {artifact.evidence.by_type.map((t) => (
                      <li key={t.type} className="flex items-center gap-2.5 text-[13px]">
                        <span className="flex size-7 items-center justify-center rounded-[8px] bg-accent-soft text-accent"><FileText className="size-3.5" /></span>
                        <span className="flex-1 capitalize">{t.type.replaceAll("_", " ")}</span>
                        <span className="text-[12px] text-subtle">{t.count} source{t.count > 1 ? "s" : ""}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[12.5px] text-subtle">No cited evidence yet. Use “Ask NOVA → Add evidence” on a section.</p>
                )}
              </RailCard>
              <QualityRail checks={artifact.quality} />
            </aside>
          </div>
        </TabsContent>

        <TabsContent value="review" className="mt-5">
          <div className="grid grid-cols-[minmax(0,1fr)] gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
            <div className="overflow-hidden rounded-[18px] border border-border bg-surface shadow-panel">
              <VersionHistory artifactId={artifactId} current={artifact.version} viewing={viewVersion} onView={(v) => setViewVersion(v === artifact.version ? null : v)} definition={artifact.definition} />
            </div>
            <section className="rounded-[18px] border border-border bg-surface p-5 shadow-panel">
              <h3 className="mb-3 text-[14px] font-semibold">Comments</h3>
              {comments?.length ? (
                <ul className="space-y-3">
                  {comments.map((c) => (
                    <li key={c.id} className={cn("text-[13.5px]", c.resolved && "opacity-50")}>
                      <div className="text-[12px] text-subtle">
                        {c.author_name} · {artifact.definition.sections.find((s) => s.key === c.section_key)?.title} · {timeAgo(c.created_at)}
                      </div>
                      <p>{c.body}</p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13px] text-subtle">No comments yet. Add one from any section in Write.</p>
              )}
            </section>
          </div>
        </TabsContent>

        <TabsContent value="evidence" className="mt-5">
          <section className="rounded-[18px] border border-border bg-surface p-5 shadow-panel">
            <h3 className="text-[14px] font-semibold">Sources cited in this Artifact</h3>
            <p className="mb-4 mt-0.5 text-[12.5px] text-subtle">Recorded when NOVA wrote it — exactly what ORBIT served, never re-searched.</p>
            {artifact.evidence.sources.length ? (
              <ul className="space-y-2">{artifact.evidence.sources.map((s) => <SourceRow key={`${s.reference_id}-${s.label}`} s={s} />)}</ul>
            ) : (
              <p className="text-[13px] text-subtle">No source cited.</p>
            )}
          </section>
        </TabsContent>
      </Tabs>
    </div>
  );
}
