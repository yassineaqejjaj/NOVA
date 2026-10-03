"use client";

import { ClassificationBadge } from "@/components/shell/page";
import { cn } from "@nova/ui";
import { motion } from "framer-motion";
import { ArrowRight, Orbit, Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";

import type { Recommendation } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";
import { useComposer } from "@/stores/ui";

export function Recommendations({ items }: { items: Recommendation[] }) {
  const router = useRouter();
  const composer = useComposer();
  const act = (r: Recommendation) => {
    if (r.href) {
      if (r.href.startsWith("http")) window.open(r.href, "_blank");
      else router.push(r.href);
      return;
    }
    if (r.conversation_id) {
      router.push(`/c/${r.conversation_id}`);
      return;
    }
    if (r.prompt) {
      if (r.project_id) composer.setProject(r.project_id);
      if (r.artifact_id) composer.addArtifactRef({ id: r.artifact_id, title: r.subtitle ?? "Artifact" });
      composer.setDraft(r.prompt);
      document.getElementById("nova-composer")?.focus();
    }
  };
  if (!items.length) return null;
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-[14px] border border-border">
      {items.map((r, i) => (
        <motion.li key={r.id} initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2, delay: i * 0.04 }}>
          <button onClick={() => act(r)} className="group flex w-full items-center gap-3.5 bg-surface/50 px-4 py-3 text-left transition-colors hover:bg-surface-2">
            <span className={cn("flex size-8 shrink-0 items-center justify-center rounded-[10px]", r.source === "orbit" ? "bg-surface-3 text-muted" : "bg-accent-soft text-accent")}>
              {r.source === "orbit" ? <Orbit className="size-4" /> : <Sparkles className="size-4" />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2">
                <span className="truncate text-[14px] text-text">{r.title}</span>
                {r.classification !== undefined ? <ClassificationBadge level={r.classification} /> : null}
              </span>
              <span className="block truncate text-[12.5px] text-subtle">
                {[r.project_name, r.subtitle, timeAgo(r.at)].filter(Boolean).join(" · ")}
              </span>
            </span>
            <span className="flex shrink-0 items-center gap-1 text-[12.5px] text-muted group-hover:text-accent">
              {r.action} <ArrowRight className="size-3.5 transition-transform group-hover:translate-x-0.5" />
            </span>
          </button>
        </motion.li>
      ))}
    </ul>
  );
}
