"use client";

import { Badge, Button, cn, Skeleton } from "@nova/ui";
import { motion } from "framer-motion";
import { ArrowRight, ChevronRight, FileText, Flame, ListTodo, Orbit, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Composer } from "@/components/composer/composer";
import { ClassificationBadge } from "@/components/shell/page";
import { TopSearch } from "@/components/shell/sidebar";
import { HeroArt } from "@/components/today/hero-art";
import { useArtifacts, useProjects, useTasks, useToday } from "@/lib/api/hooks";
import type { Recommendation } from "@/lib/api/types";
import { greeting, timeAgo } from "@/lib/format";
import { useComposer } from "@/stores/ui";

function CountBadge({ n }: { n: number }) {
  return <span className="inline-flex min-w-5 items-center justify-center rounded-full bg-accent px-1.5 text-[11px] font-semibold leading-5 text-accent-fg">{n}</span>;
}

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return <section className={cn("rounded-[20px] border border-border bg-surface p-5 shadow-panel", className)}>{children}</section>;
}

function useRecommendationAction() {
  const router = useRouter();
  const composer = useComposer();
  return (r: Recommendation) => {
    if (r.href) {
      if (r.href.startsWith("http")) window.open(r.href, "_blank");
      else router.push(r.href);
    } else if (r.conversation_id) router.push(`/c/${r.conversation_id}`);
    else if (r.prompt) {
      if (r.project_id) composer.setProject(r.project_id);
      if (r.artifact_id) composer.addArtifactRef({ id: r.artifact_id, title: r.subtitle ?? "Artifact" });
      composer.setDraft(r.prompt);
      document.getElementById("nova-composer")?.focus();
    }
  };
}

function NeedsAttention({ items }: { items: Recommendation[] }) {
  const act = useRecommendationAction();
  const [expanded, setExpanded] = useState(false);
  const [featured, ...rest] = items;
  const others = expanded ? rest : rest.slice(0, 2);
  return (
    <Card className="relative w-full max-w-[720px]">
      <h2 className="mb-4 flex items-center gap-2 text-[15px] font-semibold">
        <Flame className="size-4 text-accent" /> Needs your attention <CountBadge n={items.length} />
      </h2>
      {featured ? (
        <div className="rounded-[16px] border border-border bg-background/60 p-4">
          <div className="flex items-center gap-2.5">
            <span className="flex size-8 items-center justify-center rounded-full bg-text text-[12px] font-semibold text-background">
              {(featured.project_name ?? "N").slice(0, 1)}
            </span>
            <div className="min-w-0 text-[12.5px] leading-tight">
              <div className="truncate font-medium">{featured.project_name ?? "Your work"}</div>
              <div className="text-subtle">{featured.source === "orbit" ? "ORBIT change" : "NOVA"}</div>
            </div>
          </div>
          <div className="mt-3 flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-0 flex-1 basis-64">
              <p className="text-[17px] font-semibold leading-snug tracking-tight">{featured.title}</p>
              {featured.subtitle ? <p className="mt-1 line-clamp-2 text-[13px] text-muted">{featured.subtitle}</p> : null}
              <div className="mt-2.5 flex flex-wrap items-center gap-2 text-[12px] text-subtle">
                {featured.classification !== undefined ? <ClassificationBadge level={featured.classification} /> : null}
                <span className="inline-flex items-center gap-1">
                  {featured.source === "orbit" ? <Orbit className="size-3.5" /> : <Sparkles className="size-3.5" />}
                  {featured.source === "orbit" ? "From the ORBIT change feed" : "From your NOVA work"}
                </span>
                <span>· {timeAgo(featured.at)}</span>
              </div>
            </div>
            <Button variant="primary" className="rounded-full px-5" onClick={() => act(featured)}>
              {featured.action} <ArrowRight />
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-[13.5px] text-muted">Nothing needs your attention right now.</p>
      )}
      {others.length ? (
        <ul className="mt-3 divide-y divide-border">
          {others.map((r) => (
            <li key={r.id}>
              <button onClick={() => act(r)} className="group flex w-full items-center gap-3 py-2.5 text-left">
                {r.source === "orbit" ? <Orbit className="size-4 shrink-0 text-subtle" /> : <Sparkles className="size-4 shrink-0 text-accent" />}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13.5px]">{r.title}</span>
                  <span className="block truncate text-[12px] text-subtle">{[r.project_name, timeAgo(r.at)].filter(Boolean).join(" · ")}</span>
                </span>
                <span className="shrink-0 text-[12.5px] text-muted group-hover:text-accent max-sm:hidden">{r.action}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {rest.length > 2 ? (
        <button onClick={() => setExpanded(!expanded)} className="mt-1 text-[12.5px] text-muted hover:text-accent">
          {expanded ? "Show less" : `Show ${rest.length - 2} more`}
        </button>
      ) : null}
    </Card>
  );
}

export default function HomePage() {
  const { data: today, isLoading } = useToday();
  const { data: active } = useTasks("active");
  const { data: artifacts } = useArtifacts({});
  const { data: projects } = useProjects();
  const names = new Map(projects?.map((p) => [p.id, p.name]));
  const [hello, setHello] = useState("Hello");
  useEffect(() => setHello(greeting()), []);
  const recommendations = today?.recommendations ?? [];
  const recent = (artifacts ?? []).slice(0, 4);

  return (
    <div className="relative min-h-screen">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-[520px] bg-[radial-gradient(ellipse_at_70%_0%,var(--glow),transparent_60%)] opacity-60" />
      <div className="relative mx-auto w-full max-w-[1120px] px-5 pb-36 pt-5 md:px-8">
        <div className="mb-8 flex justify-center">
          <TopSearch />
        </div>

        <div className="relative overflow-hidden rounded-[28px]">
          <HeroArt className="absolute inset-0" />
          <div className="absolute inset-0 bg-[linear-gradient(90deg,var(--background)_0%,color-mix(in_srgb,var(--background)_88%,transparent)_34%,transparent_62%)]" />
          <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25 }} className="relative px-6 py-10 md:px-10 md:pb-24 md:pt-14">
            <p className="text-[15px] text-muted">
              {hello}
              {today ? `, ${today.user.first_name}.` : "."}
            </p>
            <h1 className="mt-2 text-[40px] font-semibold leading-[1.05] tracking-tight md:text-[52px]">
              Here&apos;s what matters
              <br />
              <span className="text-accent">today.</span>
            </h1>
            <p className="mt-4 max-w-[440px] text-[15px] text-muted">
              {isLoading
                ? "Reviewing your projects…"
                : recommendations.length
                  ? `I've reviewed your projects and found ${recommendations.length} update${recommendations.length > 1 ? "s" : ""} that need${recommendations.length > 1 ? "" : "s"} your attention.`
                  : "I've reviewed your projects — nothing needs your attention right now."}
            </p>
          </motion.div>
        </div>

        <div className="relative -mt-8 grid grid-cols-[minmax(0,1fr)] gap-5 px-0 md:-mt-12 md:px-6">
          {isLoading ? <Skeleton className="h-48 rounded-[20px]" /> : <NeedsAttention items={recommendations} />}

          <div className="grid grid-cols-[minmax(0,1fr)] gap-5 md:grid-cols-2">
            <Card>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-[15px] font-semibold">
                  <ListTodo className="size-4 text-accent" /> NOVA is working on <CountBadge n={active?.length ?? 0} />
                </h2>
                <Link href="/work" className="text-[12.5px] text-muted hover:text-accent">View all</Link>
              </div>
              {active?.length ? (
                <ul className="space-y-3">
                  {active.slice(0, 4).map((t) => {
                    const pct = t.progress_total ? Math.round((t.progress_done / t.progress_total) * 100) : 0;
                    return (
                      <li key={t.id}>
                        <Link href={t.conversation_id ? `/c/${t.conversation_id}` : `/work?task=${t.id}`} className="flex items-center gap-3 rounded-[14px] p-2 hover:bg-surface-2">
                          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent">
                            <Sparkles className="size-4" />
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center justify-between gap-2">
                              <span className="truncate text-[13.5px] font-medium">{t.objective}</span>
                              <span className="shrink-0 text-[12px] text-muted">{t.status === "waiting_user" ? "Waiting for you" : `${pct}%`}</span>
                            </span>
                            <span className="block truncate text-[12px] text-subtle">
                              {[t.project_id ? names.get(t.project_id) : null, t.phase_label || t.skills.join(" → ")].filter(Boolean).join(" · ")}
                            </span>
                            <span className="mt-1.5 block h-1.5 overflow-hidden rounded-full bg-surface-3">
                              <motion.span className="block h-full rounded-full bg-gradient-to-r from-[#f9a8bf] to-accent" initial={false} animate={{ width: `${Math.max(pct, 4)}%` }} transition={{ duration: 0.25 }} />
                            </span>
                          </span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="text-[13.5px] text-muted">NOVA has no active tasks.</p>
              )}
            </Card>

            <Card>
              <div className="mb-3 flex items-center justify-between">
                <h2 className="flex items-center gap-2 text-[15px] font-semibold">
                  <FileText className="size-4 text-accent" /> Recent results <Badge>{recent.length}</Badge>
                </h2>
                <Link href="/library" className="text-[12.5px] text-muted hover:text-accent">Library</Link>
              </div>
              {recent.length ? (
                <ul className="divide-y divide-border">
                  {recent.map((a) => (
                    <li key={a.id}>
                      <Link href={`/artifacts/${a.id}`} className="group flex items-center gap-3 py-2.5">
                        <span className="flex size-9 shrink-0 items-center justify-center rounded-[10px] bg-accent-soft text-accent">
                          <FileText className="size-4" />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[13.5px] font-medium">{a.title.replace(/^[^·]+·\s*/, "")}</span>
                          <span className="block truncate text-[12px] text-subtle">
                            {[a.type_name, a.project_id ? names.get(a.project_id) : null, timeAgo(a.updated_at)].filter(Boolean).join(" · ")}
                          </span>
                        </span>
                        <ChevronRight className="size-4 text-subtle group-hover:text-accent" />
                      </Link>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-[13.5px] text-muted">Your work with NOVA will appear here.</p>
              )}
            </Card>
          </div>
        </div>
      </div>

      <div className="fixed inset-x-0 bottom-16 z-30 px-4 md:bottom-6 md:left-[224px]">
        <div className="mx-auto max-w-[760px]">
          <Composer variant="pill" placeholder="Tell NOVA what you need…" />
        </div>
      </div>
    </div>
  );
}
