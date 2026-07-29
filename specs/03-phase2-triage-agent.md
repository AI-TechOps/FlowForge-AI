# Spec: Phase 2 — Triage Agent

**Status:** Approved (2026-07-28, FlowForge Code Owners)
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

## Key decisions (confirmed 2026-07-28 by the FlowForge Code Owners)

1. **Structured output: provider-native JSON-schema mode.** Ollama's `format: <schema>` / OpenAI's `response_format: json_schema`, then Pydantic validation, then one repair retry. The provider interface gains `complete_structured(prompt, schema)` so the choice stays behind the factory (D11). Prompt-only JSON was rejected as too flaky on small local models; LangChain's `with_structured_output` was rejected as a second uncontrolled abstraction.
2. **Deterministic graph control flow.** The fixed node list drives tool calls directly; there is no ReAct-style LLM-chooses-tools loop. Tools still pass through the registry + audit wrapper. Rationale: predictable step counts keep G2.5 (audit completeness) meaningful and make the Phase 3 durable pause tractable.
3. **CI runs the LLM gates on a fake completion provider.** Extends `LLM_PROVIDER=fake` from D15: deterministic, schema-valid triage output derived from ticket text, plus injectable invalid output (bad enum / unparseable / zero citations) so G2.1–G2.3 prove the gates actually fail closed. Refused when `APP_ENV=prod`, exactly like fake embeddings.
4. **Taxonomy lives in runtime code.** `backend/app/agents/taxonomy.py` is the source of truth for category / urgency / priority / team enums; a Codex-owned test asserts `fixtures/enterprise/taxonomy.json` matches it exactly. This preserves the D6 isolation guard (`backend/app/` may never import `fixtures/`) while keeping one authority and catching drift at a gate.
5. **Two Postgres drivers, deliberately.** `langgraph-checkpoint-postgres` requires psycopg3; the application stays on asyncpg (D14). We add psycopg for the checkpointer only rather than hand-writing an asyncpg checkpointer — the durable pause (Phase 3) is the architectural centerpiece and is not the place for a bespoke persistence layer. Documented so the extra dependency is not mistaken for drift.
6. **Dev triage model:** `TRIAGE_MODEL` config, default `llama3.1:8b` on Ollama (separate from `EMBEDDING_MODEL`). Phase 5's eval judge must be a *different* model (D5).

## Task plan (approved 2026-07-28 by the FlowForge Code Owners)

One atomic commit per task. **[CC]** = Claude Code, **[CX]** = Codex.

1. **[CC] Taxonomy + triage schema** — `app/agents/taxonomy.py` (the four enums) and `app/agents/schema.py` (`TriageResult`, `Citation`) matching the MVP JSON exactly.
2. **[CC] Data model** — `tickets`, `runs`, `audit_log` models + migration 0003 with working `downgrade()`.
3. **[CC] Structured completion** — `complete_structured()` on Ollama/OpenAI providers; fake provider extended with deterministic schema-valid output + injectable failure modes.
4. **[CC] Audit service** — one write path recording every tool call and LLM call (payload, result, latency, tokens, cost estimate); no-secrets rule enforced at the boundary.
5. **[CC] Tool registry + read tools** — typed Pydantic args, org/user context injection, permission-check stub, audit wrapper; `search_company_knowledge` (k clamped ≤20) and `get_ticket`.
6. **[CC] Ticket endpoints + seed loader** — `POST /api/tickets` (title ≤200, description ≤10,000), `GET /api/tickets` with filters, `GET /api/tickets/{id}`; script loading `fixtures/eval_tickets.json` with `is_eval_seed=true`.
7. **[CC] Triage graph** — LangGraph `load_ticket → retrieve_evidence → classify → ground_check → propose`, Postgres checkpointer wired (psycopg), `agent_version` stamped on every run.
8. **[CC] Grounding gate + repair** — zero valid citations → `failed`/`ungrounded`; schema or enum violation → one repair retry → `failed`/`schema_invalid`; `requires_approval` derived in code, never trusted from the model.
9. **[CC] Run orchestration** — `POST /api/tickets/{id}/triage` → queued run + arq job; `GET /api/runs/{id}` (status, output, evidence, audit); per-run timeout, LLM retry/backoff, worker concurrency limit.
10. **[CX] Gate tests** — `tests/phase2/` covering G2.1–G2.6 plus the taxonomy↔fixtures parity test.
11. **[CX] Adversarial pass + cold diff review.**
12. **[CC] Eval baseline + CI + docs** — run the agent over the seed set, record G2.4's number in `eval/baseline.md`, wire the Phase 2 gates into CI, update README.
