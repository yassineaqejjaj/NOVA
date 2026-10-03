"use client";

import { Kbd } from "@nova/ui";
import { Command } from "cmdk";
import { AnimatePresence, motion } from "framer-motion";
import {
  Boxes,
  FileStack,
  FileText,
  FolderKanban,
  Layers,
  ListTodo,
  MessageSquare,
  Orbit,
  Search,
  Sparkles,
  Telescope,
  CalendarRange,
} from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useProjects, useSearch } from "@/lib/api/hooks";
import { useComposer, useUi } from "@/stores/ui";

function Item({ icon: Icon, label, hint, onSelect }: { icon: typeof Search; label: string; hint?: string; onSelect: () => void }) {
  return (
    <Command.Item
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-3 rounded-[10px] px-3 py-2 text-[13.5px] text-muted data-[selected=true]:bg-surface-2 data-[selected=true]:text-text"
    >
      <Icon className="size-4 shrink-0 text-subtle" />
      <span className="truncate">{label}</span>
      {hint ? <span className="ml-auto truncate text-[11.5px] text-subtle">{hint}</span> : null}
    </Command.Item>
  );
}

function Group({ heading, children }: { heading: string; children: React.ReactNode }) {
  return (
    <Command.Group heading={heading} className="px-1.5 py-1 [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-[11px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-subtle">
      {children}
    </Command.Group>
  );
}

export function CommandPalette() {
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPaletteOpen);
  const setDraft = useComposer((s) => s.setDraft);
  const router = useRouter();
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const { data: projects } = useProjects();
  const { data: results } = useSearch(open ? query : "");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(!useUi.getState().paletteOpen);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [setOpen]);

  const run = (fn: () => void) => {
    setOpen(false);
    setQuery("");
    fn();
  };
  /** Prefill the composer with a Skill shortcut: the user completes the intent (no hidden execution). */
  const compose = (text: string) =>
    run(() => {
      setDraft(text);
      if (!(pathname === "/" || pathname.startsWith("/c/") || pathname.startsWith("/artifacts/"))) router.push("/");
      setTimeout(() => document.getElementById("nova-composer")?.focus(), 60);
    });

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/45 pt-[14vh] backdrop-blur-[2px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={() => setOpen(false)}
        >
          <motion.div
            initial={{ opacity: 0, y: -8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -8, scale: 0.98 }}
            transition={{ duration: 0.18, ease: "easeOut" }}
            className="w-[min(92vw,620px)] overflow-hidden rounded-[16px] border border-border-strong bg-surface shadow-panel"
            onClick={(e) => e.stopPropagation()}
          >
            <Command label="Command palette" shouldFilter={true} loop>
              <div className="flex items-center gap-3 border-b border-border px-4">
                <Search className="size-4 text-subtle" />
                <Command.Input
                  autoFocus
                  value={query}
                  onValueChange={setQuery}
                  placeholder="Ask NOVA, run a Skill, open a project…"
                  className="h-12 w-full bg-transparent text-[14.5px] outline-none placeholder:text-subtle"
                />
                <Kbd>esc</Kbd>
              </div>
              <Command.List className="max-h-[56vh] overflow-y-auto py-1.5">
                <Command.Empty className="px-4 py-6 text-center text-sm text-subtle">Nothing matches. Press Enter on “Ask NOVA”.</Command.Empty>
                <Group heading="Actions">
                  <Item icon={Sparkles} label={query ? `Ask NOVA: “${query}”` : "Ask NOVA"} onSelect={() => compose(query)} />
                  <Item icon={FileText} label="Create PRD" hint="/prd" onSelect={() => compose("/prd ")} />
                  <Item icon={Telescope} label="Start Discovery" hint="/problem-framing" onSelect={() => compose("/problem-framing ")} />
                  <Item icon={CalendarRange} label="Prepare Sprint" hint="/sprint-planning" onSelect={() => compose("/sprint-planning Prepare the next sprint")} />
                  <Item icon={Layers} label="Create User Stories" hint="/user-story-generation" onSelect={() => compose("/user-story-generation ")} />
                  <Item icon={ListTodo} label="View Active Work" onSelect={() => run(() => router.push("/work"))} />
                  <Item icon={FileStack} label="Search Artifacts" onSelect={() => run(() => router.push(`/artifacts${query ? `?q=${encodeURIComponent(query)}` : ""}`))} />
                  <Item icon={Orbit} label="Search Context" hint="ORBIT" onSelect={() => run(() => router.push(`/context${query ? `?q=${encodeURIComponent(query)}` : ""}`))} />
                </Group>
                {projects?.length ? (
                  <Group heading="Open project">
                    {projects.map((p) => (
                      <Item key={p.id} icon={FolderKanban} label={p.name} hint={p.description} onSelect={() => run(() => router.push(`/projects/${p.id}`))} />
                    ))}
                  </Group>
                ) : null}
                {results ? (
                  <>
                    {results.artifacts.length ? (
                      <Group heading="Artifacts">
                        {results.artifacts.map((a) => (
                          <Item key={a.id} icon={FileText} label={a.title} hint={a.type} onSelect={() => run(() => router.push(`/artifacts/${a.id}`))} />
                        ))}
                      </Group>
                    ) : null}
                    {results.conversations.length ? (
                      <Group heading="Conversations">
                        {results.conversations.map((c) => (
                          <Item key={c.id} icon={MessageSquare} label={c.title} onSelect={() => run(() => router.push(`/c/${c.id}`))} />
                        ))}
                      </Group>
                    ) : null}
                    {results.skills.length ? (
                      <Group heading="Skills">
                        {results.skills.map((s) => (
                          <Item key={s.id} icon={Boxes} label={s.name} hint={`/${s.id}`} onSelect={() => compose(`/${s.id} `)} />
                        ))}
                      </Group>
                    ) : null}
                    {results.context.length ? (
                      <Group heading="ORBIT context">
                        {results.context.map((c) => (
                          <Item key={c.ref_id} icon={Orbit} label={c.title} hint={c.source_kind ?? undefined} onSelect={() => run(() => router.push(`/context?q=${encodeURIComponent(query)}`))} />
                        ))}
                      </Group>
                    ) : null}
                  </>
                ) : null}
              </Command.List>
            </Command>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
