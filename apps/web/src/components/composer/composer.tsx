"use client";

import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Select,
  Tooltip,
} from "@nova/ui";
import { ArrowUp, FileText, Orbit, Paperclip, Plus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { useArtifacts, useProjects, useSendIntent, useSkills } from "@/lib/api/hooks";
import { useComposer } from "@/stores/ui";

import { NovaMark } from "@/components/shell/nova-mark";

import { ContextPicker } from "./context-picker";

const TEXT_TYPES = [".txt", ".md", ".csv", ".json", ".yaml", ".yml"];
const MAX_ATTACHMENT_CHARS = 20_000;

export interface ComposerProps {
  conversationId?: string | null;
  activeArtifactId?: string | null;
  placeholder?: string;
  autoFocus?: boolean;
  compact?: boolean;
  disabled?: boolean;
  /** "pill": floating home composer (orb, single line; controls appear when focused). */
  variant?: "default" | "pill";
}

export function Composer({ conversationId, activeArtifactId, placeholder, autoFocus, compact, disabled, variant = "default" }: ComposerProps) {
  const [focused, setFocused] = useState(false);
  const router = useRouter();
  const send = useSendIntent();
  const { data: projects } = useProjects();
  const { data: skills } = useSkills();
  const state = useComposer();
  const [attachments, setAttachments] = useState<{ name: string; text: string }[]>([]);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [artifactMenu, setArtifactMenu] = useState(false);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const root = useRef<HTMLDivElement>(null);
  // Menus open below the composer; they flip above only when there is not enough room below.
  const [menuAbove, setMenuAbove] = useState(false);
  const placeMenu = () => {
    const rect = root.current?.getBoundingClientRect();
    if (rect) setMenuAbove(window.innerHeight - rect.bottom < 300 && rect.top > window.innerHeight - rect.bottom);
  };
  const fileInput = useRef<HTMLInputElement>(null);
  const { data: recentArtifacts } = useArtifacts({ project_id: state.projectId ?? undefined }, artifactMenu);

  // Autosize
  useEffect(() => {
    const el = textarea.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 260)}px`;
  }, [state.draft]);

  // Slash command suggestions on the word being typed
  const slash = useMemo(() => {
    const match = /(?:^|\s)\/([a-z0-9-]*)$/.exec(state.draft);
    if (!match || !skills) return [];
    const q = match[1] ?? "";
    return skills.filter((s) => s.id.includes(q) || s.name.toLowerCase().includes(q)).slice(0, 6);
  }, [state.draft, skills]);
  const [slashIndex, setSlashIndex] = useState(0);
  useEffect(() => setSlashIndex(0), [slash.length]);
  useEffect(() => {
    if (slash.length || artifactMenu) placeMenu();
  }, [slash.length, artifactMenu]);

  const insertSkill = (id: string) => {
    state.setDraft(state.draft.replace(/\/([a-z0-9-]*)$/, `/${id} `));
    textarea.current?.focus();
  };

  const submit = async () => {
    const text = state.draft.trim();
    if (!text || send.isPending || disabled) return;
    const result = await send.mutateAsync({
      conversationId,
      payload: {
        text,
        project_id: state.projectId,
        context_mode: state.contextMode,
        pinned_context_ref_ids: state.pinned.map((p) => p.reference_id),
        excluded_context_refs: state.excluded,
        artifact_refs: state.artifactRefs.map((a) => a.id),
        active_artifact_id: activeArtifactId ?? null,
        attachments,
      },
    });
    state.reset();
    setAttachments([]);
    if (result.conversation.id !== conversationId) router.push(`/c/${result.conversation.id}`);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (slash.length) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        setSlashIndex((i) => (i + (e.key === "ArrowDown" ? 1 : slash.length - 1)) % slash.length);
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        insertSkill(slash[slashIndex]!.id);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };

  const onFiles = async (files: FileList | null) => {
    for (const file of Array.from(files ?? [])) {
      if (!TEXT_TYPES.some((ext) => file.name.toLowerCase().endsWith(ext))) {
        toast.error(`${file.name}: only text files (${TEXT_TYPES.join(", ")}) can be attached. Add documents to ORBIT to use them as context.`);
        continue;
      }
      const text = (await file.text()).slice(0, MAX_ATTACHMENT_CHARS);
      setAttachments((prev) => [...prev.filter((a) => a.name !== file.name), { name: file.name, text }].slice(0, 5));
    }
  };

  const projectOptions = [{ value: "none", label: "No project" }, ...(projects ?? []).map((p) => ({ value: p.id, label: p.name }))];
  const chips = state.pinned.length + state.artifactRefs.length + attachments.length + state.excluded.length;

  return (
    <div
      ref={root}
      onFocus={() => setFocused(true)}
      onBlur={(e) => {
        const next = e.relatedTarget as HTMLElement | null;
        // Menus of the composer's own controls (project, context) render in a portal: stay expanded.
        if (!e.currentTarget.contains(next) && !next?.closest("[data-radix-popper-content-wrapper]")) setFocused(false);
      }}
      className={cn(
        "relative border border-border-strong bg-surface shadow-panel transition-colors focus-within:border-accent/40",
        variant === "pill" ? "rounded-[26px]" : "rounded-[16px]",
      )}
    >
      {slash.length ? (
        <div role="listbox" aria-label="Skills" className={cn("absolute left-3 z-30 w-[min(100%,420px)] overflow-hidden rounded-[12px] border border-border-strong bg-surface p-1 shadow-panel", menuAbove ? "bottom-full mb-2" : "top-full mt-2")}>
          {slash.map((s, i) => (
            <button
              key={s.id}
              role="option"
              aria-selected={i === slashIndex}
              onMouseDown={(e) => {
                e.preventDefault();
                insertSkill(s.id);
              }}
              className={cn("flex w-full flex-col rounded-[8px] px-2.5 py-1.5 text-left", i === slashIndex ? "bg-surface-2" : "")}
            >
              <span className="text-[13px] text-text">
                /{s.id} <span className="text-subtle">· {s.name}</span>
              </span>
              <span className="truncate text-[11.5px] text-subtle">{s.summary}</span>
            </button>
          ))}
        </div>
      ) : null}

      {chips ? (
        <div className="flex flex-wrap gap-1.5 px-3 pt-3">
          {state.pinned.map((p) => (
            <Chip key={p.reference_id} icon={<Orbit className="size-3" />} label={`${p.label} · ${p.count}`} onRemove={() => state.unpin(p.reference_id)} />
          ))}
          {state.artifactRefs.map((a) => (
            <Chip key={a.id} icon={<FileText className="size-3" />} label={a.title} onRemove={() => state.removeArtifactRef(a.id)} />
          ))}
          {state.excluded.map((label) => (
            <Chip key={label} icon={<X className="size-3" />} label={`Excluding ${label}`} onRemove={() => state.include(label)} />
          ))}
          {attachments.map((a) => (
            <Chip key={a.name} icon={<Paperclip className="size-3" />} label={a.name} onRemove={() => setAttachments((prev) => prev.filter((x) => x.name !== a.name))} />
          ))}
        </div>
      ) : null}

      {variant === "pill" ? (
        <div className="flex items-center gap-3 pl-3 pr-2">
          <NovaMark size={30} />
          <textarea
            id="nova-composer"
            ref={textarea}
            value={state.draft}
            onChange={(e) => state.setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            autoFocus={autoFocus}
            disabled={disabled}
            rows={1}
            aria-label="Ask NOVA"
            placeholder={placeholder ?? "Ask NOVA anything about your product work…"}
            className={cn(
              "block w-full resize-none bg-transparent px-4 text-[15px] leading-relaxed text-text outline-none placeholder:text-subtle",
              "min-h-[52px] flex-1 px-0 py-[14px]",
            )}
          />
          <Button variant="primary" size="icon" className="size-9 shrink-0 rounded-full" onClick={() => void submit()} disabled={!state.draft.trim() || send.isPending || disabled} aria-label="Send">
            <ArrowUp />
          </Button>
        </div>
      ) : (
        <textarea
          id="nova-composer"
          ref={textarea}
          value={state.draft}
          onChange={(e) => state.setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          autoFocus={autoFocus}
          disabled={disabled}
          rows={1}
          aria-label="Ask NOVA"
          placeholder={placeholder ?? "Ask NOVA anything about your product work…"}
          className={cn(
            "block w-full resize-none bg-transparent px-4 text-[15px] leading-relaxed text-text outline-none placeholder:text-subtle",
            compact ? "min-h-[48px] py-3" : "min-h-[64px] py-4",
          )}
        />
      )}

      <div className={cn("flex flex-wrap items-center gap-1.5 px-2.5 pb-2.5", variant === "pill" && !(focused || state.draft || chips) && "hidden")}>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label="Add">
              <Plus />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onSelect={() => fileInput.current?.click()}>
              <Paperclip /> Attach a text file
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setPickerOpen(true)} disabled={!state.projectId}>
              <Orbit /> Add ORBIT context{state.projectId ? "" : " (choose a project)"}
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => setArtifactMenu(true)}>
              <FileText /> Reference an Artifact
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
        <input ref={fileInput} type="file" multiple hidden accept={TEXT_TYPES.join(",")} onChange={(e) => void onFiles(e.target.files)} />

        <Select
          ariaLabel="Project"
          value={state.projectId ?? "none"}
          onValueChange={(v) => state.setProject(v === "none" ? null : v)}
          options={projectOptions}
          className="h-8 max-w-[200px] border-transparent bg-transparent px-2 text-[12.5px] text-muted hover:bg-surface-2 [&>span]:truncate"
        />
        <Tooltip content="Auto: NOVA decides what to request from ORBIT. Explicit: only the context you add. None: no project context.">
          <span>
            <Select
              ariaLabel="Context"
              value={state.contextMode}
              onValueChange={(v) => state.setContextMode(v as "auto" | "explicit" | "none")}
              options={[
                { value: "auto", label: "Context: Auto" },
                { value: "explicit", label: "Context: Explicit" },
                { value: "none", label: "Context: None" },
              ]}
              className="h-8 border-transparent bg-transparent px-2 text-[12.5px] text-muted hover:bg-surface-2 [&>span]:whitespace-nowrap"
            />
          </span>
        </Tooltip>

        <div className="ml-auto flex items-center gap-2">
          <span className="hidden whitespace-nowrap text-[11px] text-subtle xl:inline">/ for Skills · ⇧↵ new line</span>
          {variant === "pill" ? null : (
            <Button variant="primary" size="icon" onClick={() => void submit()} disabled={!state.draft.trim() || send.isPending || disabled} aria-label="Send">
              <ArrowUp />
            </Button>
          )}
        </div>
      </div>

      <ContextPicker open={pickerOpen} onOpenChange={setPickerOpen} projectId={state.projectId} onPin={(ref) => state.pin(ref)} />
      {artifactMenu ? (
        <div className={cn("absolute left-3 z-30 w-[min(100%,420px)] rounded-[12px] border border-border-strong bg-surface p-1 shadow-panel", menuAbove ? "bottom-full mb-2" : "top-full mt-2")}>
          <div className="flex items-center justify-between px-2.5 py-1.5 text-[11px] uppercase tracking-wider text-subtle">
            Reference an Artifact
            <button onClick={() => setArtifactMenu(false)} aria-label="Close">
              <X className="size-3.5" />
            </button>
          </div>
          {(recentArtifacts ?? []).slice(0, 8).map((a) => (
            <button
              key={a.id}
              onClick={() => {
                state.addArtifactRef({ id: a.id, title: a.title });
                setArtifactMenu(false);
              }}
              className="flex w-full items-center gap-2 rounded-[8px] px-2.5 py-1.5 text-left text-[13px] text-muted hover:bg-surface-2 hover:text-text"
            >
              <FileText className="size-3.5" /> <span className="truncate">{a.title}</span>
            </button>
          ))}
          {recentArtifacts && recentArtifacts.length === 0 ? <div className="px-2.5 py-2 text-[13px] text-subtle">No Artifacts yet.</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function Chip({ icon, label, onRemove }: { icon: React.ReactNode; label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex max-w-[260px] items-center gap-1.5 rounded-lg border border-border bg-surface-2 px-2 py-1 text-[12px] text-muted">
      {icon}
      <span className="truncate">{label}</span>
      <button onClick={onRemove} className="text-subtle hover:text-text" aria-label={`Remove ${label}`}>
        <X className="size-3" />
      </button>
    </span>
  );
}
