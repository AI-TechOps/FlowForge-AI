/**
 * Response shapes, transcribed from the FastAPI handlers they come from.
 *
 * Hand-written rather than generated: the backend has no OpenAPI client
 * pipeline, and adding one to consume ~15 endpoints would be more machinery
 * than the thing it automates. The trade is that these can drift, so each type
 * names its endpoint — when a screen is wrong, there is one file to check
 * against one handler.
 *
 * Optional fields are optional because the API genuinely omits them, not out of
 * caution. `metrics.estimated_cost_usd` is absent for non-administrators by
 * design (D19 decision 6), and that absence is what the UI renders.
 */

export type Role = "administrator" | "operator" | "approver";

/** GET /api/me */
export interface Identity {
  id: string;
  org_id: string;
  email: string;
  roles: Role[];
}

/** GET /api/health */
export interface Health {
  status: string;
  db: string;
  redis: string;
}

export type RunStatus =
  | "queued"
  | "running"
  | "awaiting_approval"
  | "executing"
  | "completed"
  | "rejected"
  | "failed";

export type TicketStatus = "new" | "triaged" | "actioned" | "closed";

export type DocumentStatus = "pending" | "processing" | "ready" | "failed";

/** One retrieved chunk, as stored on `runs.evidence`. */
export interface EvidenceChunk {
  chunk_id: string;
  document_title?: string | null;
  document_id?: string | null;
  page?: number | null;
  section?: string | null;
  score?: number | null;
  text?: string | null;
}

/** A citation the model emitted, pointing at a chunk it was given. */
export interface Citation {
  chunk_id: string;
  quote?: string | null;
}

/** The Pydantic-validated triage result on `runs.output`. */
export interface TriageOutput {
  summary?: string;
  category?: string;
  urgency?: string;
  recommended_team?: string;
  suggested_priority?: string;
  recommended_resolution?: string;
  confidence?: number;
  requires_approval?: boolean;
  citations?: Citation[];
  executed_actions?: ProposedAction[];
}

export interface ProposedAction {
  tool: string;
  field?: string | null;
  current_value?: unknown;
  new_value?: unknown;
  args?: Record<string, unknown>;
}

/** One audit row as embedded in a run detail response. */
export interface RunAuditEntry {
  actor: string;
  tool: string;
  payload: unknown;
  result: unknown;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_estimate: number | null;
  created_at: string;
}

/** GET /api/runs/{id} */
export interface Run {
  id: string;
  ticket_id: string;
  status: RunStatus;
  agent_version?: string | null;
  confidence?: number | null;
  output?: TriageOutput | null;
  evidence?: EvidenceChunk[] | null;
  failure_reason?: string | null;
  error?: string | null;
  attempts?: number;
  eval_batch_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string;
  /**
   * Present on run *detail* only, and already tenant-scoped for every persona.
   * Run detail is an any-persona screen, so its audit panel reads from here
   * rather than from the administrator-only `/api/audit` — which is why an
   * operator saw no trail at all.
   */
  audit_entries?: RunAuditEntry[];
}

/** GET /api/runs */
export interface RunPage {
  total: number;
  limit: number;
  offset: number;
  runs: Run[];
}

/** GET /api/tickets/{id} */
export interface Ticket {
  id: string;
  title: string;
  description: string;
  status: TicketStatus;
  department?: string | null;
  service?: string | null;
  priority?: string | null;
  assigned_team?: string | null;
  external_ref?: string | null;
  is_eval_seed?: boolean;
  internal_notes?: unknown[];
  created_at?: string;
}

/** GET /api/documents */
export interface KnowledgeDocument {
  id: string;
  title: string;
  version?: string | null;
  status: DocumentStatus;
  chunk_count?: number | null;
  error_message?: string | null;
  file_ref?: string | null;
  created_at?: string;
}

export type ApprovalStatusValue = "pending" | "decided";
export type DecisionValue = "approved" | "edited" | "rejected";

/** GET /api/approvals/{id} */
export interface Approval {
  id: string;
  run_id: string;
  /**
   * The affected ticket, embedded by the detail endpoint — id, title, status,
   * priority and team, already tenant-scoped. Reading it from here is what
   * lets the approval card name its subject without two further round trips
   * for data the payload already carried.
   */
  ticket?: {
    id: string;
    title: string;
    status: string;
    priority?: string | null;
    assigned_team?: string | null;
  } | null;
  /** Not sent by the current API; tolerated in case the shape is ever flattened. */
  ticket_id?: string | null;
  status: ApprovalStatusValue;
  decision?: DecisionValue | null;
  risk_class?: string | null;
  original_proposal?: ProposedAction[] | null;
  final_values?: unknown;
  feedback?: string | null;
  confidence?: number | null;
  agent_version?: string | null;
  evidence?: EvidenceChunk[] | null;
  decided_at?: string | null;
  created_at?: string;
}

/** GET /api/metrics/summary — admin-only keys are absent, not null (D19.6). */
export interface MetricsSummary {
  window_days: number;
  total_runs: number;
  successful_runs: number;
  failed_runs: number;
  waiting_approvals: number;
  avg_latency_seconds: number | null;
  avg_tokens_per_run: number | null;
  tool_success_rate: number | null;
  approval_rate: number | null;
  human_edit_rate: number | null;
  human_rejection_rate: number | null;
  retrieval_success: number | null;
  grounded_rate: number | null;
  latest_eval_batch_id: string | null;
  /** Administrator only. */
  evaluation_accuracy?: number | null;
  /** Administrator only. */
  estimated_cost_usd?: number;
  /** Administrator only. */
  cost_pricing_as_of?: string;
}

/** GET /api/audit */
export interface AuditEntry {
  id: string;
  run_id: string | null;
  actor: string;
  tool: string;
  payload: unknown;
  result: unknown;
  latency_ms: number | null;
  tokens_in: number | null;
  tokens_out: number | null;
  cost_estimate: number | null;
  created_at: string;
}

export interface AuditPage {
  total: number;
  limit: number;
  offset: number;
  entries: AuditEntry[];
}

/** GET /api/eval/batches */
export interface EvalBatch {
  id: string;
  agent_version: string;
  llm_provider?: string | null;
  triage_model: string;
  judge_model?: string | null;
  status: "running" | "completed" | "failed";
  total_tickets: number;
  started_at?: string | null;
  finished_at?: string | null;
  summary?: EvalSummary | null;
  created_at?: string;
}

export interface EvalSummary {
  scored_tickets?: number;
  failed_runs?: number;
  accuracy_overall?: number | null;
  accuracy_category?: number | null;
  accuracy_urgency?: number | null;
  accuracy_recommended_team?: number | null;
  grounded_rate?: number | null;
  retrieval_hit_at_k?: number | null;
  judge_resolution_quality_mean?: number | null;
  judge_citation_support_mean?: number | null;
  judged_tickets?: number;
  total_tickets?: number;
}

export interface EvalResult {
  id: string;
  run_id: string | null;
  ticket_id: string;
  seed_ref: string | null;
  expected: Record<string, unknown>;
  actual: Record<string, unknown> | null;
  scores: Record<string, unknown>;
  judge_model: string | null;
  failure_reason: string | null;
}

export interface EvalBatchDetail extends EvalBatch {
  results: EvalResult[];
}

/** GET /api/config/agent */
export interface AgentConfig {
  agent_version: string;
  judge_version: string;
  llm_provider: string;
  triage_model: string;
  judge_model: string;
  embedding_model: string;
  run_timeout_seconds: number;
  max_run_attempts: number;
  taxonomy: {
    categories: string[];
    urgencies: string[];
    teams: string[];
    priorities: string[];
  };
}
