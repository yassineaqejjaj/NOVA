"use client";

import { INSERT_ORDERED_LIST_COMMAND, INSERT_UNORDERED_LIST_COMMAND, REMOVE_LIST_COMMAND } from "@lexical/list";
import { $createHeadingNode, $createQuoteNode } from "@lexical/rich-text";
import { $setBlocksType } from "@lexical/selection";
import { Tooltip, cn } from "@nova/ui";
import { $createParagraphNode, $getSelection, $isRangeSelection, REDO_COMMAND, UNDO_COMMAND } from "lexical";
import { Heading3, List, ListOrdered, Pilcrow, Quote, Redo2, Undo2 } from "lucide-react";

import { useActiveEditor } from "@/stores/editor";

/** Block formatting for the focused section (the Artifact block model has no inline styles, so none are offered). */
export function EditorToolbar({ disabled }: { disabled?: boolean }) {
  const editor = useActiveEditor((s) => s.editor);
  const off = disabled || !editor;
  const block = (create: () => ReturnType<typeof $createParagraphNode>) =>
    editor?.update(() => {
      const selection = $getSelection();
      if ($isRangeSelection(selection)) $setBlocksType(selection, create);
    });
  const items = [
    { label: "Paragraph", icon: Pilcrow, run: () => block(() => $createParagraphNode()) },
    { label: "Heading", icon: Heading3, run: () => block(() => $createHeadingNode("h3") as never) },
    { label: "Bulleted list", icon: List, run: () => editor?.dispatchCommand(INSERT_UNORDERED_LIST_COMMAND, undefined) },
    { label: "Numbered list", icon: ListOrdered, run: () => editor?.dispatchCommand(INSERT_ORDERED_LIST_COMMAND, undefined) },
    { label: "Quote", icon: Quote, run: () => block(() => $createQuoteNode() as never) },
  ];
  return (
    <div className="flex items-center gap-0.5 rounded-[12px] border border-border bg-surface px-1.5 py-1">
      {items.map(({ label, icon: Icon, run }) => (
        <Tooltip key={label} content={label}>
          <button
            disabled={off}
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              if (label !== "Bulleted list" && label !== "Numbered list") editor?.dispatchCommand(REMOVE_LIST_COMMAND, undefined);
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
      <button disabled={off} onMouseDown={(e) => e.preventDefault()} onClick={() => editor?.dispatchCommand(UNDO_COMMAND, undefined)} className="rounded-md p-1.5 text-muted hover:bg-surface-2 disabled:opacity-40" aria-label="Undo"><Undo2 className="size-4" /></button>
      <button disabled={off} onMouseDown={(e) => e.preventDefault()} onClick={() => editor?.dispatchCommand(REDO_COMMAND, undefined)} className="rounded-md p-1.5 text-muted hover:bg-surface-2 disabled:opacity-40" aria-label="Redo"><Redo2 className="size-4" /></button>
      <span className="ml-2 hidden text-[11.5px] text-subtle lg:inline">{editor ? "Formatting the focused section" : "Click in a section to format it"}</span>
    </div>
  );
}
