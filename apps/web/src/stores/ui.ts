"use client";

import { create } from "zustand";
import { persist } from "zustand/middleware";

import type { NovaPhase } from "@/lib/api/types";

interface UiState {
  sidebarCollapsed: boolean;
  paletteOpen: boolean;
  theme: "dark" | "light";
  toggleSidebar: () => void;
  setPaletteOpen: (open: boolean) => void;
  setTheme: (theme: "dark" | "light") => void;
}

export const useUi = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      paletteOpen: false,
      theme: "light",
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
      setTheme: (theme) => set({ theme }),
    }),
    { name: "nova-ui-v2", partialize: (s) => ({ sidebarCollapsed: s.sidebarCollapsed, theme: s.theme }) },
  ),
);

/** NOVA's visible state, aggregated from live execution streams. */
interface NovaState {
  running: Record<string, { phase: NovaPhase; label: string }>;
  setPhase: (taskId: string, phase: NovaPhase, label: string) => void;
  clear: (taskId: string) => void;
}

export const useNovaState = create<NovaState>((set) => ({
  running: {},
  setPhase: (taskId, phase, label) => set((s) => ({ running: { ...s.running, [taskId]: { phase, label } } })),
  clear: (taskId) =>
    set((s) => {
      const next = { ...s.running };
      delete next[taskId];
      return { running: next };
    }),
}));

/** Composer state shared by Today, conversations and the command palette. */
export interface ComposerContextRef { reference_id: string; label: string; count: number }

interface ComposerState {
  draft: string;
  projectId: string | null;
  contextMode: "auto" | "explicit" | "none";
  pinned: ComposerContextRef[];
  artifactRefs: { id: string; title: string }[];
  excluded: string[]; // context labels removed by the user for the next request
  setDraft: (draft: string) => void;
  setProject: (projectId: string | null) => void;
  setContextMode: (mode: "auto" | "explicit" | "none") => void;
  pin: (ref: ComposerContextRef) => void;
  unpin: (id: string) => void;
  addArtifactRef: (ref: { id: string; title: string }) => void;
  removeArtifactRef: (id: string) => void;
  exclude: (label: string) => void;
  include: (label: string) => void;
  reset: () => void;
}

export const useComposer = create<ComposerState>()(
  persist(
    (set) => ({
      draft: "",
      projectId: null,
      contextMode: "auto",
      pinned: [],
      artifactRefs: [],
      excluded: [],
      setDraft: (draft) => set({ draft }),
      setProject: (projectId) => set({ projectId }),
      setContextMode: (contextMode) => set({ contextMode }),
      pin: (ref) => set((s) => ({ pinned: [...s.pinned.filter((p) => p.reference_id !== ref.reference_id), ref] })),
      unpin: (id) => set((s) => ({ pinned: s.pinned.filter((p) => p.reference_id !== id) })),
      addArtifactRef: (ref) => set((s) => ({ artifactRefs: [...s.artifactRefs.filter((a) => a.id !== ref.id), ref] })),
      removeArtifactRef: (id) => set((s) => ({ artifactRefs: s.artifactRefs.filter((a) => a.id !== id) })),
      exclude: (label) => set((s) => ({ excluded: [...new Set([...s.excluded, label])] })),
      include: (label) => set((s) => ({ excluded: s.excluded.filter((l) => l !== label) })),
      reset: () => set({ draft: "", pinned: [], artifactRefs: [], excluded: [] }),
    }),
    { name: "nova-composer", partialize: (s) => ({ projectId: s.projectId, contextMode: s.contextMode }) },
  ),
);
