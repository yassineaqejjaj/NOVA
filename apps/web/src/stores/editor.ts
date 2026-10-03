"use client";

import type { LexicalEditor } from "lexical";
import { create } from "zustand";

/** The Lexical editor that has focus (the document toolbar acts on it). */
export const useActiveEditor = create<{ editor: LexicalEditor | null; set: (editor: LexicalEditor | null) => void }>((set) => ({
  editor: null,
  set: (editor) => set({ editor }),
}));
