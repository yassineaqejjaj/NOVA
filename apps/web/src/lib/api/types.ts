// Types of the NOVA API (apps/api/nova_api). Kept in sync by hand with the routers.

export type TaskStatus = "queued" | "scheduled" | "running" | "waiting_user" | "paused" | "completed" | "failed" | "cancelled";
export type NovaPhase = "idle" | "retrieving_context" | "planning" | "executing" | "waiting_user" | "completed" | "failed";
export type AutonomyMode = "suggest" | "assist" | "execute_with_approval" | "execute_automatically";
export type BlockType =
  | "text" | "plan" | "workflow" | "question" | "checklist" | "task" | "artifact" | "table" | "decision"
  | "context_sources" | "tool_execution" | "progress" | "warning" | "error" | "citations";

export interface Action { label: string; action: string }

export interface Me {
  id: string;
  email: string;
  display_name: string;
  title: string;
  is_admin: boolean;
  roles: string[];
  preferences: Preferences;
  orbit: OrbitIdentity;
}

export interface Preferences {
  nova_name: string;
  avatar?: string;
  tone?: string;
  role?: string;
  teams?: string[];
  preferred_methods?: string[];
  artifact_format?: string;
  default_autonomy?: AutonomyMode;
  theme?: "dark" | "light" | "system";
  language?: "en" | "fr" | null;
  orb_color?: "coral" | "rose" | "violet" | "ocean" | "emerald" | "amber" | "graphite";
  /** The user's profile: the specialist agent NOVA leads with. */
  profile?: "product" | "project" | "design" | "engineering";
  onboarding_completed?: boolean;
}

export interface OrbitIdentity {
  linked: boolean;
  external_user_id?: string | null;
  email?: string | null;
  display_name?: string | null;
  clearance?: number | null;
  expires_at?: string | null;
  mode: "session" | "agent_key" | "none";
}

export interface Block<T = Record<string, unknown>> { key: string; type: BlockType; position: number; data: T }

export interface TaskSummary {
  id: string;
  status: TaskStatus;
  phase: NovaPhase;
  phase_label: string;
  progress_done: number;
  progress_total: number;
  waiting_for: WaitingFor | null;
  trace_id: string | null;
}

export type WaitingFor =
  | { kind: "questions"; questions: { key: string; question: string; skill_id?: string | null }[] }
  | { kind: "confirm_workflow"; workflow_id: string }
  | { kind: "approval"; approval_id: string };

export interface Message {
  id: string;
  role: "user" | "nova";
  created_at: string;
  meta: { text?: string; project_id?: string | null; skill_refs?: string[]; attachments?: string[]; seed?: boolean };
  blocks: Block[];
  task: TaskSummary | null;
}

export interface Conversation {
  id: string;
  title: string;
  project_id: string | null;
  archived: boolean;
  updated_at: string;
  messages?: Message[];
}

export interface ComposerPayload {
  text: string;
  project_id?: string | null;
  context_mode?: "auto" | "explicit" | "none";
  pinned_context_ref_ids?: string[];
  excluded_context_refs?: string[];
  artifact_refs?: string[];
  skill_refs?: string[];
  active_artifact_id?: string | null;
  autonomy?: AutonomyMode | null;
  attachments?: { name: string; text: string }[];
  scheduled_for?: string | null;
}

export type RecommendationAction =
  | { kind: "fix"; label: string; prompt: string; artifact_id?: string; artifact_title?: string }
  | { kind: "review"; label: string; href: string }
  | { kind: "retry"; label: string; task_id: string }
  | { kind: "ignore"; label: string };

/** A business object that needs the user: what, where, why it matters and what NOVA can do about it. */
export interface Recommendation {
  id: string;
  source: "orbit" | "nova";
  title: string;
  subtitle?: string;
  context: string;
  suggestion: string;
  actions: RecommendationAction[];
  task_id?: string;
  conversation_id?: string | null;
  project_id?: string | null;
  project_name?: string | null;
  artifact_id?: string;
  classification?: number;
  urgent?: boolean;
  risk?: boolean;
  at: string;
}

export type OrbState = "idle" | "thinking" | "working" | "waiting" | "clarification" | "completed";

export interface ContextProjectOverview {
  id: string;
  name: string;
  url: string | null;
  documents: number;
  memory_items: number;
  decisions: number;
  sources: number;
  snapshots: number;
}

export interface Today {
  user: { display_name: string; first_name: string; title: string };
  nova: { name: string; avatar?: string; state: OrbState };
  onboarding_completed: boolean;
  brief: { actions_required: number; running: number; paused: number; waiting: number; results_ready: number; projects_at_risk: string[] };
  recommendations: Recommendation[];
  continue: { conversation_id: string; title: string; project_name: string | null; updated_at: string }[];
  context: {
    system: "ORBIT";
    linked: boolean;
    account: string | null;
    error: string | null;
    projects: ContextProjectOverview[];
    totals: { documents: number; memory_items: number; decisions: number; sources: number };
    changes_24h: number;
    last_change_at: string | null;
  };
  quality: {
    system: "FORGE";
    monitoring: boolean;
    last_evaluation: { score: number | null; passed: boolean | null; status: string | null; url: string | null; at: string } | null;
    url: string;
  };
  orbit: { linked: boolean; error: string | null };
  inbox: import("./missions").Inbox;
  since: { at: string; count: number; decisions: number; worked_on: { task_id: string; title: string; origin: string; conversation_id: string | null; artifact_ids: string[]; at: string | null }[] };
  recommended: import("./missions").InboxItem[];
  goals: import("./missions").Goal[];
}

export interface Project {
  id: string;
  slug: string;
  name: string;
  description: string;
  role: string | null;
  orbit_slug: string | null;
  orbit_url: string | null;
  stats: { artifacts?: number; active_work?: number };
  updated_at: string;
}

export interface ChangeEvent {
  id: string;
  project_slug: string;
  type: string;
  type_label: string;
  title: string;
  summary: string;
  classification: number;
  created_at: string;
  data: Record<string, unknown>;
}

export interface ProjectDetail extends Project {
  people: { name: string; title: string; role: string }[];
  decisions: ChangeEvent[];
  recent_context?: ChangeEvent[];
  context_error: { code: string; message: string } | null;
}

export interface TaskStep {
  id: string;
  title: string;
  skill_id: string | null;
  skill_name: string | null;
  skill_version: string | null;
  /** The sub-agent carrying out the step (owner of its Skill). */
  agent: "product" | "project" | "design" | "engineering";
  status: string;
  detail: string;
  artifact_id: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface EvaluationRef {
  scenario_id?: string | null;
  run_id?: string | null;
  status?: string | null;
  composite_score?: number | null;
  passed?: boolean | null;
  url?: string | null;
  pending_feedback?: unknown[];
}

export interface WorkItem {
  id: string;
  objective: string;
  status: TaskStatus;
  phase: NovaPhase;
  phase_label: string;
  project_id: string | null;
  conversation_id: string | null;
  skills: string[];
  progress_done: number;
  progress_total: number;
  created_at: string;
  scheduled_for: string | null;
  duration_seconds: number | null;
  trace_id: string | null;
  evaluation: EvaluationRef | null;
  error: string | null;
  artifact_ids: string[];
  steps?: TaskStep[];
  artifacts?: { id: string; title: string; type: string; version: number }[];
  model?: string | null;
  usage?: { input_tokens?: number; output_tokens?: number; model_calls?: number };
  waiting_for?: WaitingFor | null;
}

export interface SkillSummary {
  id: string;
  name: string;
  version: string;
  category: string;
  agent: "product" | "project" | "design" | "engineering";
  summary: string;
  artifact_type: string;
  artifact_type_name: string | null;
  steps: { id: string; title: string }[];
  triggers: string[];
  /** Display translations, e.g. { fr: { name, summary, artifact_type_name, purpose, steps, … } } (see SkillTranslation). */
  translations?: Record<string, SkillTranslation>;
}

/** Display translation of a Skill (`skills/i18n/<lang>.yaml`); prompts keep the English definition. */
export interface SkillTranslation {
  name?: string;
  summary?: string;
  artifact_type_name?: string | null;
  purpose?: string | null;
  /** Methodology name. */
  method?: string | null;
  /** Same order and length as methodology.principles. */
  principles?: string[] | null;
  /** Skill step id → title. */
  steps?: Record<string, string>;
  /** Evaluation criterion key → question. */
  criteria?: Record<string, string>;
  /** Same order and length as evaluation.checks (descriptions). */
  checks?: string[] | null;
  /** Input name → description and question. */
  inputs?: Record<string, { description?: string | null; question?: string | null }>;
}

export interface SkillDetail extends SkillSummary {
  purpose: string;
  inputs: { name: string; description: string; required: boolean; ask: boolean; question?: string | null }[];
  methodology: { name: string; principles: string[]; references: string[] };
  tools: string[];
  expected_context: { orbit_intent: string; token_budget: number; required: boolean; query_hint: string };
  composes_with: string[];
  evaluation: { criteria: { key: string; question: string; weight?: number }[]; checks: { type: string; description: string }[] };
  instructions: string;
  content_hash: string;
  mode: "create" | "update";
}

// --- Artifacts -----------------------------------------------------------------------------------

export interface Citation { label: string; ref?: string | null; title?: string | null }
export interface TextBlock { type: "paragraph" | "heading" | "bullet" | "numbered" | "quote"; text: string; citations: Citation[] }
export interface ArtifactItem {
  id: string;
  kind: string;
  title: string;
  description: string;
  parent_id: string | null;
  rationale: string;
  citations: Citation[];
  attributes: Record<string, unknown>;
}
export interface SectionContent { kind: "rich_text" | "items"; blocks: TextBlock[]; items: ArtifactItem[] }
export interface ArtifactContent { type: string; title: string; sections: Record<string, SectionContent>; metadata: Record<string, unknown> }
export interface SectionDefinition { key: string; title: string; kind: "rich_text" | "items"; item_kind: string | null; description: string }
export interface ArtifactTypeTranslation { name?: string; description?: string; sections?: Record<string, { title?: string; description?: string }> }
export interface ArtifactTypeDef {
  type: string;
  name: string;
  description: string;
  icon: string;
  sections: SectionDefinition[];
  /** Display translations (prompts always use the canonical definition). */
  translations?: Record<string, ArtifactTypeTranslation>;
}

export interface ArtifactSummary {
  id: string;
  type: string;
  type_name: string;
  icon: string;
  title: string;
  status: "draft" | "in_review" | "final" | "archived";
  project_id: string | null;
  version: number;
  classification: number;
  owner_id: string;
  conversation_id: string | null;
  task_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ArtifactDetail extends ArtifactSummary {
  role: string;
  can_edit: boolean;
  viewing_version: number;
  version_state: string;
  proposed_version: number | null;
  content: ArtifactContent;
  definition: ArtifactTypeDef;
  evaluation: EvaluationRef | null;
  evidence: { sources_count: number; updated_at: string | null; by_type: { type: string; count: number }[]; sources: ContextSource[] };
  quality: QualityCheck[];
}

export interface QualityCheck { key: string; label: string; status: "pass" | "warn" | "pending"; detail: string }

export interface ArtifactVersionInfo {
  version: number;
  state: string;
  author_type: "user" | "nova";
  author_name: string | null;
  skill_id: string | null;
  skill_version: string | null;
  changed_sections: string[];
  summary: string;
  task_id: string | null;
  created_at: string;
}

export interface SectionDiff {
  key: string;
  status: "added" | "removed" | "changed" | "unchanged";
  added_items: string[];
  removed_items: string[];
  changed_items: string[];
  before_text: string;
  after_text: string;
}

export interface ContextSource {
  label: string;
  title: string;
  type?: string | null;
  kind?: string;
  source?: string;
  project?: string | null;
  uri?: string | null;
  updated?: string | null;
  classification: number;
  classification_label?: string;
  excerpt?: string;
  relevance?: number | null;
  flagged?: boolean;
  reference_id?: string | null;
  citation?: string;
}

export interface Provenance {
  sources: ContextSource[];
  rationale: string;
  origin: { version: number; skill_id: string | null; skill_version: string | null; created_at: string } | null;
  unresolved: number;
}

export interface CommentInfo { id: string; section_key: string; item_id: string | null; author_name: string; body: string; resolved: boolean; created_at: string }

export interface ActivityEvent {
  kind: string;
  category: "work" | "artifact" | "decision" | "context" | "quality";
  system?: "ORBIT" | "NOVA" | "FORGE" | "You";
  href?: string | null;
  classification?: number;
  project_name?: string | null;
  author?: "user" | "nova";
  at: string;
  text: string;
  detail?: string;
  status?: string;
  task_id?: string | null;
  artifact_id?: string;
  project_id?: string | null;
  conversation_id?: string | null;
  skills?: string[];
}

export interface SearchResults {
  projects: { id: string; name: string; description: string }[];
  artifacts: { id: string; title: string; type: string }[];
  conversations: { id: string; title: string }[];
  skills: { id: string; name: string; summary: string; translations?: SkillSummary["translations"] }[];
  context: { ref_id: string; title: string; snippet: string; project_id: string; source_kind?: string | null }[];
  context_error: { message: string }[];
}

export interface ExecutionEvent {
  seq?: number;
  type: "status" | "progress" | "block" | "task" | "done" | "error" | "heartbeat";
  phase?: NovaPhase;
  label?: string;
  message_id?: string;
  block?: Block;
  status?: string;
  [key: string]: unknown;
}

export interface ApiErrorBody { detail: string; code: string; actions: Action[] }
