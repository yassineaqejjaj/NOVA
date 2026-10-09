"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";

// --- Types ------------------------------------------------------------------------------------------------

export type RunKind = "feature" | "bugfix" | "refactor" | "review";
export type RunStatus = "queued" | "running" | "waiting_user" | "completed" | "failed" | "cancelled";
export type StageStatus = "pending" | "running" | "done" | "skipped" | "failed" | "waiting";
export type StageKey = "spec" | "design" | "implement" | "tests" | "pull_request" | "review" | "ci" | "merge" | "release";

export interface Stage {
  key: StageKey;
  status: StageStatus;
  summary: string;
  output?: Record<string, unknown>;
  started_at: string | null;
  finished_at: string | null;
}

export interface Run {
  id: string;
  kind: RunKind;
  title: string;
  goal: string;
  repo: string;
  base_branch: string;
  branch: string;
  autonomy: "guided" | "autopilot";
  auto_merge: boolean;
  has_deploy_hook: boolean;
  status: RunStatus;
  stage: StageKey;
  gate: "plan" | "merge" | null;
  issue_url: string;
  pr_number: number | null;
  pr_url: string;
  merge_sha: string;
  release_url: string;
  model: string;
  usage: { input_tokens?: number; output_tokens?: number; model_calls?: number };
  error: string;
  created_at: string | null;
  updated_at: string | null;
  finished_at: string | null;
  stages: Stage[];
  log?: { at: string; level: "info" | "error"; message: string }[];
  release?: { version: string; title: string; notes: string } | null;
}

export interface LlmProviderInfo {
  id: string;
  label: string;
  default_model: string;
  models: string[];
  key_hint: string;
  needs_base_url: boolean;
}

export interface LlmConfig {
  providers: LlmProviderInfo[];
  configured: boolean;
  provider: string | null;
  model: string | null;
  base_url: string;
  key_hint: string;
  verified_at: string | null;
  default_model: string;
}

export interface GithubStatus {
  linked: boolean;
  login: string | null;
  scopes: string;
  can_write: boolean;
}

export interface GithubRepo {
  full_name: string;
  private: boolean;
  default_branch: string;
  description: string;
  can_push: boolean;
}

export interface RunInput {
  kind: RunKind;
  title?: string;
  goal?: string;
  repo?: string;
  base_branch?: string | null;
  autonomy: "guided" | "autopilot";
  auto_merge: boolean;
  deploy_hook?: string | null;
  issue_url?: string;
  pr_url?: string;
  post_review?: boolean;
}

export const engKeys = {
  llm: ["llm"] as const,
  github: ["github"] as const,
  repos: ["github-repos"] as const,
  runs: ["sdlc-runs"] as const,
  run: (id: string) => ["sdlc-run", id] as const,
};

const ACTIVE: RunStatus[] = ["queued", "running"];

// --- Hooks ------------------------------------------------------------------------------------------------

export const useLlmConfig = () => useQuery({ queryKey: engKeys.llm, queryFn: () => api.get<LlmConfig>("/me/llm") });
export const useGithub = () => useQuery({ queryKey: engKeys.github, queryFn: () => api.get<GithubStatus>("/me/github") });
export const useRepos = (enabled: boolean) =>
  useQuery({ queryKey: engKeys.repos, queryFn: () => api.get<GithubRepo[]>("/me/github/repos"), enabled, staleTime: 120_000 });

export const useRuns = () =>
  useQuery({
    queryKey: engKeys.runs,
    queryFn: () => api.get<Run[]>("/sdlc/runs"),
    refetchInterval: (q) => (q.state.data?.some((r) => ACTIVE.includes(r.status)) ? 3000 : 20_000),
  });

export const useRun = (id: string) =>
  useQuery({
    queryKey: engKeys.run(id),
    queryFn: () => api.get<Run>(`/sdlc/runs/${id}`),
    refetchInterval: (q) => (!q.state.data || ACTIVE.includes(q.state.data.status) ? 2500 : 15_000),
  });

export function useCreateRun() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: RunInput) => api.post<Run>("/sdlc/runs", body),
    onSuccess: (run) => {
      client.setQueryData(engKeys.run(run.id), run);
      void client.invalidateQueries({ queryKey: engKeys.runs });
    },
  });
}

export function useRunAction(id: string) {
  const client = useQueryClient();
  const done = (run: Run) => {
    client.setQueryData(engKeys.run(id), run);
    void client.invalidateQueries({ queryKey: engKeys.runs });
  };
  return {
    approve: useMutation({ mutationFn: (notes: string) => api.post<Run>(`/sdlc/runs/${id}/approve`, { notes }), onSuccess: done }),
    cancel: useMutation({ mutationFn: () => api.post<Run>(`/sdlc/runs/${id}/cancel`), onSuccess: done }),
    retry: useMutation({ mutationFn: () => api.post<Run>(`/sdlc/runs/${id}/retry`), onSuccess: done }),
    release: useMutation({ mutationFn: (v: { tag: string; draft: boolean }) => api.post<Run>(`/sdlc/runs/${id}/release`, v), onSuccess: done }),
    deploy: useMutation({ mutationFn: () => api.post<Run>(`/sdlc/runs/${id}/deploy`), onSuccess: done }),
  };
}
