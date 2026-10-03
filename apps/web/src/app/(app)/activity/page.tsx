"use client";

import { Input, Select, Tabs, TabsList, TabsTrigger } from "@nova/ui";
import { Search } from "lucide-react";
import { useState } from "react";

import { ActivityFeed } from "@/components/activity-feed";
import { useProjects } from "@/lib/api/hooks";

const TABS = [
  { value: "all", label: "All activity" },
  { value: "projects", label: "My projects" },
  { value: "artifact", label: "Artifacts" },
  { value: "decision", label: "Decisions" },
];

export default function ActivityPage() {
  const { data: projects } = useProjects();
  const [tab, setTab] = useState("all");
  const [project, setProject] = useState("all");
  const [query, setQuery] = useState("");
  return (
    <div className="mx-auto w-full max-w-[960px] px-5 pb-16 pt-8 md:px-8">
      <h1 className="text-[28px] font-semibold tracking-tight">Activity</h1>
      <p className="mt-1 text-[14px] text-muted">Everything NOVA did for you, and every decision you made.</p>

      <div className="mt-6 flex flex-wrap items-center gap-3 border-b border-border pb-3">
        <Tabs value={tab} onValueChange={setTab} className="-mx-1 max-w-full overflow-x-auto px-1">
          <TabsList className="whitespace-nowrap">
            {TABS.map((t) => <TabsTrigger key={t.value} value={t.value}>{t.label}</TabsTrigger>)}
          </TabsList>
        </Tabs>
        <div className="flex w-full flex-wrap items-center gap-2 sm:ml-auto sm:w-auto">
          <Select
            ariaLabel="Project"
            value={project}
            onValueChange={setProject}
            options={[{ value: "all", label: "All projects" }, ...(projects ?? []).map((p) => ({ value: p.id, label: p.name }))]}
            className="w-full sm:w-44"
          />
          <label className="relative w-full sm:w-auto">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-subtle" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search activity" aria-label="Search activity" className="w-full rounded-full pl-8 sm:w-52" />
          </label>
        </div>
      </div>

      <div className="mt-6">
        <ActivityFeed filters={{ project_id: project === "all" ? undefined : project }} category={tab} query={query} />
      </div>
    </div>
  );
}
