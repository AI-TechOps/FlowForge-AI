# Spec: Phase 2 — Triage Agent

**Status:** Draft — awaiting review
**Owner:** FlowForge Code Owners
**Depends on:** 02-phase1-rag.md (approved + built)
**Gate to exit:** Phase 2 definition of done demoed + spec review of Phase 3

## What this phase delivers

The LangGraph triage agent: given a ticket, it reads the ticket, retrieves evidence, and produces the validated structured triage result with citations. No write actions yet, no approval yet — the run ends at "proposal produced." Runs execute as background jobs and are fully logged.

## Scope (in)

### 1. Data model (migration)
- `tickets`: id, org_id, title, description, department, service, priority, status (`new|triaged|actioned|closed`), external_ref, is_eval_seed, created_by, created_at
- `runs`: id, org_id, ticket_id, status (`queued|running|awaiting_approval|executing|completed|rejected|failed`), agent_version, confidence, output jsonb, error, started_at, finished_at
- `audit_log`: id, org_id, run_id, actor (`agent|user:<id>|system`), tool, payload jsonb, result jsonb, latency_ms, tokens_in, tokens_out, cost_estimate, created_at
- Audit payload rule: payloads must never contain secrets (API keys, tokens, connection strings) — provider credentials live in env/config and are never part of tool args or logged prompts. Demo/ticket data is fictional by design; PII redaction in audit payloads is noted as production hardening, not MVP scope.

### 2. Ticket endpoints + form backing
- `POST /api/tickets` (Operator) — the New Ticket fields from the MVP spec. Input limits enforced server-side: title ≤ 200 chars, description ≤ 10,000 chars.
- `GET /api/tickets` with filters (status, department, service, is_eval_seed — the Phase 6 Tickets screen uses these), `GET /api/tickets/{id}`.
- Eval seed loader: script inserts `fixtures/eval_tickets.json` (committed in Phase 1) into `tickets` with `is_eval_seed=true`.
- `POST /api/tickets/{id}/triage` → creates a `run` (queued), enqueues background job, returns run id.
- `GET /api/runs/{id}` — full run detail: status, structured output, evidence used, audit entries.

### 3. LangGraph triage graph
Nodes: `load_ticket → retrieve_evidence → classify → ground_check → propose` (propose = final node this phase; it records the proposal in `runs.output`, status `completed`).
- Postgres checkpointer configured from the start (even though the durable pause is Phase 3) — the plumbing goes in now.
- `agent_version` string constant, stamped on every run.

### 4. Tools (the two read tools)
- `search_company_knowledge(query, k)` — wraps Phase 1 retrieve; auto-executes; logged to audit_log. `k` clamped server-side (≤ 20) regardless of what the model asks for.
- `get_ticket(ticket_id)` — reads the ticket; auto-executes; logged.
- Tool registry pattern: tools declared with typed args (Pydantic), org/user context injected, permission check stub, audit wrapper. (Write tools reuse this in Phase 3 — build the contract now.)

### 5. Structured output + grounding gate
- Triage result validated against a Pydantic schema exactly matching the MVP JSON (summary, category, urgency, recommended_team, suggested_priority, recommended_resolution, confidence, requires_approval, citations[]).
- `category`, `urgency`, `suggested_priority`, `recommended_team` are enums/known values (config), not free text.
- Citations: list of {chunk_id, document_title, page, section, claim}. **Grounding gate in code:** zero valid citations → run status `failed` with reason `ungrounded`, never `completed`.
- `requires_approval` is derived in code from the proposed tool's gating (always true for the three write tools) — the LLM's own value for this field is informational and never trusted for control flow.
- LLM output parsing failures: one retry with repair prompt, then `failed` with reason `schema_invalid`.

### 6. Reliability controls
- Per-run timeout (config). LLM call retries with backoff (max 2). Concurrency limit on the worker.
- Every LLM call and tool call logged with latency/tokens/cost estimate.

## Scope (out)
- No write tools, no proposal execution, no approval (Phase 3).
- No reviewer sub-agent (optional Phase 3 stretch).
- No auth enforcement on endpoints yet (Phase 4) — but org context is already threaded through everything.
- No frontend screens beyond what exists (Phase 6); testing via API.

## Gates & checks
- **G2.1 Schema gate:** 100% of completed runs have Pydantic-valid output; invalid output can never reach `completed`.
- **G2.2 Grounding gate:** a run against an empty knowledge base fails as `ungrounded` (test exists).
- **G2.3 Enum gate:** category/urgency/priority/team outside the allowed sets → repair retry → `failed` if still invalid.
- **G2.4 Eval smoke:** run the agent over the seed set; ≥70% category accuracy against labels (baseline bar — formal eval is Phase 5). Record the number.
- **G2.5 Audit completeness:** every run has audit entries for every tool call and LLM call — a script compares the run's graph trace to its audit rows (counts and tool names must match), plus one human end-to-end spot-check.
- **G2.6 Tenant isolation:** run for org A cannot retrieve or read org B data.

## Definition of done
- Operator can create a ticket and trigger triage via API; run executes in background.
- Run detail returns validated structured output + citations + evidence.
- Grounding enforced in code; failure paths produce typed reasons.
- G2.1–G2.6 pass; seed-set baseline accuracy recorded in the repo (e.g., `eval/baseline.md`).

## Risks
- Local model (Ollama) may struggle with strict JSON. Mitigation: repair-retry loop; keep schemas flat; validate with the dev model early — this is the point of G2.4.
- Prompt drift across phases. Mitigation: prompts live in versioned files, `agent_version` bumps on change.

## Task plan
*(Filled after spec approval — review gate.)*
