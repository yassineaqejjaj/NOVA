"use client";

import { Kbd } from "@nova/ui";
import { Command } from "cmdk";
import { AnimatePresence, motion } from "framer-motion";
import {
  Mic,
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

import { conversationTitle } from "@/components/conversation/blocks.messages";
import { useVoiceAvailable } from "@/components/voice/voice-button";
import { useArtifactTypes, useProjects, useSearch } from "@/lib/api/hooks";
import { defineMessages, useLang, useT } from "@/lib/i18n";
import { skillName, typeName } from "@/lib/i18n/catalog";

const M = defineMessages({
  en: {
    palette: "Command palette",
    placeholder: "Ask NOVA, run a Skill, open a project…",
    actions: "Actions",
    ask: "Ask NOVA",
    talk: "Talk with NOVA",
    askQuery: "Ask NOVA: “{query}”",
    createPrd: "Create PRD",
    discovery: "Start Discovery",
    sprint: "Prepare Sprint",
    sprintPrompt: "/sprint-planning Prepare the next sprint",
    stories: "Create User Stories",
    activeWork: "View Active Work",
    searchArtifacts: "Search Artifacts",
    searchContext: "Search Context",
    openProject: "Open project",
    artifacts: "Artifacts",
    conversations: "Conversations",
    skills: "Skills",
    orbitContext: "ORBIT context",
    empty: "Nothing matches. Press Enter on “Ask NOVA”.",
  },
  fr: {
    palette: "Palette de commandes",
    placeholder: "Demander à NOVA, lancer une compétence, ouvrir un projet…",
    actions: "Actions",
    ask: "Demander à NOVA",
    talk: "Parler avec NOVA",
    askQuery: "Demander à NOVA : « {query} »",
    createPrd: "Créer un PRD",
    discovery: "Lancer une phase de découverte",
    sprint: "Préparer le sprint",
    sprintPrompt: "/sprint-planning Prépare le prochain sprint",
    stories: "Créer des user stories",
    activeWork: "Voir le travail en cours",
    searchArtifacts: "Rechercher des Artefacts",
    searchContext: "Rechercher dans le contexte",
    openProject: "Ouvrir un projet",
    artifacts: "Artefacts",
    conversations: "Conversations",
    skills: "Compétences",
    orbitContext: "Contexte ORBIT",
    empty: "Aucun résultat. Appuyez sur Entrée sur « Demander à NOVA ».",
  },
});
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
  const t = useT(M);
  const lang = useLang();
  const voiceAvailable = useVoiceAvailable();
  const openVoice = useUi((s) => s.openVoice);
  const open = useUi((s) => s.paletteOpen);
  const setOpen = useUi((s) => s.setPaletteOpen);
  const setDraft = useComposer((s) => s.setDraft);
  const router = useRouter();
  const pathname = usePathname();
  const [query, setQuery] = useState("");
  const { data: projects } = useProjects();
  const { data: results } = useSearch(open ? query : "");
  const { data: types } = useArtifactTypes();

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
            <Command label={t("palette")} shouldFilter={true} loop>
              <div className="flex items-center gap-3 border-b border-border px-4">
                <Search className="size-4 text-subtle" />
                <Command.Input
                  autoFocus
                  value={query}
                  onValueChange={setQuery}
                  placeholder={t("placeholder")}
                  className="h-12 w-full bg-transparent text-[14.5px] outline-none placeholder:text-subtle"
                />
                <Kbd>esc</Kbd>
              </div>
              <Command.List className="max-h-[56vh] overflow-y-auto py-1.5">
                <Command.Empty className="px-4 py-6 text-center text-sm text-subtle">{t("empty")}</Command.Empty>
                <Group heading={t("actions")}>
                  <Item icon={Sparkles} label={query ? t("askQuery", { query }) : t("ask")} onSelect={() => compose(query)} />
                  {voiceAvailable ? <Item icon={Mic} label={t("talk")} onSelect={() => run(() => openVoice())} /> : null}
                  <Item icon={FileText} label={t("createPrd")} hint="/prd" onSelect={() => compose("/prd ")} />
                  <Item icon={Telescope} label={t("discovery")} hint="/problem-framing" onSelect={() => compose("/problem-framing ")} />
                  <Item icon={CalendarRange} label={t("sprint")} hint="/sprint-planning" onSelect={() => compose(t("sprintPrompt"))} />
                  <Item icon={Layers} label={t("stories")} hint="/user-story-generation" onSelect={() => compose("/user-story-generation ")} />
                  <Item icon={ListTodo} label={t("activeWork")} onSelect={() => run(() => router.push("/work"))} />
                  <Item icon={FileStack} label={t("searchArtifacts")} onSelect={() => run(() => router.push(`/artifacts${query ? `?q=${encodeURIComponent(query)}` : ""}`))} />
                  <Item icon={Orbit} label={t("searchContext")} hint="ORBIT" onSelect={() => run(() => router.push(`/context${query ? `?q=${encodeURIComponent(query)}` : ""}`))} />
                </Group>
                {projects?.length ? (
                  <Group heading={t("openProject")}>
                    {projects.map((p) => (
                      <Item key={p.id} icon={FolderKanban} label={p.name} hint={p.description} onSelect={() => run(() => router.push(`/projects/${p.id}`))} />
                    ))}
                  </Group>
                ) : null}
                {results ? (
                  <>
                    {results.artifacts.length ? (
                      <Group heading={t("artifacts")}>
                        {results.artifacts.map((a) => (
                          <Item key={a.id} icon={FileText} label={a.title} hint={typeName(types?.find((d) => d.type === a.type), lang, a.type)} onSelect={() => run(() => router.push(`/artifacts/${a.id}`))} />
                        ))}
                      </Group>
                    ) : null}
                    {results.conversations.length ? (
                      <Group heading={t("conversations")}>
                        {results.conversations.map((c) => (
                          <Item key={c.id} icon={MessageSquare} label={conversationTitle(c.title, lang)} onSelect={() => run(() => router.push(`/c/${c.id}`))} />
                        ))}
                      </Group>
                    ) : null}
                    {results.skills.length ? (
                      <Group heading={t("skills")}>
                        {results.skills.map((s) => (
                          <Item key={s.id} icon={Boxes} label={skillName(s, lang)} hint={`/${s.id}`} onSelect={() => compose(`/${s.id} `)} />
                        ))}
                      </Group>
                    ) : null}
                    {results.context.length ? (
                      <Group heading={t("orbitContext")}>
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
