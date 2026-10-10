"use client";

import { Skeleton } from "@nova/ui";

import { Composer } from "@/components/composer/composer";
import {
  Attention,
  ContextStatus,
  ContinueList,
  QualityStatus,
  RecentResults,
  Suggestions,
  WorkingOn,
} from "@/components/home/command-center";
import { GettingStarted } from "@/components/home/getting-started";
import { GoalsStrip, ImpactCard, ProactiveHero, ProductPulse, RecommendedToday } from "@/components/home/today";
import { NovaOrb, ORB_LABEL } from "@/components/shell/nova-orb";
import { TopSearch } from "@/components/shell/sidebar";
import { useArtifacts, useTasks, useToday } from "@/lib/api/hooks";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: { status: "NOVA status", request: "New request", placeholder: "Ask NOVA anything — what do you want to get done?", capabilities: "Capabilities" },
  fr: { status: "Statut de NOVA", request: "Nouvelle demande", placeholder: "Demandez ce que vous voulez à NOVA — que voulez-vous accomplir ?", capabilities: "Capacités" },
});

/**
 * Home — NOVA's command center: what NOVA knows, what it is doing, what needs the user now.
 * Everything starts from "Ask NOVA"; ORBIT (context) and FORGE (quality) stay background capabilities.
 */
export default function HomePage() {
  const t = useT(M);
  const { data: today, isLoading } = useToday();
  const { data: active } = useTasks("active");
  const { data: artifacts } = useArtifacts({});

  return (
    <div className="mx-auto w-full max-w-[1080px] px-5 pb-16 pt-4 md:px-8">
      <div className="mb-4 flex items-center justify-between gap-3">
        <TopSearch />
        {today ? (
          <span className="flex items-center gap-2 rounded-full bg-surface-2/80 py-1 pl-1.5 pr-3 text-[12.5px] text-muted" aria-label={t("status")}>
            <NovaOrb state={today.nova.state} size={22} /> {ORB_LABEL[today.nova.state]}
          </span>
        ) : null}
      </div>

      {today ? <ProactiveHero today={today} /> : <Skeleton className="h-[230px] rounded-[28px]" />}

      {today ? <GettingStarted today={today} /> : null}

      <section aria-label={t("request")} className="mt-6 space-y-3">
        <Suggestions />
        <Composer variant="command" placeholder={t("placeholder")} />
      </section>

      {today?.continue.length ? (
        <div className="mt-8">
          <ContinueList items={today.continue} />
        </div>
      ) : null}

      <div className="mt-10 grid grid-cols-[minmax(0,1fr)] gap-10 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="space-y-10">
          {today ? <RecommendedToday today={today} /> : <Attention items={[]} loading={isLoading} />}
          {today ? <GoalsStrip today={today} /> : null}
          {today ? <ProductPulse today={today} /> : null}
          <WorkingOn tasks={active ?? []} />
          <RecentResults artifacts={(artifacts ?? []).slice(0, 5)} />
        </div>
        <aside className="space-y-3 lg:sticky lg:top-6 lg:self-start" aria-label={t("capabilities")}>
          {today ? (
            <>
              <ImpactCard />
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
