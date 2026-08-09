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
 │  │ React dashboard (10 role-based screens)              │  │
 │  └───────────────────────┬──────────────────────────────┘  │
 │                          │ /api (JSON)                     │
 │  ┌───────────────────────▼──────────────────────────────┐  │
 │  │ FastAPI backend                                       │  │
 │  │  - auth middleware (OAuth2 → session/JWT)             │  │
 │  │  - tenant filter (org_id on every query)              │  │
 │  │  - routers: docs, tickets, runs, approvals, metrics   │  │
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
- **React dashboard** — only thing users touch. Never talks to the DB directly. Screens shown depend on role.
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
| tickets | id, org_id, title, description, department, service, priority, status, external_ref, is_eval_seed, created_by | the issues |
| runs | id, org_id, ticket_id, status, agent_version, confidence, output jsonb, checkpoint ref | one triage execution |
| approvals | id, org_id, run_id, approver_user_id, decision, original_proposal jsonb, final_values jsonb, feedback, risk_class, decided_at, created_at | human decisions |
| audit_log | id, org_id, run_id, actor, tool, payload jsonb, result, latency_ms, tokens, cost, created_at | immutable trail |
| eval_results | id, org_id, run_id, ticket_id, expected jsonb, actual jsonb, scores jsonb, judge_model, eval_batch_id | scoring vs labeled set |
| eval_batches | id, org_id, agent_version, started_at, finished_at, summary jsonb | one eval run over the seed set |

Ticket status lifecycle: `new → triaged → actioned` (plus `closed`).

Run status lifecycle: `queued → running → awaiting_approval → executing → completed | rejected | failed`.

---

## Cross-cutting requirements (apply everywhere)

- **Tenant isolation:** `org_id` filter enforced at the query layer on every tenant table. RLS is the production hardening path.
- **Structured output:** every LLM decision validated against a Pydantic schema; raw model text is never trusted for routing.
- **Write-tool contract:** org context, user context, typed args, permission check, idempotency key, timeout, audit record, retry policy, mock implementation, post-execution confirmation.
- **Observability:** every run and every tool call logged (inputs, outputs, latency, tokens, cost).
- **Provider abstraction:** only `backend/app/llm/provider.py` knows which LLM/embedding provider is active.

---

## Production hardening (deferred, tracked)

Things the MVP deliberately does not do. Each is a conscious deferral, not an
oversight — recorded here so they are found on purpose rather than in an
incident.

| Item | MVP behaviour | Hardening step |
|---|---|---|
| Vector search | Exact sequential scan over the org's chunks | HNSW index (below) |
| Tenant isolation | Application-level `org_id` filtering | Postgres RLS (D7, spec 05 §3) |
| Audit payloads | Credential-bearing *keys* redacted | Value-level scanning of user-supplied text (spec 03 §1) |
| Eval judge | Same provider family as triage | A genuinely different model (D5) |

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
