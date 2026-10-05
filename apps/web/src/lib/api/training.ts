"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { AgentProfile } from "@/lib/agents";

import { api } from "./client";

/** FORGE training loop of the specialist agents (`/api/v1/training`, docs/TRAINING.md). */

export type CycleStatus =
  | "queued"
  | "evaluating"
  | "experimenting"
  | "promoted"
  | "validated"
  | "rejected"
  | "no_change"
  | "failed"
  | "cancelled";

export interface PolicyView {
  id: string;
  version: number;
  status: "candidate" | "active" | "retired" | "rejected";
  summary: string;
  score: number | null;
  standards_count: number;
  lessons_count: number;
  skills_with_lessons: number;
  created_at: string;
  activated_at: string | null;
  parent_id: string | null;
  standards?: string[];
  skills?: Record<string, string[]>;
  recommendations?: { skill_id: string; category: string; priority: string; title: string; description: string }[];
}

export interface CycleView {
  id: string;
  agent: AgentProfile;
  status: CycleStatus;
  trigger: "manual" | "scheduled";
  skills_count: number;
  runs_count: number;
  baseline_version: number | null;
  candidate_version: number | null;
  experiment_url: string | null;
  error: string | null;
  created_at: string;
  finished_at: string | null;
  result: {
    baseline?: { scores: Record<string, number | null>; mean: number | null; failed_runs: number };
    changed_skills?: string[];
    new_standards?: string[];
    experiment?: {
      recommendation: string | null;
      summary: string | null;
      baseline_mean: number | null;
      candidate_mean: number | null;
      delta: number | null;
      regressions: string[];
      improvements: string[];
    };
    decision?: { promote: boolean; reason: string };
  };
}

export interface TrainingOverview {
  missing: string[];
  auto_promote: boolean;
  interval_days: number;
  repetitions: number;
  forge_url: string;
  can_manage: boolean;
  agents: {
    agent: AgentProfile;
    name: string;
    skills_count: number;
    active: PolicyView | null;
    last_cycle: CycleView | null;
    training: boolean;
  }[];
}

export interface AgentTraining {
  agent: AgentProfile;
  name: string;
  can_manage: boolean;
  active: PolicyView | null;
  skills: { id: string; name: string; translations: Record<string, { name?: string }>; lessons: string[]; score: number | null }[];
  policies: PolicyView[];
  cycles: CycleView[];
}

export const OPEN_CYCLE: CycleStatus[] = ["queued", "evaluating", "experimenting"];

const trainingKeys = {
  overview: ["training"] as const,
  agent: (agent: string) => ["training", agent] as const,
};

export function useTraining() {
  return useQuery({
    queryKey: trainingKeys.overview,
    queryFn: () => api.get<TrainingOverview>("/training"),
    refetchInterval: (q) => (q.state.data?.agents.some((a) => a.training) ? 15_000 : 60_000),
  });
}

export function useAgentTraining(agent: AgentProfile) {
  return useQuery({
    queryKey: trainingKeys.agent(agent),
    queryFn: () => api.get<AgentTraining>(`/training/agents/${agent}`),
    refetchInterval: (q) => (q.state.data?.cycles.some((c) => OPEN_CYCLE.includes(c.status)) ? 15_000 : 60_000),
  });
}

function useTrainingMutation<V = void>(fn: (v: V) => Promise<unknown>) {
  const qc = useQueryClient();
  return useMutation({ mutationFn: fn, onSettled: () => qc.invalidateQueries({ queryKey: trainingKeys.overview }) });
}

export const useStartTraining = () => useTrainingMutation((agent: AgentProfile) => api.post(`/training/agents/${agent}/cycles`));
export const useStartAllTraining = () => useTrainingMutation(() => api.post("/training/cycles"));
export const useCancelCycle = () => useTrainingMutation((cycleId: string) => api.post(`/training/cycles/${cycleId}/cancel`));
export const useRollback = () => useTrainingMutation((agent: AgentProfile) => api.post(`/training/agents/${agent}/rollback`));
export const useActivatePolicy = () => useTrainingMutation((policyId: string) => api.post(`/training/policies/${policyId}/activate`));
