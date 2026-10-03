"use client";

import { $createListItemNode, $createListNode, $isListItemNode, $isListNode, ListItemNode, ListNode } from "@lexical/list";
import { HEADING, ORDERED_LIST, QUOTE, UNORDERED_LIST } from "@lexical/markdown";
import { LexicalComposer } from "@lexical/react/LexicalComposer";
import { ContentEditable } from "@lexical/react/LexicalContentEditable";
import { LexicalErrorBoundary } from "@lexical/react/LexicalErrorBoundary";
import { HistoryPlugin } from "@lexical/react/LexicalHistoryPlugin";
import { ListPlugin } from "@lexical/react/LexicalListPlugin";
import { MarkdownShortcutPlugin } from "@lexical/react/LexicalMarkdownShortcutPlugin";
import { OnChangePlugin } from "@lexical/react/LexicalOnChangePlugin";
import { RichTextPlugin } from "@lexical/react/LexicalRichTextPlugin";
import { $createHeadingNode, $createQuoteNode, $isHeadingNode, $isQuoteNode, HeadingNode, QuoteNode } from "@lexical/rich-text";
import { $createParagraphNode, $createTextNode, $getRoot, type EditorState, type LexicalNode } from "lexical";
import { useLexicalComposerContext } from "@lexical/react/LexicalComposerContext";
import { useEffect, useMemo, useRef } from "react";

import { useActiveEditor } from "@/stores/editor";

/** Registers the focused section editor so the document toolbar can format it. */
function FocusTracker() {
  const [editor] = useLexicalComposerContext();
  const set = useActiveEditor((s) => s.set);
  useEffect(() => {
    const root = editor.getRootElement();
    if (!root) return;
    const onFocus = () => set(editor);
    root.addEventListener("focus", onFocus);
    return () => root.removeEventListener("focus", onFocus);
  }, [editor, set]);
  return null;
}

import type { TextBlock } from "@/lib/api/types";

const TRANSFORMERS = [HEADING, QUOTE, UNORDERED_LIST, ORDERED_LIST];

/** NOVA blocks → Lexical nodes (consecutive list blocks become one list). */
function populate(blocks: TextBlock[]) {
  const root = $getRoot();
  root.clear();
  let list: ListNode | null = null;
  let listType: "bullet" | "number" | null = null;
  for (const block of blocks) {
    if (block.type === "bullet" || block.type === "numbered") {
      const type = block.type === "bullet" ? "bullet" : "number";
      if (!list || listType !== type) {
        list = $createListNode(type);
        listType = type;
        root.append(list);
      }
      list.append($createListItemNode().append($createTextNode(block.text)));
      continue;
    }
    list = null;
    listType = null;
    const node = block.type === "heading" ? $createHeadingNode("h3") : block.type === "quote" ? $createQuoteNode() : $createParagraphNode();
    root.append(node.append($createTextNode(block.text)));
  }
  if (root.getChildrenSize() === 0) root.append($createParagraphNode());
}

/** Lexical state → NOVA blocks. Citations survive when the text (or the position and type) is unchanged. */
export function toBlocks(state: EditorState, previous: TextBlock[]): TextBlock[] {
  const byText = new Map(previous.map((b) => [b.text.trim(), b.citations]));
  const blocks: TextBlock[] = [];
  state.read(() => {
    const push = (type: TextBlock["type"], node: LexicalNode) => {
      const text = node.getTextContent().trim();
      if (!text) return;
      const atIndex = previous[blocks.length];
      const citations = byText.get(text) ?? (atIndex && atIndex.type === type ? atIndex.citations : []);
      blocks.push({ type, text, citations: citations ?? [] });
    };
    for (const child of $getRoot().getChildren()) {
      if ($isListNode(child)) {
        const type = child.getListType() === "number" ? "numbered" : "bullet";
        for (const item of child.getChildren()) if ($isListItemNode(item)) push(type, item);
      } else if ($isHeadingNode(child)) push("heading", child);
      else if ($isQuoteNode(child)) push("quote", child);
      else push("paragraph", child);
    }
  });
  return blocks;
}

export function RichTextEditor({
  blocks,
  editable,
  onChange,
  placeholder,
  ariaLabel,
}: {
  blocks: TextBlock[];
  editable: boolean;
  onChange: (blocks: TextBlock[]) => void;
  placeholder?: string;
  ariaLabel: string;
}) {
  const previous = useRef(blocks);
  previous.current = blocks;
  const initialConfig = useMemo(
    () => ({
      namespace: "nova-artifact",
      editable,
      nodes: [HeadingNode, QuoteNode, ListNode, ListItemNode],
      onError: (error: Error) => console.error(error),
      editorState: () => populate(blocks),
      theme: { paragraph: "", heading: { h3: "" }, list: { ul: "", ol: "" }, quote: "" },
    }),
    // The editor is keyed by section + version by the parent; content resets on new versions.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );
  return (
    <LexicalComposer initialConfig={initialConfig}>
      <div className="relative">
        <RichTextPlugin
          contentEditable={
            <ContentEditable
              aria-label={ariaLabel}
              className="nova-editor min-h-[28px] text-[14.5px] leading-relaxed text-text outline-none"
            />
          }
          placeholder={<div className="pointer-events-none absolute left-0 top-0 text-[14.5px] text-subtle">{placeholder ?? "Write, or ask NOVA to draft this section…"}</div>}
          ErrorBoundary={LexicalErrorBoundary}
        />
        <HistoryPlugin />
        <FocusTracker />
        <ListPlugin />
        <MarkdownShortcutPlugin transformers={TRANSFORMERS} />
        <OnChangePlugin ignoreSelectionChange onChange={(state) => onChange(toBlocks(state, previous.current))} />
      </div>
    </LexicalComposer>
  );
}
