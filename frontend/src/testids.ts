/**
 * The selector contract (spec 07, task 3).
 *
 * Gates bind to these ids and to nothing else — not to copy, not to CSS
 * classes, not to DOM position. A gate that breaks when a heading is reworded
 * or a column is reordered is a gate that gets muted, and a muted gate is
 * worse than no gate because it looks green.
 *
 * This file is why Codex can write G6.1-G6.5 (task 4) against screens that do
 * not exist yet: the interface is agreed before the implementation. **Changing
 * or removing an id here is a spec change**, because it breaks a gate by
 * design. Adding one is free.
 *
 * Convention: `area.thing`, lower-kebab within a segment. Anything
 * parameterised by a row id takes it as an argument so a gate can address one
 * specific row rather than counting them.
 */

export const TID = {
  /* ---- shell ------------------------------------------------------- */
  app: "app",
  sidebar: "sidebar",
  navLink: (route: string) => `nav-${route}`,
  navApprovalCount: "nav-approval-count",
  themeToggle: "theme-toggle",
  userMenu: "user-menu",
  userEmail: "user-email",
  userRoles: "user-roles",
  signOut: "sign-out",
  healthDot: "health-dot",

  /* ---- generic states ---------------------------------------------- */
  loading: "loading",
  empty: "empty",
  error: "error",
  errorDetail: "error-detail",
  retry: "retry",
  forbidden: "forbidden",

  /* ---- login -------------------------------------------------------- */
  loginCard: "login-card",
  loginIdentity: (email: string) => `login-identity-${email}`,
  loginAuth0: "login-auth0",
  loginError: "login-error",

  /* ---- dashboard ---------------------------------------------------- */
  dashboard: "dashboard",
  metric: (key: string) => `metric-${key}`,
  metricValue: (key: string) => `metric-value-${key}`,
  windowSelect: "window-select",
  outcomeChart: "outcome-chart",
  recentRuns: "recent-runs",

  /* ---- documents ---------------------------------------------------- */
  documents: "documents",
  documentRow: (id: string) => `document-${id}`,
  documentStatus: (id: string) => `document-status-${id}`,
  documentReingest: (id: string) => `document-reingest-${id}`,
  uploadOpen: "upload-open",
  uploadInput: "upload-input",
  uploadSubmit: "upload-submit",
  uploadError: "upload-error",

  /* ---- tickets ------------------------------------------------------ */
  tickets: "tickets",
  ticketRow: (id: string) => `ticket-${id}`,
  ticketStatus: (id: string) => `ticket-status-${id}`,
  ticketTriage: (id: string) => `ticket-triage-${id}`,
  ticketFilterStatus: "ticket-filter-status",
  ticketFilterService: "ticket-filter-service",
  ticketFilterSeed: "ticket-filter-seed",
  newTicketOpen: "new-ticket-open",
  newTicketForm: "new-ticket-form",
  newTicketTitle: "new-ticket-title",
  newTicketDescription: "new-ticket-description",
  newTicketDepartment: "new-ticket-department",
  newTicketService: "new-ticket-service",
  newTicketPriority: "new-ticket-priority",
  newTicketSubmit: "new-ticket-submit",

  /* ---- run detail --------------------------------------------------- */
  runDetail: "run-detail",
  runStatus: "run-status",
  runTimeline: "run-timeline",
  runConfidence: "run-confidence",
  runField: (field: string) => `run-field-${field}`,
  runResolution: "run-resolution",
  evidencePanel: "evidence-panel",
  evidenceItem: (chunkId: string) => `evidence-${chunkId}`,
  /** Present only on chunks the model actually cited — G6.3 keys off this. */
  evidenceCited: (chunkId: string) => `evidence-cited-${chunkId}`,
  citationList: "citation-list",
  citation: (chunkId: string) => `citation-${chunkId}`,
  /** Rendered when a citation names a chunk absent from the evidence (G6.3). */
  citationUnresolved: (chunkId: string) => `citation-unresolved-${chunkId}`,
  runProposal: "run-proposal",
  runAudit: "run-audit",

  /* ---- approvals ---------------------------------------------------- */
  approvalInbox: "approval-inbox",
  approvalRow: (id: string) => `approval-${id}`,
  approvalCard: "approval-card",
  approvalRisk: "approval-risk",
  approvalConfidence: "approval-confidence",
  approvalAgentVersion: "approval-agent-version",
  approvalProposal: (index: number) => `approval-proposal-${index}`,
  approvalCurrentValue: (index: number) => `approval-current-${index}`,
  approvalNewValue: (index: number) => `approval-new-${index}`,
  approve: "approve",
  openEdit: "open-edit",
  openReject: "open-reject",
  editForm: "edit-form",
  editValue: (index: number) => `edit-value-${index}`,
  editSubmit: "edit-submit",
  rejectForm: "reject-form",
  rejectFeedback: "reject-feedback",
  rejectSubmit: "reject-submit",
  decisionError: "decision-error",

  /* ---- evaluation --------------------------------------------------- */
  evaluation: "evaluation",
  evalRunBatch: "eval-run-batch",
  evalBatchRow: (id: string) => `eval-batch-${id}`,
  evalBatchDetail: "eval-batch-detail",
  evalMetric: (key: string) => `eval-metric-${key}`,
  evalResultRow: (seedRef: string) => `eval-result-${seedRef}`,

  /* ---- audit -------------------------------------------------------- */
  audit: "audit",
  auditRow: (id: string) => `audit-${id}`,
  auditExpand: (id: string) => `audit-expand-${id}`,
  auditJson: (id: string) => `audit-json-${id}`,
  auditFilterActor: "audit-filter-actor",
  auditFilterTool: "audit-filter-tool",
  auditFilterRun: "audit-filter-run",
  auditNext: "audit-next",
  auditPrev: "audit-prev",
  auditTotal: "audit-total",

  /* ---- agent config -------------------------------------------------- */
  agentConfig: "agent-config",
  configField: (key: string) => `config-${key}`,
  taxonomyGroup: (key: string) => `taxonomy-${key}`,
} as const;

/** Spread onto an element: `<div {...testid(TID.dashboard)} />`. */
export function testid(id: string): { "data-testid": string } {
  return { "data-testid": id };
}
