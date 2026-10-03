"use client";

import {
  Button,
  cn,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Popover,
  PopoverAnchor,
  PopoverContent,
  Textarea,
  Tooltip,
} from "@nova/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronRight, FileSearch, MessageSquare, MessageSquarePlus, PenLine, ShieldQuestion, Sparkles, Text, Wand2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { NovaMark } from "@/components/shell/nova-mark";
import { api } from "@/lib/api/client";
import { keys } from "@/lib/api/hooks";
import type { ArtifactItem, CommentInfo, SectionContent, SectionDefinition } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";
import { useComposer } from "@/stores/ui";

import { CitationChip, ItemsEditor } from "./items-editor";
import { RichTextEditor } from "./rich-text-editor";

const ASK_ACTIONS = [
  { label: "Improve writing", icon: PenLine, instruction: "Improve the writing of this section: clearer and more concise, keep the same facts and citations." },
  { label: "Challenge assumptions", icon: ShieldQuestion, instruction: "Challenge the assumptions in this section: make weak assumptions, risks and open questions explicit." },
  { label: "Add evidence", icon: FileSearch, instruction: "Strengthen this section with evidence from the project context and cite each source." },
  { label: "Summarize", icon: Text, instruction: "Summarize this section: keep only what matters, keep the citations." },
];
const DRAFT_ACTIONS = [{ label: "Draft this section", icon: Sparkles, instruction: "Draft this section from the project context and the rest of the document." }];

export function ArtifactSection({
  artifactId,
  definition,
  content,
  editable,
  allItems,
  comments,
  versionKey,
  onChange,
  conversationId,
  number,
}: {
  artifactId: string;
  definition: SectionDefinition;
  content: SectionContent;
  editable: boolean;
  allItems: ArtifactItem[];
  comments: CommentInfo[];
  versionKey: string;
  onChange: (section: SectionContent) => void;
  conversationId: string | null;
  number?: number;
}) {
  const [open, setOpen] = useState(true);
  const [regenOpen, setRegenOpen] = useState(false);
  const [instruction, setInstruction] = useState("");
  const [commentsOpen, setCommentsOpen] = useState(false);
  const [comment, setComment] = useState("");
  const client = useQueryClient();
  const router = useRouter();
  const setDraft = useComposer((s) => s.setDraft);
  const empty = content.kind === "rich_text" ? content.blocks.length === 0 : content.items.length === 0;
  const open_comments = comments.filter((c) => !c.resolved);

  const regenerate = useMutation({
    mutationFn: (text: string) =>
      api.post<{ task_id: string; conversation_id: string }>(`/artifacts/${artifactId}/sections/${definition.key}/regenerate`, { instruction: text }),
    onSuccess: (result) => {
      setRegenOpen(false);
      setInstruction("");
      toast(`NOVA is updating “${definition.title}”.`);
      void client.invalidateQueries({ queryKey: ["conversation"] });
      if (result.conversation_id !== conversationId) router.push(`/c/${result.conversation_id}?artifact=${artifactId}`);
    },
  });
  const run = (text: string) => regenerate.mutate(text);
  const addComment = useMutation({
    mutationFn: () => api.post(`/artifacts/${artifactId}/comments`, { section_key: definition.key, body: comment }),
    onSuccess: () => {
      setComment("");
      void client.invalidateQueries({ queryKey: keys.artifactComments(artifactId) });
    },
  });
  const resolve = useMutation({
    mutationFn: (id: string) => api.post(`/artifacts/${artifactId}/comments/${id}/resolve`),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.artifactComments(artifactId) }),
  });

  const blockCitations = content.kind === "rich_text" ? content.blocks.flatMap((b) => b.citations) : [];
  const uniqueCitations = blockCitations.filter((c, i) => blockCitations.findIndex((x) => x.label === c.label && x.ref === c.ref) === i);

  return (
    <section id={`section-${definition.key}`} className="group/section scroll-mt-20 border-b border-border py-4 last:border-b-0">
      <header className="flex items-center gap-2">
        <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 text-left" aria-expanded={open}>
          <ChevronRight className={cn("size-4 text-subtle transition-transform", open && "rotate-90")} />
          <h3 className={cn("text-[15px] font-semibold tracking-tight", empty && "text-muted")}>
            {number ? `${number}. ` : ""}
            {definition.title}
          </h3>
        </button>
        {uniqueCitations.length ? (
          <span className="flex gap-1">
            {uniqueCitations.map((c) => <CitationChip key={`${c.label}-${c.ref}`} citation={c} artifactId={artifactId} section={definition.key} />)}
          </span>
        ) : null}
        <div className="ml-auto flex items-center gap-0.5 opacity-60 transition-opacity group-hover/section:opacity-100">
          {open_comments.length ? (
            <Button variant="ghost" size="sm" className="h-7 text-[12px]" onClick={() => setCommentsOpen(!commentsOpen)}>
              <MessageSquare /> {open_comments.length}
            </Button>
          ) : null}
          <Tooltip content="Comment">
            <Button variant="ghost" size="icon" className="size-7" onClick={() => setCommentsOpen(!commentsOpen)} aria-label="Comment"><MessageSquarePlus className="!size-3.5" /></Button>
          </Tooltip>
          {editable ? (
            <Popover open={regenOpen} onOpenChange={setRegenOpen}>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <PopoverAnchor asChild>
                    <button className="inline-flex h-7 items-center gap-1.5 rounded-full border border-accent/40 bg-accent-soft px-2.5 text-[12px] font-medium text-accent hover:bg-accent/15">
                      <NovaMark size={12} /> Ask NOVA
                    </button>
                  </PopoverAnchor>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  {(empty ? DRAFT_ACTIONS : ASK_ACTIONS).map((a) => (
                    <DropdownMenuItem key={a.label} onSelect={() => run(a.instruction)}>
                      <a.icon /> {a.label}
                    </DropdownMenuItem>
                  ))}
                  <DropdownMenuItem onSelect={() => setTimeout(() => setRegenOpen(true), 0)}>
                    <Wand2 /> Custom instruction…
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => {
                      setDraft(`About “${definition.title}”: `);
                      document.getElementById("nova-composer")?.focus();
                    }}
                  >
                    <MessageSquare /> Ask a question about it
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <PopoverContent align="end">
                <form onSubmit={(e) => { e.preventDefault(); run(instruction); }} className="space-y-2">
                  <div className="text-[13px] font-medium">Ask NOVA to update “{definition.title}”</div>
                  <Textarea rows={3} value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder="e.g. make the metrics measurable" autoFocus />
                  <p className="text-[11.5px] text-subtle">Only this section changes. A new version is created.</p>
                  <div className="flex justify-end"><Button type="submit" size="sm" variant="primary" disabled={regenerate.isPending}>Run</Button></div>
                </form>
              </PopoverContent>
            </Popover>
          ) : null}
        </div>
      </header>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.2 }} className="overflow-hidden">
            <div className="pl-6 pt-2">
              {definition.description && empty ? <p className="mb-1 text-[12.5px] text-subtle">{definition.description}</p> : null}
              {content.kind === "rich_text" ? (
                <RichTextEditor
                  key={versionKey}
                  blocks={content.blocks}
                  editable={editable}
                  ariaLabel={definition.title}
                  onChange={(blocks) => onChange({ ...content, blocks })}
                />
              ) : (
                <ItemsEditor items={content.items} itemKind={definition.item_kind ?? "note"} editable={editable} allItems={allItems} artifactId={artifactId} onChange={(items) => onChange({ ...content, items })} />
              )}
              {commentsOpen ? (
                <div className="mt-3 space-y-2 rounded-[10px] border border-border bg-surface-2/60 p-3">
                  {comments.map((c) => (
                    <div key={c.id} className={cn("text-[13px]", c.resolved && "opacity-50")}>
                      <span className="font-medium">{c.author_name}</span> <span className="text-[11.5px] text-subtle">{timeAgo(c.created_at)}</span>
                      <p className="text-muted">{c.body}</p>
                      {!c.resolved ? <button onClick={() => resolve.mutate(c.id)} className="text-[11.5px] text-accent hover:underline">Resolve</button> : null}
                    </div>
                  ))}
                  <form onSubmit={(e) => { e.preventDefault(); if (comment.trim()) addComment.mutate(); }} className="flex gap-2">
                    <Textarea rows={1} value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Add a comment" className="min-h-0" />
                    <Button type="submit" size="sm" disabled={!comment.trim()}>Comment</Button>
                  </form>
                </div>
              ) : null}
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </section>
  );
}
