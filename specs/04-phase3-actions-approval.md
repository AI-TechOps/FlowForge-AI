# Spec: Phase 3 — Write Actions & Human Approval

**Status:** Draft — awaiting review
**Owner:** Muhammad
**Depends on:** 03-phase2-triage-agent.md (approved + built)
**Gate to exit:** Phase 3 definition of done demoed + spec review of Phase 4

## What this phase delivers

The architectural centerpiece: the agent proposes a write action, the workflow pauses durably, a human approves/edits/rejects, and only then does the write execute against the mock ticket system. Full audit of both original and edited proposals.

## Scope (in)

### 1. Data model (migration)
- `approvals`: id, org_id, run_id, approver_user_id, decision (`approved|edited|rejected`), original_proposal jsonb, final_values jsonb, feedback, risk_class, decided_at, created_at
- `runs.status` gains active use of `awaiting_approval` and `executing`.

### 2. Mock ticket system behind an integration interface
- `TicketSystemAdapter` interface: `get_ticket`, `assign_ticket`, `change_priority`, `add_note` — each returns the updated ticket state.
- `MockTicketSystem` implementation backed by our own `tickets` table + an `external_ref`. Deterministic, injectable failures for testing (flag to simulate timeout/500).
- Design rule: nothing outside the adapter knows it's a mock. Swapping in Jira later = new adapter class only.

### 3. The three write tools
- `assign_ticket(ticket_id, team)`, `change_ticket_priority(ticket_id, priority)`, `add_internal_note(ticket_id, note)`.
- Full write-tool contract (from CLAUDE.md): org context, user context, typed args, permission check, **idempotency key** (run_id + tool + args hash; re-execution is a no-op returning the prior result), timeout, audit record, retry policy (max 2, backoff, only on transport errors — never after a confirmed write), mock implementation, **post-execution confirmation** (re-fetch ticket, verify the change landed, record confirmation in audit).

### 4. Durable pause (LangGraph interrupt)
- Graph extends: `... → propose → INTERRUPT(awaiting_approval) → execute → confirm → complete`.
- On propose: checkpoint state to Postgres, set run `awaiting_approval`, create the pending approval record, end the request/job.
- Resume triggered by the approval decision endpoint — a fresh worker loads the checkpoint and continues. Must survive backend restart between pause and resume (this is tested, not assumed).
- Crash recovery: a run stuck in `executing` (worker died mid-execute) is detected on worker startup (executing older than the per-run timeout) and re-enqueued; the idempotency key makes replay safe — the write happens at most once (ties to G3.3).

### 5. Approval endpoints
- `GET /api/approvals?status=pending` — approval inbox (Approver).
- `GET /api/approvals/{id}` — the full approval card payload: proposed action, affected ticket, new values, existing values, evidence, confidence, risk classification, agent_version.
- `POST /api/approvals/{id}/decision` body `{decision: approved|edited|rejected, final_values?, feedback?}`.
  - **approved** → resume graph → execute tool → confirm → run `completed`.
  - **edited** → validate final_values against the tool's Pydantic schema (reject request on invalid) → resume with edited values → execute → confirm → `completed`. Original AND edited proposals both persisted.
  - **rejected** → no write occurs (assert: zero adapter write calls) → feedback recorded → run `rejected`.
- Decisions are one-shot: a second decision on the same approval → 409. Enforced atomically (single compare-and-swap UPDATE on the approval's status, or equivalent row lock) so two concurrent decision requests cannot both win.

### 6. Risk classification
- Simple rule-based `risk_class` on proposals (e.g., priority raise to P1 = high; note-only = low). Stored on the approval; shown on the card. (Keeps "risk classification" from the MVP spec honest without ML scope creep.)

### 7. Optional stretch — reviewer sub-agent (only if ahead of schedule)
- A second LangGraph node/sub-agent critiques the proposal (flags low confidence, weak citation match) and attaches notes to the approval card. Human still decides. Same model, different context. Off by default behind a config flag.

## Scope (out)
- Real Jira/ServiceNow adapters (post-MVP).
- Notifications (email/Slack) to approvers.
- Approval delegation, multi-approver quorum, expiry/escalation (note as future work).
- Auth enforcement of the Approver role on endpoints — threaded but enforced in Phase 4.

## Gates & checks
- **G3.1 Durability:** pause a run, **restart the backend**, then approve — run resumes and completes. (Scripted test.)
- **G3.2 No-write-on-reject:** reject path executes zero adapter write calls (assert via mock call recorder).
- **G3.3 Idempotency:** replaying an approval decision or re-running execute does not double-write (adapter call count = 1).
- **G3.4 Edit integrity:** edited values are schema-validated; both original and edited proposals present in the approval record and audit log.
- **G3.5 Confirmation:** after execute, the re-fetched ticket reflects the change; confirmation recorded in audit.
- **G3.6 Failure handling:** injected adapter timeout → retry per policy → if still failing, run `failed`, approval preserved, no phantom writes.
- **G3.7 One-shot decisions:** a second decision attempt → 409, no state change; two concurrent decision requests → exactly one succeeds and exactly one tool execution occurs (parallel-request test, asserted with the adapter call recorder).

## Definition of done
- Full loop works end to end via API: ticket → triage → proposal → pause → (approve|edit|reject) → (execute+confirm | no-write) → recorded.
- Survives backend restart mid-pause (G3.1).
- All gates G3.1–G3.7 pass with tests.
- The MVP definition-of-done steps 5–9 are now demonstrable via API (frontend comes in Phase 6).

## Risks
- LangGraph checkpoint/resume edge cases. Mitigation: G3.1 is a hard gate; keep graph state minimal and serializable.
- Scope creep into notification/escalation. Mitigation: explicitly out of scope.

## Task plan
*(Filled after spec approval — review gate.)*
