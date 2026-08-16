# FlowForge-AI — High Level Design (HLD)

Four views: (1) system architecture, (2) end-to-end triage workflow, (3) RAG ingestion pipeline, (4) data model. Read them in order — View 1 is the *what*, View 2 the *behavior*, View 3 the *preparation*, View 4 the *state*.

---

## View 1 — System architecture

```
                        ┌─────────┐
                        │  Users  │ (Admin / Operator / Approver — humans)
                        └────┬────┘
                             │ HTTPS
 ┌───────────────────────────▼───────────────────────────────┐
 │                    FlowForge-AI platform                   │
 │                                                            │
 │  ┌──────────────────────────────────────────────────────┐  │
 │  │ React SPA — 10 role-based screens + config panel      │  │
 │  │ built by Vite, served by nginx, which proxies /api    │  │
 │  └───────────────────────┬──────────────────────────────┘  │
 │                          │ /api (JSON)                     │
 │  ┌───────────────────────▼──────────────────────────────┐  │
 │  │ FastAPI backend                                       │  │
 │  │  - auth middleware (OAuth2 → session/JWT)             │  │
 │  │  - tenant filter (org_id on every query)              │  │
 │  │  - routers: docs, tickets, runs, approvals,           │  │
 │  │    eval, metrics, audit, config                       │  │
 │  └──────┬──────────────────────────┬────────────────────┘  │
 │         │                          │                        │
 │  ┌──────▼──────────┐      ┌────────▼─────────┐             │
 │  │ LangGraph agent │─────▶│ Tool registry     │             │
 │  │ (triage graph,  │      │ 5 typed tools     │             │
 │  │  checkpointed)  │      │ 2 auto / 3 gated  │             │
 │  └──────┬──────────┘      └────────┬─────────┘             │
 │         │                          │                        │
 │  ┌──────▼──────────┐      ┌────────▼─────────┐             │
 │  │ Postgres +      │      │ Redis             │             │
 │  │ pgvector        │      │ cache + job queue │             │
 │  │ (state, vectors,│      └──────────────────┘             │
 │  │  runs, audit)   │                                        │
 │  └─────────────────┘                                        │
 └───────┬──────────────────┬───────────────────┬─────────────┘
         │                  │                   │
   ┌─────▼─────┐     ┌──────▼──────┐    ┌───────▼────────┐
   │ LLM API   │     │ Auth        │    │ Ticket system  │
   │ Ollama /  │     │ provider    │    │ (MOCK behind   │
   │ OpenAI    │     │ (OAuth2)    │    │  interface)    │
   └───────────┘     └─────────────┘    └────────────────┘
```

**Layer responsibilities:**
- **React dashboard** — only thing users touch. Never talks to the DB directly. Screens shown depend on role, **presentationally only**: the sidebar hides what a role cannot use, and the server independently refuses it (D21 decision 11). Routing is React Router, every read is a TanStack Query — including the polls that carry run status and the approval inbox, since the durable pause makes "wait for this to settle" the dominant interaction (D21 decisions 1 and 3). The container ships a production build behind nginx rather than a dev server, so Playwright and Phase 7 both exercise the artifact that deploys (D21 decision 7).
- **FastAPI backend** — the security boundary. Authenticates (who you are) and tenant-filters (which org you belong to). Every query is scoped by `org_id`.
- **LangGraph agent** — the state machine running triage steps in order. Checkpointed to Postgres so runs survive process restarts and approval waits.
- **Tool registry** — the only actions the agent can take. 2 read tools auto-execute; 3 write tools are approval-gated. The agent cannot act outside the registry.
- **Postgres/pgvector** — everything durable: documents, chunks, embeddings, tickets, runs, approvals, audit, eval results, agent checkpoints.
- **Redis** — fast disposable state: cache, background job queue (ingestion jobs, agent runs).
- **External (not owned):** LLM (swappable via provider factory — Ollama dev, OpenAI validation), OAuth2 provider, and the ticket system — *mocked behind an integration interface* so Jira/ServiceNow can replace the mock with a one-adapter change.

---

## View 2 — End-to-end triage workflow

```
 Ticket submitted (Operator)
        │
        ▼
 Read ticket ................. get_ticket (auto)
        │
        ▼
 Retrieve evidence ........... search_company_knowledge (auto, RAG)
        │
        ▼
 Classify + score ............ structured output (Pydantic-validated)
        │                      {summary, category, urgency, recommended_team,
        │                       suggested_priority, recommended_resolution,
        │                       confidence, requires_approval, citations[]}
        ▼
 GATE: grounding check ....... ≥1 valid citation or run fails as ungrounded
        │
        ▼
 Propose action .............. assign_ticket | change_ticket_priority | add_internal_note
        │
        ▼
 ╔═══════════════════════════════════════════╗
 ║ PAUSE FOR APPROVAL — durable interrupt    ║   ◀── LangGraph checkpoint → Postgres
 ║ (survives hours; request ends here)       ║
 ╚═══════╦══════════════════════╦════════════╝
         │ approve / edit       │ reject
         ▼                      ▼
 Execute write tool      No write occurs
 (idempotency key,       Feedback recorded
  timeout, retry)        Run → rejected ──────┐
         │                                    │
         ▼                                    │
 Confirm: re-fetch ticket                     │
 Run → completed                              │
         │                                    │
         ▼                                    ▼
 ┌────────────────────────────────────────────────┐
 │ Record run: audit log + evaluation log         │
 │ (EVERY path is recorded — approve/edit/reject) │
 └────────────────────────────────────────────────┘
```

**Three properties that make this real, not a demo:**
1. **The pause is a durable interrupt.** State checkpoints to Postgres; the approver may decide hours later; the run resumes exactly where it stopped.
2. **No write without approval.** Read tools auto-run; write tools cannot execute until a human approves. Reject = zero external writes.
3. **Every path records.** Approve, edit, reject all converge on audit + eval logging. Nothing the agent does is invisible.

---

## View 3 — RAG ingestion pipeline

```
 Admin uploads file (PDF / Markdown / plain text)
        │
        ▼
 Store original file  ──────────── (object storage / disk; keep the source)
        │
        ▼
 Extract text ─────────────────── preserve page + section structure
        │
        ▼
 Split into chunks ────────────── overlapping windows; carry metadata
        │
        ▼
 Generate embeddings ──────────── one vector per chunk (embedding model
        │                          via provider factory)
        ▼
 Store in pgvector ────────────── chunk text + vector + document title,
        │                          version, page, section, org_id
        ▼
 Report ingestion status ──────── success/failure visible to Admin
```

**Critical detail:** page + section metadata is preserved end-to-end. That metadata is what makes **citations** possible later — the agent can point at "VPN Access Policy, page 3, §2.1". Skip metadata at ingestion and honest grounding becomes impossible. Ingestion and citation are the same design decision viewed from two ends.

Ingestion runs as a **background job** (Redis queue) — uploads return immediately with a job id; status polls or pushes to the Admin screen.

---

## View 4 — Data model (ER overview)

```
 organizations 1──* users 1──* user_roles   (org_id on every tenant table)
 organizations 1──* documents 1──* chunks(embedding vector, page, section)
 organizations 1──* tickets   1──* runs 1──* approvals
                                        1──* audit_log
                                        1──* eval_results
 organizations 1──* eval_batches 1──* eval_results
```

| Table | Key columns | Purpose |
|---|---|---|
| organizations | id, name | tenant root |
| users | id, org_id, email, auth_subject | humans; auth_subject linked in Phase 4 |
| user_roles | user_id, role, created_at | role grants (admin/operator/approver); one row per grant, PK (user_id, role) |
| documents | id, org_id, title, version, status, file_ref, error_message | uploaded knowledge |
| chunks | id, org_id, document_id, chunk_index, text, embedding vector, embedding_model, page, section, token_count | RAG units; org_id denormalized for direct tenant filtering |
| tickets | id, org_id, title, description, department, service, priority, assigned_team, internal_notes jsonb, status, external_ref, is_eval_seed, created_by | the issues. `department` is the REQUESTER's org unit; `assigned_team` is the write target of `assign_ticket` — different concepts |
| runs | id, org_id, ticket_id, status, agent_version, confidence, output jsonb, evidence jsonb, failure_reason, attempts, triggered_by, eval_batch_id, checkpoint ref | one triage execution. `attempts` survives Redis losing the job, which is what lets a poisoned run dead-letter; `eval_batch_id` is the *only* thing that selects the eval graph, and because that graph has no execute node a run marked eval by mistake stops at a proposal rather than writing unapproved (D19 decision 2) |
| approvals | id, org_id, run_id, status, approver_user_id, decision, original_proposal jsonb, final_values jsonb, feedback, risk_class, decided_at, created_at | human decisions. `status` (pending/decided) is separate from `decision` so the one-shot rule is a single compare-and-swap |
| tool_executions | id, org_id, run_id, tool, args_hash, args jsonb, result jsonb, confirmed | idempotency ledger; UNIQUE (run_id, tool, args_hash) is the at-most-once guarantee for write tools |
| audit_log | id, org_id, run_id, actor, tool, payload jsonb, result, latency_ms, tokens, cost, created_at | immutable trail |
| eval_results | id, org_id, batch_id, run_id, ticket_id, seed_ref, expected jsonb, actual jsonb, scores jsonb, judge_model, failure_reason | scoring vs labeled set. UNIQUE (batch_id, ticket_id): re-scoring updates in place, which is what makes "the same batch re-scored gives identical accuracy" a claim about determinism rather than about row counts (G5.1) |
| eval_batches | id, org_id, agent_version, llm_provider, triage_model, judge_model, status, total_tickets, started_at, finished_at, summary jsonb | one eval run over the seed set. The summary is computed once at finalize and never recomputed on read, so a recorded batch stays a fixed historical fact even after the scoring code changes (G5.5). `llm_provider` is recorded because the fake provider runs under the configured `TRIAGE_MODEL` name — without it a harness batch and a real one are indistinguishable in the regression table |

`runs.eval_batch_id` marks a run as part of a batch and is the **only** thing
that selects the eval graph. Deliberately one column rather than a separate
`is_eval` boolean: two markers can disagree, and the asymmetry makes a single
marker safe — a run wrongly marked eval degrades to "proposes and stops", never
to "writes without approval", because the eval graph has no execute node. The
same column also gates the shared finalizer's `new → triaged` ticket write, so
"eval writes nothing back" holds in lifecycle code as well as in topology.

Ticket status lifecycle: `new → triaged → actioned` (plus `closed`).

Run status lifecycle: `queued → running → awaiting_approval → executing → completed | rejected | failed`.

The pause between `awaiting_approval` and `executing` is a LangGraph `interrupt()` checkpointed to
Postgres, not an in-memory wait: the job ends, and a *different* worker process resumes from the
checkpoint whenever the human decides. LangGraph owns its own checkpoint tables (created by
`saver.setup()`, deliberately outside Alembic — they are the library's schema, versioned with it).

---

## Cross-cutting requirements (apply everywhere)

- **Tenant isolation:** `org_id` filter enforced at the query layer on every tenant table. RLS is the production hardening path.
- **Structured output:** every LLM decision validated against a Pydantic schema; raw model text is never trusted for routing.
- **Write-tool contract:** org context, user context, typed args, permission check, idempotency key, timeout, audit record, retry policy, mock implementation, post-execution confirmation.
- **Observability:** every run and every tool call logged (inputs, outputs, latency, tokens, cost). Model calls too, the judge included — the eval spends tokens like anything else, and a cost figure that quietly omits a fifth of the calls is worse than none. Logs are JSON with `run_id`/`org_id` on every line in both the API and the worker, so one run's whole life is a single query across two containers.
- **Measurement:** the deterministic scorer (`app/eval/scoring.py`) is pure functions only — no clock, no database, no model. That is what makes a recorded batch re-scorable to the same numbers, and therefore what makes two `agent_version`s comparable (G5.1, G5.5). Judgement lives in `app/eval/judge.py` on a *different model family* from triage (D5); config validation refuses a judge in the **same family** as triage, comparing the model name minus its `:tag` and provider prefix — exact-name comparison let `llama3.1:8b` be judged by `llama3.1:70b`, which is the same weights lineage and therefore the same blind spots (D20 finding 5).
- **Provider abstraction:** only `backend/app/llm/provider.py` knows which LLM/embedding provider is active, and only `backend/app/auth/provider.py` knows which identity provider is (D18 decision 1). In both cases the *verification/validation* path is shared across providers; only the source of the key or the completion differs.
- **Authentication:** every `/api` route except `/api/health` requires a bearer token. `org_id` is derived from the authenticated principal — no header, query parameter, or body field can influence it (G4.5).
- **Authorization:** roles come from `user_roles`, never from token claims, so a revoked role takes effect on the next request. The role matrix is expressed once as named dependencies in `backend/app/auth/principal.py`. The SPA mirrors that matrix in `frontend/src/shell/Shell.tsx` for navigation only; the two are copied rather than derived, and where they disagree the server wins and the user sees a refusal instead of a broken screen.
- **Gate selectors:** browser gates bind to `data-testid` values registered in `frontend/src/testids.ts`, never to copy or CSS classes — a gate that breaks when a heading is reworded is a gate that gets muted, and a muted gate is worse than none because it looks green. Changing an id there is a spec change.

---

## Production hardening (deferred, tracked)

Things the MVP deliberately does not do. Each is a conscious deferral, not an
oversight — recorded here so they are found on purpose rather than in an
incident.

| Item | MVP behaviour | Hardening step |
|---|---|---|
| Vector search | Exact sequential scan over the org's chunks | HNSW index (below) |
| Tenant isolation | Application-level `org_id` filtering | Postgres RLS (D7, spec 05 §3) |
| Tenant-consistent foreign keys | Child rows carry `org_id` and are filtered on it; the FK alone does not enforce the pair | Composite FKs (e.g. `eval_results → eval_batches(id, org_id)`) so a cross-tenant parent/child pair cannot be written at all. Lands with RLS — worth doing across every tenant table at once, not one table at a time (D20 finding 1) |
| Audit payloads | Credential-bearing *keys* redacted | Value-level scanning of user-supplied text (spec 03 §1) |
| hit@k document identity | Matched on normalised title (`MD-IT-001` ↔ "MD IT 001 vpn access policy") | A `documents.external_ref` column; retitling a document silently drops hit@k today |
| Eval answer key | A JSON file mounted read-only into the containers | Unchanged by design — keeping the labels out of Postgres is what stops the agent reading them |
| Token storage (SPA) | `sessionStorage`, cleared on 401 | httpOnly cookie + backend session, which XSS cannot read |
| User and role management | Roles seeded by `scripts/seed.py`; no screen, no endpoint | `GET/POST/DELETE /api/users` plus an admin screen. Deliberately out of the MVP (D21 decision 5) — the ten-screen list omits it, and building it means new backend write APIs |
| Dead-lettered runs | Terminal, visible on the run detail page | An operator-facing requeue action |

### HNSW index on `chunks.embedding`

`chunks.embedding` carries no ANN index today — only btree on `id`,
`document_id`, `org_id` — so every retrieval is an exact scan. At demo scale
(~10² chunks per org) that is both fast and *more* accurate than approximate
search, and it avoids index build time and recall tuning. It does not survive
production volume.

```sql
CREATE INDEX CONCURRENTLY ix_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

Three things to get right when this lands:

- **Match the operator class to the query.** Retrieval uses cosine distance
  (`backend/app/rag/retrieve.py`), so the index must be `vector_cosine_ops`. A
  mismatched op class is silently ignored and the scan stays sequential.
- **Filtered recall is the real trap.** Every query filters by `org_id` first,
  and an HNSW scan that post-filters can return fewer than `k` rows — or miss
  the best ones — for a small tenant inside a large table. pgvector 0.8 (0.8.5
  is what we run) added iterative index scans for exactly this; enable
  `hnsw.iterative_scan` rather than assuming the plain index is correct under a
  filter.
- **Re-index on any embedding change.** Model or dimension changes invalidate
  both the vectors and the index; `chunks.embedding_model` exists to make that
  detectable.

Worth measuring before adopting: below roughly 10⁴–10⁵ chunks per org the exact
scan is usually the better answer, so this should be driven by a benchmark on
real volume rather than by default.
