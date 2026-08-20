/**
 * Every read in the app, as a TanStack Query hook (D21 decision 1).
 *
 * The polling intervals are the ones the spec fixes, and they are declared
 * here rather than at each call site so "how live is this screen?" has one
 * answer. Each poll stops on its own terms:
 *
 *   - run detail stops when the run reaches a terminal status,
 *   - documents stop when nothing is pending or processing,
 *   - the eval batch stops when the batch is no longer running.
 *
 * A poll that never stops is a poll that hammers the API for as long as a tab
 * is open, which on the audit and metrics screens is a real cost.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type {
  AgentConfig,
  Approval,
  AuditPage,
  DecisionValue,
  EvalBatch,
  EvalBatchDetail,
  Health,
  Identity,
  KnowledgeDocument,
  MetricsSummary,
  ProposedAction,
  Run,
  RunPage,
  RunStatus,
  Ticket,
} from "./types";

export const POLL = {
  run: 2000,
  approvals: 5000,
  documents: 3000,
  dashboard: 15000,
  evalBatch: 4000,
} as const;

const TERMINAL_RUN: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "completed",
  "rejected",
  "failed",
]);

export const isTerminal = (status?: RunStatus): boolean =>
  status !== undefined && TERMINAL_RUN.has(status);

/** Shown as a live pulse in the UI — the run is still moving. */
export const isActive = (status?: RunStatus): boolean =>
  status !== undefined && !TERMINAL_RUN.has(status);

export const keys = {
  identity: ["identity"] as const,
  health: ["health"] as const,
  metrics: (windowDays: number) => ["metrics", windowDays] as const,
  runs: (params: unknown) => ["runs", params] as const,
  run: (id: string) => ["run", id] as const,
  tickets: (params: unknown) => ["tickets", params] as const,
  ticket: (id: string) => ["ticket", id] as const,
  documents: ["documents"] as const,
  approvals: ["approvals"] as const,
  approval: (id: string) => ["approval", id] as const,
  audit: (params: unknown) => ["audit", params] as const,
  evalBatches: ["evalBatches"] as const,
  evalBatch: (id: string) => ["evalBatch", id] as const,
  agentConfig: ["agentConfig"] as const,
};

/* ---------------------------------------------------------------- identity */

export function useIdentity(enabled: boolean) {
  return useQuery({
    queryKey: keys.identity,
    queryFn: ({ signal }) => api.get<Identity>("/api/me", undefined, signal),
    enabled,
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: ({ signal }) => api.get<Health>("/api/health", undefined, signal),
    refetchInterval: 15000,
    retry: false,
  });
}

/* --------------------------------------------------------------- dashboard */

export function useMetrics(windowDays: number) {
  return useQuery({
    queryKey: keys.metrics(windowDays),
    queryFn: ({ signal }) =>
      api.get<MetricsSummary>("/api/metrics/summary", { window_days: windowDays }, signal),
    refetchInterval: POLL.dashboard,
  });
}

/* -------------------------------------------------------------------- runs */

export interface RunFilters {
  status?: string;
  limit?: number;
  offset?: number;
  include_eval?: boolean;
}

export function useRuns(filters: RunFilters = {}, enabled = true) {
  return useQuery({
    enabled,
    queryKey: keys.runs(filters),
    queryFn: ({ signal }) =>
      api.get<RunPage>("/api/runs", { ...filters } as Record<string, string>, signal),
  });
}

export function useRun(id: string | undefined) {
  return useQuery({
    queryKey: keys.run(id ?? ""),
    queryFn: ({ signal }) => api.get<Run>(`/api/runs/${id}`, undefined, signal),
    enabled: Boolean(id),
    // Poll while the run is moving; stop the moment it lands. `false` is what
    // TanStack takes as "do not schedule another".
    refetchInterval: (query) => (isTerminal(query.state.data?.status) ? false : POLL.run),
  });
}

/* ----------------------------------------------------------------- tickets */

export interface TicketFilters {
  status?: string;
  department?: string;
  service?: string;
  is_eval_seed?: boolean;
}

export function useTickets(filters: TicketFilters = {}, enabled = true) {
  return useQuery({
    enabled,
    queryKey: keys.tickets(filters),
    queryFn: ({ signal }) =>
      api.get<Ticket[] | { tickets: Ticket[] }>(
        "/api/tickets",
        filters as Record<string, string>,
        signal,
      ),
    // The endpoint returns a bare list; tolerate a wrapped shape so a future
    // pagination change does not blank the screen.
    select: (data): Ticket[] => (Array.isArray(data) ? data : (data.tickets ?? [])),
  });
}

export function useTicket(id: string | undefined) {
  return useQuery({
    queryKey: keys.ticket(id ?? ""),
    queryFn: ({ signal }) => api.get<Ticket>(`/api/tickets/${id}`, undefined, signal),
    enabled: Boolean(id),
  });
}

export interface NewTicket {
  title: string;
  description: string;
  department?: string;
  service?: string;
  priority?: string;
}

export function useCreateTicket() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NewTicket) => api.post<Ticket>("/api/tickets", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tickets"] }),
  });
}

export function useStartTriage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ticketId: string) => api.post<Run>("/api/runs", { ticket_id: ticketId }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["runs"] });
      void qc.invalidateQueries({ queryKey: ["tickets"] });
    },
  });
}

/* --------------------------------------------------------------- documents */

export function useDocuments() {
  return useQuery({
    queryKey: keys.documents,
    queryFn: ({ signal }) =>
      api.get<KnowledgeDocument[] | { documents: KnowledgeDocument[] }>(
        "/api/documents",
        undefined,
        signal,
      ),
    select: (data): KnowledgeDocument[] =>
      Array.isArray(data) ? data : (data.documents ?? []),
    // Ingestion is a background job, so the list is live only while something
    // is actually being ingested. A ready corpus stops polling entirely.
    refetchInterval: (query) => {
      const docs = query.state.data;
      const list = Array.isArray(docs) ? docs : (docs?.documents ?? []);
      const busy = list.some((d) => d.status === "pending" || d.status === "processing");
      return busy ? POLL.documents : false;
    },
  });
}

export function useUploadDocument() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (form: FormData) => api.upload<KnowledgeDocument>("/api/documents", form),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.documents }),
  });
}

export function useReingest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.post<unknown>(`/api/documents/${id}/reingest`),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.documents }),
  });
}

/* --------------------------------------------------------------- approvals */

export function useApprovals(enabled = true) {
  return useQuery({
    queryKey: keys.approvals,
    queryFn: ({ signal }) =>
      api.get<Approval[] | { approvals: Approval[] }>("/api/approvals", undefined, signal),
    select: (data): Approval[] => (Array.isArray(data) ? data : (data.approvals ?? [])),
    enabled,
    refetchInterval: POLL.approvals,
  });
}

export function useApproval(id: string | undefined) {
  return useQuery({
    queryKey: keys.approval(id ?? ""),
    queryFn: ({ signal }) => api.get<Approval>(`/api/approvals/${id}`, undefined, signal),
    enabled: Boolean(id),
  });
}

export interface DecisionBody {
  decision: DecisionValue;
  feedback?: string;
  final_values?: ProposedAction[];
}

export function useDecide(approvalId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: DecisionBody) =>
      api.post<Approval>(`/api/approvals/${approvalId}/decision`, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: keys.approvals });
      void qc.invalidateQueries({ queryKey: keys.approval(approvalId) });
      void qc.invalidateQueries({ queryKey: ["runs"] });
      // Tickets too: approving executes a write against the ticket system, so
      // the ticket's status, team and priority all change. Without this a
      // ticket list opened afterwards shows the pre-approval row until the
      // cache goes stale on its own — the screen contradicting the decision
      // the user just made on the previous screen.
      void qc.invalidateQueries({ queryKey: ["tickets"] });
      void qc.invalidateQueries({ queryKey: ["ticket"] });
    },
  });
}

/* ------------------------------------------------------------------- audit */

export interface AuditFilters {
  run_id?: string;
  actor?: string;
  tool?: string;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}

export function useAudit(filters: AuditFilters = {}, enabled = true) {
  return useQuery({
    queryKey: keys.audit(filters),
    queryFn: ({ signal }) =>
      api.get<AuditPage>("/api/audit", filters as Record<string, string>, signal),
    enabled,
  });
}

/* -------------------------------------------------------------------- eval */

export function useEvalBatches(enabled = true) {
  return useQuery({
    queryKey: keys.evalBatches,
    queryFn: ({ signal }) => api.get<EvalBatch[]>("/api/eval/batches", undefined, signal),
    enabled,
  });
}

export function useEvalBatch(id: string | undefined) {
  return useQuery({
    queryKey: keys.evalBatch(id ?? ""),
    queryFn: ({ signal }) =>
      api.get<EvalBatchDetail>(`/api/eval/batches/${id}`, undefined, signal),
    enabled: Boolean(id),
    refetchInterval: (query) =>
      query.state.data?.status === "running" ? POLL.evalBatch : false,
  });
}

export function useStartEvalBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<EvalBatch>("/api/eval/run"),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.evalBatches }),
  });
}

/* ------------------------------------------------------------------ config */

export function useAgentConfig() {
  return useQuery({
    queryKey: keys.agentConfig,
    queryFn: ({ signal }) => api.get<AgentConfig>("/api/config/agent", undefined, signal),
    staleTime: 5 * 60 * 1000,
  });
}
