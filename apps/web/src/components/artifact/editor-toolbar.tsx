"use client";

import { INSERT_ORDERED_LIST_COMMAND, INSERT_UNORDERED_LIST_COMMAND, REMOVE_LIST_COMMAND } from "@lexical/list";
import { $createHeadingNode, $createQuoteNode } from "@lexical/rich-text";
import { $setBlocksType } from "@lexical/selection";
import { Tooltip, cn } from "@nova/ui";
import { $createParagraphNode, $getSelection, $isRangeSelection, REDO_COMMAND, UNDO_COMMAND } from "lexical";
import { Heading3, List, ListOrdered, Pilcrow, Quote, Redo2, Undo2 } from "lucide-react";

import { defineMessages, useT } from "@/lib/i18n";
import { useActiveEditor } from "@/stores/editor";

const M = defineMessages({
  en: {
    paragraph: "Paragraph",
    heading: "Heading",
    bulleted: "Bulleted list",
    numbered: "Numbered list",
    quote: "Quote",
    undo: "Undo",
    redo: "Redo",
    focused: "Formatting the focused section",
    clickToFormat: "Click in a section to format it",
  },
  fr: {
    paragraph: "Paragraphe",
    heading: "Titre",
    bulleted: "Liste à puces",
    numbered: "Liste numérotée",
    quote: "Citation",
    undo: "Annuler",
    redo: "Rétablir",
    focused: "Mise en forme de la section active",
    clickToFormat: "Cliquez dans une section pour la mettre en forme",
  },
});

/** Block formatting for the focused section (the Artifact block model has no inline styles, so none are offered). */
export function EditorToolbar({ disabled }: { disabled?: boolean }) {
  const t = useT(M);
  const editor = useActiveEditor((s) => s.editor);
  const off = disabled || !editor;
  const block = (create: () => ReturnType<typeof $createParagraphNode>) =>
    editor?.update(() => {
      const selection = $getSelection();
      if ($isRangeSelection(selection)) $setBlocksType(selection, create);
    });
  const items = [
    { label: t("paragraph"), icon: Pilcrow, run: () => block(() => $createParagraphNode()) },
    { label: t("heading"), icon: Heading3, run: () => block(() => $createHeadingNode("h3") as never) },
    { label: t("bulleted"), icon: List, list: true, run: () => editor?.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined) },
    { label: t("numbered"), icon: ListOrdered, list: true, run: () => editor?.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined) },
    { label: t("quote"), icon: Quote, run: () => block(() => $createQuoteNode() as never) },
  ];
  return (
    <div className="flex items-center gap-0.5 rounded-[12px] border border-border bg-surface px-1.5 py-1">
      {items.map(({ label, icon: Icon, list, run }) => (
        <Tooltip key={label} content={label}>
          <button
            disabled={off}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              if (!list) editor?.dispatchCommand(REMOVE_LIST_COMMAND, undefined);
              run();
            }}
            className={cn("rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-text disabled:opacity-40")}
            aria-label={label}
          >
            <Icon className="size-4" />
          </button>
        </Tooltip>
      ))}
      <span className="mx-1 h-4 w-px bg-border" />
      <button disabled={off} onMouseDown={(e) => e.preventDefault()} onClick={() => editor?.dispatchCommand(UNDO_COMMAND, undefined)} className="rounded-md p-1.5 text-muted hover:bg-surface-2 disabled:opacity-40" aria-label={t("undo")}><Undo2 className="size-4" /></button>
      <button disabled={off} onMouseDown={(e) => e.preventDefault()} onClick={() => editor?.dispatchCommand(REDO_COMMAND, undefined)} className="rounded-md p-1.5 text-muted hover:bg-surface-2 disabled:opacity-40" aria-label={t("redo")}><Redo2 className="size-4" /></button>
      <span className="ml-2 hidden text-[11.5px] text-subtle lg:inline">{editor ? t("focused") : t("clickToFormat")}</span>
    </div>
  );
}
