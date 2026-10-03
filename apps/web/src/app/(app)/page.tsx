"use client";

import { Skeleton } from "@nova/ui";

import { Composer } from "@/components/composer/composer";
import {
  Attention,
  ContextStatus,
  ContinueList,
  Hero,
  QualityStatus,
  RecentResults,
  Suggestions,
  WorkingOn,
} from "@/components/home/command-center";
import { NovaOrb, ORB_LABEL } from "@/components/shell/nova-orb";
import { TopSearch } from "@/components/shell/sidebar";
import { useArtifacts, useTasks, useToday } from "@/lib/api/hooks";

/**
 * Home — NOVA's command center: what NOVA knows, what it is doing, what needs the user now.
 * Everything starts from "Ask NOVA"; ORBIT (context) and FORGE (quality) stay background capabilities.
 */
export default function HomePage() {
  const { data: today, isLoading } = useToday();
  const { data: active } = useTasks("active");
  const { data: artifacts } = useArtifacts({});
  const scrollTo = (id: string) => document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });

  return (
    <div className="mx-auto w-full max-w-[1080px] px-5 pb-16 pt-4 md:px-8">
      <div className="mb-4 flex items-center justify-between gap-3">
        <TopSearch />
        {today ? (
          <span className="flex items-center gap-2 rounded-full bg-surface-2/80 py-1 pl-1.5 pr-3 text-[12.5px] text-muted" aria-label="NOVA status">
            <NovaOrb state={today.nova.state} size={22} /> {ORB_LABEL[today.nova.state]}
          </span>
        ) : null}
      </div>

      {today ? <Hero today={today} onScrollTo={scrollTo} /> : <Skeleton className="h-[230px] rounded-[28px]" />}

      <section aria-label="New request" className="mt-6 space-y-3">
        <Suggestions />
        <Composer variant="command" placeholder="Ask NOVA anything — what do you want to get done?" />
      </section>

      {today?.continue.length ? (
        <div className="mt-8">
          <ContinueList items={today.continue} />
        </div>
      ) : null}

      <div className="mt-10 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-10">
          <Attention items={today?.recommendations ?? []} loading={isLoading} />
          <WorkingOn tasks={active ?? []} />
          <RecentResults artifacts={(artifacts ?? []).slice(0, 5)} />
        </div>
        <aside className="space-y-3 lg:sticky lg:top-6 lg:self-start" aria-label="Capabilities">
          {today ? (
            <>
              <ContextStatus context={today.context} />
              <QualityStatus quality={today.quality} />
            </>
          ) : (
            <Skeleton className="h-36 rounded-[18px]" />
          )}
        </aside>
      </div>
    </div>
  );
}
