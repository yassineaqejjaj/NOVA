"use client";

import { Input, Select, Tabs, TabsList, TabsTrigger } from "@nova/ui";
import { Search } from "lucide-react";
import { useState } from "react";

import { ActivityFeed } from "@/components/activity-feed";
import { useProjects } from "@/lib/api/hooks";
import { defineMessages, useT } from "@/lib/i18n";

const M = defineMessages({
  en: {
    title: "Timeline",
    description: "How your work moved: ORBIT supplies the context, NOVA acts, FORGE evaluates — and what you decided.",
    tab_all: "Everything",
    tab_projects: "My projects",
    tab_artifact: "Artifacts",
    tab_decision: "Decisions",
    tab_quality: "Quality",
    project: "Project",
    allProjects: "All projects",
    search: "Search activity",
  },
  fr: {
    title: "Timeline",
    description: "Comment votre travail a avancé : ORBIT fournit le contexte, NOVA agit, FORGE évalue — et ce que vous avez décidé.",
    tab_all: "Tout",
    tab_projects: "Mes projets",
    tab_artifact: "Artefacts",
    tab_decision: "Décisions",
    tab_quality: "Qualité",
    project: "Projet",
    allProjects: "Tous les projets",
    search: "Rechercher dans l’activité",
  },
});

const TABS = ["all", "projects", "artifact", "decision", "quality"] as const;

export default function ActivityPage() {
  const { data: projects } = useProjects();
  const t = useT(M);
  const [tab, setTab] = useState("all");
  const [project, setProject] = useState("all");
  const [query, setQuery] = useState("");
  return (
    <div className="mx-auto w-full max-w-[960px] px-5 pb-16 pt-8 md:px-8">
      <h1 className="text-[28px] font-semibold tracking-tight">{t("title")}</h1>
      <p className="mt-1 text-[14px] text-muted">{t("description")}</p>

      <div className="mt-6 flex flex-wrap items-center gap-3 border-b border-border pb-3">
        <Tabs value={tab} onValueChange={setTab} className="-mx-1 max-w-full overflow-x-auto px-1">
          <TabsList className="whitespace-nowrap">
            {TABS.map((v) => <TabsTrigger key={v} value={v}>{t(`tab_${v}`)}</TabsTrigger>)}
          </TabsList>
        </Tabs>
        <div className="flex w-full flex-wrap items-center gap-2 sm:ml-auto sm:w-auto">
          <Select
            ariaLabel={t("project")}
            value={project}
            onValueChange={setProject}
            options={[{ value: "all", label: t("allProjects") }, ...(projects ?? []).map((p) => ({ value: p.id, label: p.name }))]}
            className="w-full sm:w-44"
          />
          <label className="relative w-full sm:w-auto">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-subtle" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("search")} aria-label={t("search")} className="w-full rounded-full pl-8 sm:w-52" />
          </label>
        </div>
      </div>

      <div className="mt-6">
        <ActivityFeed filters={{ project_id: project === "all" ? undefined : project }} category={tab} query={query} />
      </div>
    </div>
  );
}
