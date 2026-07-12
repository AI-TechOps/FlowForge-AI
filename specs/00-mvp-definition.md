# Spec: FlowForge-AI MVP Definition

**Status:** Approved
**Owner:** FlowForge Code Owners
**Purpose:** The single source of truth for what the FlowForge-AI MVP is and when it is done. Every phase spec derives from this.

## Goal

One coherent enterprise support-triage workflow, end to end, demonstrating RAG, structured LLM output, LangGraph orchestration, tool-calling, human approval, authentication, tenant isolation, background processing, reliability controls, evaluation, observability, and React/FastAPI delivery on Docker/AWS.

## What FlowForge-AI does (the workflow)

A fictional enterprise connects its internal support documentation and ticket-management system. Employees submit support tickets. For a given ticket, FlowForge-AI:

1. Reads the ticket.
2. Retrieves relevant company documentation (RAG).
3. Classifies the issue.
4. Determines urgency and routing.
5. Suggests a resolution.
6. Shows the evidence it used (citations).
7. Proposes a ticket-system update.
8. Pauses for approval.
9. Executes the approved action.
10. Records the complete workflow for auditing and evaluation.

## Personas

### Administrator
Upload company documentation; view ingestion status; configure the ticket workflow; view all workflow runs; review evaluation metrics; minimally manage users and roles.

### Operator
Create or import tickets; start triage workflows; see recommendations and citations; view workflow status.

### Approver
View pending actions; approve, edit, or reject proposed ticket updates; see evidence and reasoning summary; review previous decisions.

A user may hold more than one role.

## User journey (exact)

### Step 1 — Administrator uploads knowledge
Supported MVP formats: PDF, Markdown, plain text.
System: stores the original file; extracts text; splits into chunks; generates embeddings; stores chunks in Postgres/pgvector; records document title, version, page, section; displays ingestion success/failure.

### Step 2 — Operator submits a ticket
Form fields: title, description, requester department, affected service, optional existing priority. Seeded demo tickets also provided.

### Step 3 — Agent begins triage
Produces a structured result:
```json
{
  "summary": "Employee cannot connect to the corporate VPN",
  "category": "network_access",
  "urgency": "high",
  "recommended_team": "IT Infrastructure",
  "suggested_priority": "P2",
  "recommended_resolution": "...",
  "confidence": 0.88,
  "requires_approval": true,
  "citations": []
}
```

### Step 4 — Agent retrieves evidence
Run page shows: retrieved documents; relevant excerpts; document title; page/section; retrieval score; which claims use which sources.
**Grounding rule: the recommendation cannot be considered grounded unless it includes at least one valid citation.**

### Step 5 — Agent proposes an action
MVP action can be: assign ticket to a team; change priority; add an internal note with the recommended resolution. Targets a simulated ticket system, built behind an integration interface so Jira/ServiceNow can replace the mock later.

### Step 6 — Workflow pauses
Pending approval card displays: proposed action; affected ticket; new values; existing values; evidence; confidence; risk classification; agent version; approve/edit/reject buttons.

### Step 7 — Approver decides
- **Approve:** workflow resumes; tool executes; updated ticket retrieved for confirmation; run marked completed.
- **Reject:** no external write; rejection + feedback recorded; run marked rejected.
- **Edit:** edited values validated; approved edited action executes; both original and edited proposals remain in the audit record.

### Step 8 — Dashboard records performance
Metrics: total runs; successful runs; failed runs; waiting approvals; average latency; average model tokens per run; tool success rate; approval rate; human edit rate; human rejection rate; evaluation accuracy; retrieval success; estimated model cost.

## Screens (build ONLY these)
Login; Dashboard; Knowledge documents; Upload document; Tickets; New ticket; Workflow run detail; Approval inbox; Evaluation results; Audit log.

Not in MVP: drag-and-drop agent builder. Agent config lives in code + DB records; a read-only config page is sufficient.

## Tools (five)
- `search_company_knowledge` — auto-executes
- `get_ticket` — auto-executes
- `assign_ticket` — requires approval
- `change_ticket_priority` — requires approval
- `add_internal_note` — requires approval

Every write tool must have: organization context, user context, typed arguments, permission check, idempotency key, timeout, audit record, retry policy, mock implementation, confirmation request after execution.

## Definition of done

The MVP is complete when this demonstration works end to end:

1. Admin logs in.
2. Admin uploads an IT policy PDF.
3. The document is successfully indexed.
4. Operator submits a VPN ticket.
5. Agent runs triage and produces the structured result.
6. Run detail shows retrieved evidence with at least one valid citation.
7. Agent proposes an action and the workflow pauses.
8. Approver reviews and approves.
9. The write tool executes against the mock system, the updated ticket is retrieved for confirmation, and the run is marked completed.
10. The dashboard reflects the run and the audit log captures the full workflow.

## Locked architecture decisions
- Tenant isolation: single Postgres, `org_id` on every table, application-level filtering. RLS is the production hardening step.
- Durable pause: LangGraph Postgres checkpointing; the pause is a real interrupt.
- Eval: seeded labeled set of ~15-20 tickets with known-correct category/urgency/team; agent output scored against it.
- Grounding enforced in code, not just prompt.

## Out of scope for MVP
Drag-and-drop builder; real Jira/ServiceNow integration (mock only); multi-language docs; fine-tuning; streaming token UI; SSO beyond one OAuth2 provider; more than three document formats.
