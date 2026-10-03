"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, qs } from "./client";
import type {
  ActivityEvent,
  ArtifactDetail,
  ArtifactSummary,
  ArtifactTypeDef,
  ArtifactVersionInfo,
  CommentInfo,
  ComposerPayload,
  Conversation,
  Me,
  Message,
  Project,
  ProjectDetail,
  Provenance,
  SearchResults,
  SectionDiff,
  SkillDetail,
  SkillSummary,
  TaskSummary,
  Today,
  WorkItem,
} from "./types";

export const keys = {
  me: ["me"] as const,
  today: ["today"] as const,
  conversations: (projectId?: string | null) => ["conversations", projectId ?? "all"] as const,
  conversation: (id: string) => ["conversation", id] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["project", id] as const,
  projectContext: (id: string) => ["project-context", id] as const,
  tasks: (tab: string, projectId?: string | null) => ["tasks", tab, projectId ?? "all"] as const,
  task: (id: string) => ["task", id] as const,
  skills: ["skills"] as const,
  skill: (id: string) => ["skill", id] as const,
  artifacts: (filters: Record<string, string | undefined>) => ["artifacts", filters] as const,
  artifact: (id: string, version?: number | null) => ["artifact", id, version ?? "current"] as const,
  artifactVersions: (id: string) => ["artifact-versions", id] as const,
  artifactComments: (id: string) => ["artifact-comments", id] as const,
  artifactTypes: ["artifact-types"] as const,
  activity: (filters: Record<string, string | undefined>) => ["activity", filters] as const,
  context: ["context"] as const,
  search: (q: string) => ["search", q] as const,
};

export const useMe = () => useQuery({ queryKey: keys.me, queryFn: () => api.get<Me>("/me"), staleTime: 60_000 });
export const useToday = () => useQuery({ queryKey: keys.today, queryFn: () => api.get<Today>("/today"), refetchInterval: 120_000 });
export const useProjects = () => useQuery({ queryKey: keys.projects, queryFn: () => api.get<Project[]>("/projects") });
export const useProject = (id: string) => useQuery({ queryKey: keys.project(id), queryFn: () => api.get<ProjectDetail>(`/projects/${id}`) });
export const useConversations = (projectId?: string | null) =>
  useQuery({ queryKey: keys.conversations(projectId), queryFn: () => api.get<Conversation[]>(`/conversations${qs({ project_id: projectId })}`) });
export const useConversation = (id: string | null) =>
  useQuery({ queryKey: keys.conversation(id ?? ""), queryFn: () => api.get<Conversation>(`/conversations/${id}`), enabled: !!id });
export const useTasks = (tab: string, projectId?: string | null) =>
  useQuery({
    queryKey: keys.tasks(tab, projectId),
    queryFn: () => api.get<WorkItem[]>(`/tasks${qs({ tab, project_id: projectId })}`),
    refetchInterval: tab === "active" ? 5_000 : false,
  });
export const useTask = (id: string | null) =>
  useQuery({ queryKey: keys.task(id ?? ""), queryFn: () => api.get<WorkItem>(`/tasks/${id}`), enabled: !!id });
export const useSkills = () => useQuery({ queryKey: keys.skills, queryFn: () => api.get<SkillSummary[]>("/skills"), staleTime: 300_000 });
export const useSkill = (id: string | null) =>
  useQuery({ queryKey: keys.skill(id ?? ""), queryFn: () => api.get<SkillDetail>(`/skills/${id}`), enabled: !!id, staleTime: 300_000 });
export const useArtifactTypes = () =>
  useQuery({ queryKey: keys.artifactTypes, queryFn: () => api.get<ArtifactTypeDef[]>("/artifacts/types"), staleTime: Infinity });
export interface JsonSchema {
  type?: string | string[];
  enum?: string[];
  description?: string;
  properties?: Record<string, JsonSchema>;
  items?: JsonSchema;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
}
export const useItemKinds = () =>
  useQuery({ queryKey: ["item-kinds"], queryFn: () => api.get<Record<string, JsonSchema>>("/artifacts/item-kinds"), staleTime: Infinity });
export const useArtifacts = (filters: { project_id?: string; type?: string; q?: string }, enabled = true) =>
  useQuery({ queryKey: keys.artifacts(filters), queryFn: () => api.get<ArtifactSummary[]>(`/artifacts${qs(filters)}`), enabled });
export const useArtifact = (id: string | null, version?: number | null) =>
  useQuery({
    queryKey: keys.artifact(id ?? "", version),
    queryFn: () => api.get<ArtifactDetail>(`/artifacts/${id}${qs({ version })}`),
    enabled: !!id,
  });
export const useArtifactVersions = (id: string | null) =>
  useQuery({ queryKey: keys.artifactVersions(id ?? ""), queryFn: () => api.get<ArtifactVersionInfo[]>(`/artifacts/${id}/versions`), enabled: !!id });
export const useArtifactComments = (id: string | null) =>
  useQuery({ queryKey: keys.artifactComments(id ?? ""), queryFn: () => api.get<CommentInfo[]>(`/artifacts/${id}/comments`), enabled: !!id });
export const useCompare = (id: string, from: number | null, to: number | null) =>
  useQuery({
    queryKey: ["artifact-compare", id, from, to],
    queryFn: () => api.get<{ sections: SectionDiff[] }>(`/artifacts/${id}/compare${qs({ from, to })}`),
    enabled: from !== null && to !== null,
  });
export const useProvenance = (id: string, params: { section?: string; item?: string }, enabled: boolean) =>
  useQuery({
    queryKey: ["provenance", id, params],
    queryFn: () => api.get<Provenance>(`/artifacts/${id}/provenance${qs(params)}`),
    enabled,
  });
export const useActivity = (filters: Record<string, string | undefined>) =>
  useQuery({ queryKey: keys.activity(filters), queryFn: () => api.get<ActivityEvent[]>(`/activity${qs(filters)}`) });
export const useSearch = (q: string) =>
  useQuery({ queryKey: keys.search(q), queryFn: () => api.get<SearchResults>(`/search${qs({ q })}`), enabled: q.trim().length >= 2 });

export interface SendResult {
  user_message: Message;
  message: Message;
  task: TaskSummary;
  conversation: Conversation;
}

/** Start a conversation if needed, then send the intent. */
export function useSendIntent() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ conversationId, payload }: { conversationId?: string | null; payload: ComposerPayload }) => {
      let id = conversationId;
      if (!id) id = (await api.post<Conversation>("/conversations", { project_id: payload.project_id ?? null })).id;
      return api.post<SendResult>(`/conversations/${id}/messages`, payload);
    },
    onSuccess: (result) => {
      client.setQueryData<Conversation>(keys.conversation(result.conversation.id), (old) => ({
        ...result.conversation,
        messages: [...(old?.messages ?? []), result.user_message, result.message],
      }));
      void client.invalidateQueries({ queryKey: ["conversations"] });
      void client.invalidateQueries({ queryKey: ["tasks"] });
    },
  });
}

export function useResume() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ taskId, value }: { taskId: string; value: Record<string, unknown> }) =>
      api.post(`/executions/${taskId}/resume`, { value }),
    // The refetched task status (queued) re-opens the live stream.
    onSuccess: () => client.invalidateQueries({ queryKey: ["conversation"] }),
  });
}
