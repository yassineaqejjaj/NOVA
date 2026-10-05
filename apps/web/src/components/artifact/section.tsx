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
import type { ArtifactItem, ArtifactTypeDef, CommentInfo, SectionContent, SectionDefinition } from "@/lib/api/types";
import { timeAgo } from "@/lib/format";
import { defineMessages, useLang, useT } from "@/lib/i18n";
import { sectionDescription, sectionTitle } from "@/lib/i18n/catalog";
import { useComposer } from "@/stores/ui";

import { CitationChip, ItemsEditor } from "./items-editor";
import { RichTextEditor } from "./rich-text-editor";

const M = defineMessages({
  en: {
    improve: "Improve writing",
    improveInstruction: "Improve the writing of this section: clearer and more concise, keep the same facts and citations.",
    challenge: "Challenge assumptions",
    challengeInstruction: "Challenge the assumptions in this section: make weak assumptions, risks and open questions explicit.",
    evidence: "Add evidence",
    evidenceInstruction: "Strengthen this section with evidence from the project context and cite each source.",
    summarize: "Summarize",
    summarizeInstruction: "Summarize this section: keep only what matters, keep the citations.",
    draft: "Draft this section",
    draftInstruction: "Draft this section from the project context and the rest of the document.",
    updating: (v: { title: string }) => `NOVA is updating “${v.title}”.`,
    comment: "Comment",
    askNova: "Ask NOVA",
    custom: "Custom instruction…",
    askQuestion: "Ask a question about it",
    about: (v: { title: string }) => `About “${v.title}”: `,
    askToUpdate: (v: { title: string }) => `Ask NOVA to update “${v.title}”`,
    customPlaceholder: "e.g. make the metrics measurable",
    onlyThisSection: "Only this section changes. A new version is created.",
    run: "Run",
    resolve: "Resolve",
    addComment: "Add a comment",
  },
  fr: {
    improve: "Améliorer la rédaction",
    improveInstruction: "Améliore la rédaction de cette section : plus claire et plus concise, en conservant les mêmes faits et les mêmes citations.",
    challenge: "Remettre en question les hypothèses",
    challengeInstruction: "Remets en question les hypothèses de cette section : rends explicites les hypothèses fragiles, les risques et les questions ouvertes.",
    evidence: "Ajouter des preuves",
    evidenceInstruction: "Renforce cette section avec des éléments probants issus du contexte du projet et cite chaque source.",
    summarize: "Résumer",
    summarizeInstruction: "Résume cette section : ne garde que l’essentiel et conserve les citations.",
    draft: "Rédiger cette section",
    draftInstruction: "Rédige cette section à partir du contexte du projet et du reste du document.",
    updating: (v: { title: string }) => `NOVA met à jour « ${v.title} ».`,
    comment: "Commenter",
    askNova: "Demander à NOVA",
    custom: "Instruction personnalisée…",
    askQuestion: "Poser une question à ce sujet",
    about: (v: { title: string }) => `À propos de « ${v.title} » : `,
    askToUpdate: (v: { title: string }) => `Demander à NOVA de mettre à jour « ${v.title} »`,
    customPlaceholder: "ex. : rendre les indicateurs mesurables",
    onlyThisSection: "Seule cette section est modifiée. Une nouvelle version est créée.",
    run: "Lancer",
    resolve: "Résoudre",
    addComment: "Ajouter un commentaire",
  },
});

const ASK_ACTIONS = [
  { label: "improve", icon: PenLine, instruction: "improveInstruction" },
  { label: "challenge", icon: ShieldQuestion, instruction: "challengeInstruction" },
  { label: "evidence", icon: FileSearch, instruction: "evidenceInstruction" },
  { label: "summarize", icon: Text, instruction: "summarizeInstruction" },
] as const;
const DRAFT_ACTIONS = [{ label: "draft", icon: Sparkles, instruction: "draftInstruction" }] as const;

export function ArtifactSection({
  artifactId,
  artifactType,
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
  /** The Artifact type, for the localized section title and description. */
  artifactType?: ArtifactTypeDef;
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
  const t = useT(M);
  const lang = useLang();
  const title = sectionTitle(artifactType, definition, lang);
  const description = sectionDescription(artifactType, definition, lang);
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
      toast(t("updating", { title }));
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
            {title}
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
          <Tooltip content={t("comment")}>
            <Button variant="ghost" size="icon" className="size-7" onClick={() => setCommentsOpen(!commentsOpen)} aria-label={t("comment")}><MessageSquarePlus className="!size-3.5" /></Button>
          </Tooltip>
          {editable ? (
            <Popover open={regenOpen} onOpenChange={setRegenOpen}>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <PopoverAnchor asChild>
                    <button className="inline-flex h-7 items-center gap-1.5 rounded-full border border-accent/40 bg-accent-soft px-2.5 text-[12px] font-medium text-accent hover:bg-accent/15">
                      <NovaMark size={12} /> {t("askNova")}
                    </button>
                  </PopoverAnchor>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-56">
                  {(empty ? DRAFT_ACTIONS : ASK_ACTIONS).map((a) => (
                    <DropdownMenuItem key={a.label} onSelect={() => run(t(a.instruction))}>
                      <a.icon /> {t(a.label)}
                    </DropdownMenuItem>
                  ))}
                  <DropdownMenuItem onSelect={() => setTimeout(() => setRegenOpen(true), 0)}>
                    <Wand2 /> {t("custom")}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    onSelect={() => {
                      setDraft(t("about", { title }));
                      document.getElementById("nova-composer")?.focus();
                    }}
                  >
                    <MessageSquare /> {t("askQuestion")}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <PopoverContent align="end">
                <form onSubmit={(e) => { e.preventDefault(); run(instruction); }} className="space-y-2">
                  <div className="text-[13px] font-medium">{t("askToUpdate", { title })}</div>
                  <Textarea rows={3} value={instruction} onChange={(e) => setInstruction(e.target.value)} placeholder={t("customPlaceholder")} autoFocus />
                  <p className="text-[11.5px] text-subtle">{t("onlyThisSection")}</p>
                  <div className="flex justify-end"><Button type="submit" size="sm" variant="primary" disabled={regenerate.isPending}>{t("run")}</Button></div>
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
              {description && empty ? <p className="mb-1 text-[12.5px] text-subtle">{description}</p> : null}
              {content.kind === "rich_text" ? (
                <RichTextEditor
                  key={versionKey}
                  blocks={content.blocks}
                  editable={editable}
                  ariaLabel={title}
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
                      {!c.resolved ? <button onClick={() => resolve.mutate(c.id)} className="text-[11.5px] text-accent hover:underline">{t("resolve")}</button> : null}
                    </div>
                  ))}
                  <form onSubmit={(e) => { e.preventDefault(); if (comment.trim()) addComment.mutate(); }} className="flex gap-2">
                    <Textarea rows={1} value={comment} onChange={(e) => setComment(e.target.value)} placeholder={t("addComment")} className="min-h-0" />
                    <Button type="submit" size="sm" disabled={!comment.trim()}>{t("comment")}</Button>
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
