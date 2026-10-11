"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { AgentProfile } from "@/lib/agents";

import { api } from "./client";

/** Releases of learned policies: canary, approval and rollback (`/api/v1/releases`, docs/TRAINING.md). */

export type ReleaseStatus = "canary" | "awaiting_approval" | "active" | "rolled_back" | "rejected" | "superseded";

export interface Cohort {
  runs: number;
  failed: number;
  failure_rate: number;
}

export interface ReleaseView {
  id: string;
  agent: AgentProfile;
  label: string;
  status: ReleaseStatus;
  canary_percent: number;
  policy_id: string;
  baseline_policy_id: string | null;
  evidence: { delta?: number | null; baseline_mean?: number | null; candidate_mean?: number | null; manual?: boolean };
  reason: string;
  decided_by: string | null;
  created_at: string;
  canary_started_at: string | null;
  decided_at: string | null;
  canary: Cohort;
  control: Cohort;
  min_runs: number;
}

export interface ReleasesOverview {
  can_manage: boolean;
  releases: ReleaseView[];
}

export const OPEN_RELEASE: ReleaseStatus[] = ["canary", "awaiting_approval"];

const releaseKey = ["releases"] as const;

export function useReleases() {
  return useQuery({
    queryKey: releaseKey,
    queryFn: () => api.get<ReleasesOverview>("/releases"),
    refetchInterval: (q) => (q.state.data?.releases.some((r) => OPEN_RELEASE.includes(r.status)) ? 15_000 : 60_000),
  });
}

function useReleaseMutation(action: "approve" | "rollback" | "evaluate") {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post(`/releases/${id}/${action}`),
    // A decision changes which policy is active: refresh the training views too.
    onSettled: () => Promise.all([qc.invalidateQueries({ queryKey: releaseKey }), qc.invalidateQueries({ queryKey: ["training"] })]),
  });
}

export const useApproveRelease = () => useReleaseMutation("approve");
export const useRollbackRelease = () => useReleaseMutation("rollback");
export const useEvaluateRelease = () => useReleaseMutation("evaluate");
