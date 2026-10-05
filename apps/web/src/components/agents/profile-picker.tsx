"use client";

import { cn } from "@nova/ui";
import { Check } from "lucide-react";

import { AgentAvatar } from "@/components/agents/sub-agents";
import { AGENT_PROFILES, AGENTS, type AgentProfile } from "@/lib/agents";
import { useLang } from "@/lib/i18n";

/** The four profiles NOVA serves, each led by its specialist agent. */
export function ProfilePicker({ value, onChange, compact = false }: { value: AgentProfile; onChange: (profile: AgentProfile) => void; compact?: boolean }) {
  const lang = useLang();
  return (
    <div role="radiogroup" className={cn("grid gap-2", compact ? "sm:grid-cols-2" : "sm:grid-cols-2")}>
      {AGENT_PROFILES.map((p) => {
        const agent = AGENTS[p];
        const selected = value === p;
        return (
          <button
            key={p}
            type="button"
            role="radio"
            aria-checked={selected}
            onClick={() => onChange(p)}
            className={cn(
              "flex items-start gap-3 rounded-[14px] border px-3.5 py-3 text-left transition-colors",
              selected ? "border-accent/50 bg-accent-soft" : "border-border hover:border-border-strong",
            )}
          >
            <AgentAvatar profile={p} size={32} />
            <span className="min-w-0 flex-1">
              <span className="flex items-center gap-2 text-[14px] font-medium">
                {agent.short[lang]}
                {selected ? <Check className="size-3.5 text-accent" /> : null}
              </span>
              <span className="block text-[12px] text-subtle">{agent.role[lang]}</span>
              {!compact ? <span className="mt-1 block text-[12.5px] text-muted">{agent.mission[lang]}</span> : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}
