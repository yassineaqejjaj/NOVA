"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

/** Time Machine: replay a finished run with another context, model or lessons and compare (`/api/v1/executions`). */

export interface ReplayOptionsView {
  models: string[];
  policies: { id: string; agent: string; version: number; status: "active" | "retired"; lessons: number }[];
}

export interface ReplayRow {
  id: string;
  status: string;
  overrides: Record<string, string>;
  model: string | null;
  error: string | null;
}

export interface ReplayRequest {
  context: "original" | "live" | "none";
  model?: string;
  learning_policy_id?: string;
}

export interface RunSide {
  id: string;
  status: string;
  error: string | null;
  model: string | null;
  tokens: number | null;
  duration_seconds: number | null;
  context_items: number | null;
  context_sufficiency: string | null;
  snapshot: string | null;
  policies: Record<string, number>;
  overrides: Record<string, string>;
}

export interface SectionChange {
  key: string;
  status: "added" | "removed" | "changed";
  before: string;
  after: string;
  added_items: number;
  removed_items: number;
  changed_items: number;
}

export interface Comparison {
  original: RunSide;
  replay: RunSide;
  delta: { tokens: number | null; duration: number | null; context_items: number | null };
  artifacts: {
    type: string;
    title: string;
    original_id: string | null;
    replay_id: string | null;
    words: { original: number; replay: number };
    sections: SectionChange[];
  }[];
  sections_changed: number;
}

const OPEN = ["queued", "running", "waiting_user"];

export const useReplayOptions = () =>
  useQuery({ queryKey: ["replay-options"], queryFn: () => api.get<ReplayOptionsView>("/executions/replay/options"), staleTime: 60_000 });

export const useReplays = (taskId: string | null) =>
  useQuery({
    queryKey: ["replays", taskId],
    queryFn: () => api.get<ReplayRow[]>(`/executions/${taskId}/replays`),
    enabled: !!taskId,
    refetchInterval: (q) => (q.state.data?.some((r) => OPEN.includes(r.status)) ? 3_000 : false),
  });

export const useComparison = (taskId: string | null, replayId: string | null, ready: boolean) =>
  useQuery({
    queryKey: ["replay-compare", taskId, replayId],
    queryFn: () => api.get<Comparison>(`/executions/${taskId}/compare/${replayId}`),
    enabled: !!taskId && !!replayId && ready,
  });

export function useStartReplay(taskId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ReplayRequest) => api.post<{ id: string }>(`/executions/${taskId}/replay`, body),
    onSettled: () => qc.invalidateQueries({ queryKey: ["replays", taskId] }),
  });
}

export const isOpenReplay = (status: string) => OPEN.includes(status);
