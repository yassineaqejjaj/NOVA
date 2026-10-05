"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { keys } from "./hooks";

// --- Types --------------------------------------------------------------------------------------------

export type GoalAutonomy = "observe" | "suggest" | "execute_with_approval" | "execute_automatically";
export type MilestoneStatus = "pending" | "ready" | "working" | "waiting" | "done" | "blocked" | "skipped";
export type MissionState = "working" | "waiting" | "blocked" | "idle" | "done";

export interface Milestone {
  id: string;
  title: string;
  kind: "skill" | "human";
  skill_id: string | null;
  agent: "product" | "project" | "design" | "engineering" | null;
  goal: string;
  rationale: string;
  status: MilestoneStatus;
  task_id: string | null;
  artifact_ids: string[];
  started_at: string | null;
  finished_at: string | null;
  note: string;
  activity?: string | null;
  task_status?: string;
}

export interface Goal {
  id: string;
  title: string;
  outcome: string;
  due_date: string | null;
  status: "planning" | "proposed" | "active" | "paused" | "completed" | "archived";
  autonomy: GoalAutonomy;
  project_id: string | null;
  project_name: string | null;
  conversation_id: string | null;
  summary: string;
  assumptions: string[];
  milestones: Milestone[];
  progress: { done: number; total: number; percent: number };
  mission: MissionState;
  current: Milestone | null;
  next: Milestone | null;
  created_at: string;
  updated_at: string | null;
  completed_at: string | null;
}

export interface Schedule {
  kind: "manual" | "daily" | "weekdays" | "weekly" | "monthly";
  time?: string;
  days?: number[];
  day?: number;
  tz?: string;
}

export interface Routine {
  id: string;
  name: string;
  instructions: string;
  skill_ids: string[];
  template: string | null;
  schedule: Schedule;
  autonomy: GoalAutonomy;
  enabled: boolean;
  project_id: string | null;
  conversation_id: string | null;
  next_run_at: string | null;
  last_run_at: string | null;
  last_task_id: string | null;
  runs: number;
}

export interface RoutineTemplate {
  id: string;
  name: string;
  instructions: string;
  skill_ids: string[];
  schedule: Schedule;
}

export type InboxKind = "decision" | "validation" | "anomaly" | "suggestion" | "result";

export interface Confidence {
  score: number;
  level: "high" | "medium" | "low";
  dimensions: Partial<Record<"quality" | "grounding" | "completeness" | "consistency" | "safety", number>>;
  status: string | null;
  evaluated_by: ("validation" | "forge")[];
}

export interface InboxAction {
  kind: "goal" | "validate" | "review" | "retry" | "ignore" | "fix" | string;
  label: string;
  action?: string;
  prompt?: string;
  href?: string;
  task_id?: string;
  goal_id?: string;
  milestone_id?: string;
  artifact_id?: string;
}

export interface InboxItem {
  id: string;
  kind: InboxKind;
  title: string;
  subtitle?: string;
  suggestion?: string;
  context?: string;
  project_name?: string | null;
  at?: string;
  urgent?: boolean;
  risk?: boolean;
  goal_id?: string;
  milestone_id?: string;
  artifact_id?: string;
  routine_id?: string;
  task_id?: string;
  conversation_id?: string | null;
  confidence?: Confidence | null;
  actions: InboxAction[];
}

export interface Inbox {
  counts: Record<InboxKind | "total", number>;
  items: InboxItem[];
}

export interface Presence {
  state: "working" | "waiting" | "idle";
  running: number;
  waiting: number;
  mission: { kind: string; title: string; activity: string; phase: string; started_at: string; href: string } | null;
}

export interface MissionTask {
  id: string;
  title: string;
  origin: string;
  status: string;
  activity: string;
  goal_id: string | null;
  routine_id: string | null;
  conversation_id: string | null;
  progress_done: number;
  progress_total: number;
  started_at: string;
}

export interface Missions {
  goals: Goal[];
  tasks: MissionTask[];
  routines: Routine[];
}

// --- Hooks --------------------------------------------------------------------------------------------

export const missionKeys = {
  goals: ["goals"] as const,
  goal: (id: string) => ["goal", id] as const,
  routines: ["routines"] as const,
  templates: ["routine-templates"] as const,
  inbox: ["inbox"] as const,
  presence: ["presence"] as const,
  missions: ["missions"] as const,
};

export const useGoals = () => useQuery({ queryKey: missionKeys.goals, queryFn: () => api.get<Goal[]>("/goals"), refetchInterval: 15_000 });
export const useGoal = (id: string | null) =>
  useQuery({ queryKey: missionKeys.goal(id ?? ""), queryFn: () => api.get<Goal>(`/goals/${id}`), enabled: !!id, refetchInterval: 5_000 });
export const useRoutines = () => useQuery({ queryKey: missionKeys.routines, queryFn: () => api.get<Routine[]>("/routines") });
export const useRoutineTemplates = () => useQuery({ queryKey: missionKeys.templates, queryFn: () => api.get<RoutineTemplate[]>("/routines/templates"), staleTime: 300_000 });
export const useInbox = () => useQuery({ queryKey: missionKeys.inbox, queryFn: () => api.get<Inbox>("/inbox"), refetchInterval: 30_000 });
export const usePresence = () => useQuery({ queryKey: missionKeys.presence, queryFn: () => api.get<Presence>("/presence"), refetchInterval: 5_000 });
export const useMissions = () => useQuery({ queryKey: missionKeys.missions, queryFn: () => api.get<Missions>("/missions"), refetchInterval: 5_000 });

function useRefresh() {
  const client = useQueryClient();
  return () => {
    for (const key of [missionKeys.goals, missionKeys.inbox, missionKeys.presence, missionKeys.missions, missionKeys.routines, keys.today]) {
      void client.invalidateQueries({ queryKey: key });
    }
    void client.invalidateQueries({ queryKey: ["goal"] });
    void client.invalidateQueries({ queryKey: ["tasks"] });
  };
}

export function useCreateGoal() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: { title: string; outcome: string; due_date: string | null; project_id: string | null; autonomy: GoalAutonomy; lang: "en" | "fr" }) =>
      api.post<Goal>("/goals", body),
    onSuccess: refresh,
  });
}

export function useGoalAction() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ goalId, ...body }: { goalId: string; action: string; milestone_id?: string; note?: string }) => api.post<Goal>(`/goals/${goalId}/actions`, body),
    onSuccess: refresh,
  });
}

export function useSaveRoutine() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ id, ...body }: Partial<Routine> & { id?: string }) => (id ? api.patch<Routine>(`/routines/${id}`, body) : api.post<Routine>("/routines", body)),
    onSuccess: refresh,
  });
}

export function useRunRoutine() {
  const refresh = useRefresh();
  return useMutation({ mutationFn: (id: string) => api.post<Routine & { task_id: string }>(`/routines/${id}/run`), onSuccess: refresh });
}

export function useDeleteRoutine() {
  const refresh = useRefresh();
  return useMutation({ mutationFn: (id: string) => api.delete(`/routines/${id}`), onSuccess: refresh });
}

export function useValidateDeliverable() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ artifactId, inboxId }: { artifactId: string; inboxId: string }) => api.post(`/inbox/validate/${artifactId}`, { inbox_id: inboxId }),
    onSuccess: refresh,
  });
}

export function useDismiss() {
  const refresh = useRefresh();
  return useMutation({ mutationFn: (id: string) => api.post("/today/dismiss", { id }), onSuccess: refresh });
}
