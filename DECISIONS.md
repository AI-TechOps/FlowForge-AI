# FlowForge-AI — Decisions & Rationale

This document records the decisions made while planning FlowForge-AI, and the reasoning behind them. It exists so anyone (human or AI) picking up the project understands not just *what* was decided but *why*. Specs say what to build; this says why it's built that way.

---

## D1 — Product framing

FlowForge-AI is an enterprise AI workflow automation platform, built as a portfolio capstone for a Forward-Deployed Engineer role. The FDE framing matters: it's customer-facing engineering that ships AI into a customer's real, messy internal systems. The project is deliberately a superset of simpler GenAI projects (RAG, agents, tool-calling) plus the evaluation and observability layer that separates a demo from a deployable system.

The concrete scenario: a fictional enterprise connects its internal support documentation and ticket system. Employees file support tickets. FlowForge-AI reads a ticket, retrieves relevant company knowledge via RAG, classifies and routes it, proposes a resolution grounded in cited evidence, pauses for human approval, executes the approved action against the ticket system, and records the whole workflow for audit and evaluation.

---

## D2 — Policy documents vs. tickets are different things (and why RAG needs both)

Two distinct kinds of data, often confused:

- **Policy documents (company knowledge):** reference material the company already has — "VPN Access Policy," "IT Incident Priority Guidelines," "Password Reset Procedure." Uploaded once by an Administrator. Chunked, embedded, stored in pgvector. These are the *source of truth* the agent reads from. They don't change per ticket.
- **Tickets (issues):** a specific problem a real employee is reporting right now — "Can't connect to VPN, keeps timing out, have a client demo at 2pm." Filed by an Operator. Each is a unique event.

How they work together: the agent receives a *ticket* (the problem) and searches the *policy documents* (the knowledge) to decide what to do. Analogy: the policy PDF is the textbook, the ticket is the exam question. The agent reads the question, looks up the relevant textbook page, answers, and cites the page. Without the policy docs, the agent is guessing from general knowledge — which the grounding rule forbids.

In the data model these are separate tables: `documents` (→ `chunks`) vs. `tickets`. They only meet during a `run`.

---

## D3 — Ticket filing is in the MVP (but not a full ticketing system)

Ticket creation is explicitly in scope: the New Ticket form (title, description, requester department, affected service, optional existing priority), the Tickets screen, and storage. Confirmed by the personas (Operator creates/imports tickets), the screens list, the `get_ticket` tool, and the definition of done (step 4: Operator submits a VPN ticket).

Two ways a ticket enters the system:
1. **Manual filing** via the form — what you demo live.
2. **Seeded demo tickets** via a seed script — what powers evaluation (the ~15-20 labeled tickets).

What ticket filing is NOT: not a full ticketing product. No comment threads, attachments, SLA timers, email notifications, or ticket linking. The ticket is a lightweight record — just enough fields to feed the agent and write back to (assign team, change priority, add note). The real ticket system (Jira/ServiceNow) is mocked behind an integration interface. So the `tickets` table is minimal by design.

---

## D4 — Who is the Approver (segregation of duties)

The Approver is a **designated human reviewer role** — not the person who filed the ticket, and not the developer acting as developer.

- **Not the filer:** the filer is the employee with the problem. They aren't even a persona in the MVP; they're just the "requester" field on a ticket and don't log in. Letting requesters approve actions on their own tickets is a control failure (they'd rubber-stamp whatever unblocks them).
- **Not the developer-as-developer:** building the system is separate from operating it. The Administrator persona manages docs/config/users/metrics — approving individual ticket actions isn't their listed job.
- **The Approver persona:** maps in a real deployment to a team lead, IT supervisor, or support manager — someone with authority and context to sign off on "reassign this ticket and change its priority."

Mental model: the agent is a junior analyst who drafts a recommendation with evidence; the Approver is the senior teammate who signs off before anything actually changes. The agent proposes; a human with authority disposes.

Why the separation is deliberate — **segregation of duties**: the entity that *proposes* a change (agent) must differ from the entity that *authorizes* it (Approver), which differs from the entity that *reported* the need (filer). That's what makes the audit trail meaningful. If proposer and approver were the same, approval would be theater.

Demo note: `roles` allow one user to hold all three for convenience, but seed at least one distinct Operator and one distinct Approver so the handoff between two different people is demonstrable — a stronger demo than one person approving their own proposal.

---

## D5 — No AI model in the Approver seat

Considered: using a different AI model (e.g. a code model like Codex) as an "approval agent." Rejected.

The Approver is a human role. Putting a model there deletes the human-in-the-loop, which is the single most important architectural feature of the project. It would revert to an autonomous agent that proposes AND approves its own writes — the exact control failure D4 avoids. There is no "approval persona agent."

Where a *second, different* AI does legitimately add value (neither is "the approver"):
1. **Reviewer/critic sub-agent (optional, Phase 3):** a second model reads the triage agent's proposal and flags concerns (low confidence, citation doesn't support the recommendation, priority too high) — then the human Approver still makes the final call, now with an AI second opinion. Classic proposer → critic → human pattern. Also satisfies the spec's "supports sub-agents" requirement. For MVP, same-model-different-context is fine; note "swap in a different model for true diversity" as a hardening step.
2. **LLM-as-judge for evaluation (Phase 5):** a separate model scores triage quality against a rubric. Here a *different* model is best practice — a model shouldn't grade its own homework (shared blind spots).

Why a code model (Codex) is the wrong choice for any runtime role: code models are tuned for writing code. Triage/review/judging are natural-language reasoning tasks. For model diversity, reach for a different *general* model, not a coding model.

---

## D6 — Codex is a development-time tool, not a product component

Decision: keep Codex entirely out of the runtime path; use it only during development.

- **Runtime AI (ships in FlowForge-AI):** triage agent, optional reviewer sub-agent, eval judge. General reasoning. Ollama local / OpenAI validation. No Codex.
- **Development-time AI (never shipped):** implementation and testing tooling.

Division of labor:
- **Claude Code** — primary implementation. Has the CLAUDE.md context, reads across the repo, drives the spec-driven loop.
- **Codex** — development-time only: test generation from spec acceptance criteria, mock/fixture/seed-data generation, adversarial edge-case tests, independent review of diffs (a different code model reading cold catches blind spots). Never a runtime sub-agent or shipped component.
- **Ollama (local)** — runtime LLM during dev, free.
- **OpenAI** — runtime final validation only.

Isolation rules (non-negotiable): Codex artifacts live in `tests/`, `scripts/`, `fixtures/`, never imported by `app/`; nothing development-time gets a production model key or a network path into the running system.

When tests start mattering: Phase 0 barely needs them — set the convention, don't force it. Codex earns its place from Phase 1-2, when there's real logic (ingestion, retrieval, triage graph). Each phase spec's definition of done is the source for its acceptance tests.

---

## D7 — Tenant isolation via org_id from day one

Single Postgres, `org_id` column on every table, strictly enforced query filtering in the backend. Row-level security (RLS) is noted as the production hardening step, but the MVP uses application-level filtering.

Why now (Phase 0) rather than later: every write tool requires organization context, and tenant isolation is a listed capability. Retrofitting `org_id` onto an existing schema is painful, so it goes into the base schema from the start, even before there's data to isolate. This is a locked decision.

---

## D8 — Durable pause via LangGraph Postgres checkpointing

When the agent hits the approval step, LangGraph checkpoints its entire state to Postgres and the request ends. The approver may decide minutes or hours later; the run then resumes from exactly where it stopped.

Why it matters: this is the difference between a genuine human-in-the-loop system and a demo that only works if the approver clicks within the same request. The pause is a real interrupt, not a same-request wait. This is the architectural centerpiece — worth leading with in interviews: the durable pause backed by checkpointing into the `runs` table is what makes the system controllable and auditable rather than an autonomous agent doing writes on its own.

---

## D9 — Grounding rule enforced in code

A recommendation cannot be considered grounded unless it includes at least one valid citation. This is enforced in code, not just requested in the prompt. Ingestion preserves document title, version, page, and section metadata all the way to storage precisely so citations can point to a real source (title, page, section). Ingestion and citation are the same design decision viewed from two ends — skip the metadata during ingestion and honest grounding becomes impossible.

---

## D10 — Evaluation needs a labeled seed set

The dashboard shows "evaluation accuracy." For that number to mean anything, there must be a labeled set: ~15-20 demo tickets with known-correct category / urgency / team. Agent output is scored against them. Build the seed set early (Phase 1) so eval is not an afterthought bolted on at the end.

---

## D11 — Local-first, cost-conscious build

Two things in the stack cost money: the LLM API and AWS hosting. Everything else has a free path.

- **LLM:** model-agnostic behind a single factory. Ollama locally (free, unlimited) for development; OpenAI only for final validation. Nothing imports a provider directly except `backend/app/llm/provider.py`.
- **Vector DB:** pgvector as a Postgres extension, not a separate paid vendor (Pinecone). One fewer service, zero cost, and a more "enterprise" choice (customers don't want another SaaS dependency).
- **Postgres + Redis:** free in Docker locally.
- **Auth:** Auth0/Okta free developer tier (OAuth2/OIDC).
- **Observability/eval:** build our own on Postgres + a dashboard rather than a paid SaaS — a stronger engineering flex and free.
- **AWS:** free tier for 12 months; deploy the whole stack on a single small EC2 with Docker Compose, spun up only for the demo recording, torn down after. Keep a small ($10-20) budget for final OpenAI validation.

---

## D12 — Development methodology: spec-driven

We separate deciding what to build from building it. For every real feature: write a spec → human review → break into a numbered task plan → human review → implement task by task showing each diff → atomic commit per task. Trivial one-line fixes skip the spec; real features don't. Architectural assumptions get surfaced in the spec, before code, where they're cheap to change. Genuinely parallel research is dispatched to subagents so each keeps a clean context.

Known caveat: Claude Code doesn't guarantee spec compliance — it can occasionally skip a CLAUDE.md instruction even when it "knows" the rule. Mitigation isn't more markdown, it's phase gates: review at fixed checkpoints (end of spec, end of plan, end of each task) rather than trusting it to self-police for pages at a time.

---

## D13 — Spec ownership and approval belong to the code owners

Specs and plans are owned and approved by the **FlowForge Code Owners** — the reviewers listed in `.github/CODEOWNERS` — not any single named person. Everything in the repo is collectively owned; approval at each review gate (spec, plan, task) comes from a code owner. Spec `Owner:` fields and review-gate language reference "FlowForge Code Owners" accordingly.

---

## D14 — Phase 0 review gate resolved (2026-07-11)

The four Phase 0 decisions were reviewed and confirmed by the code owners:

1. **Postgres image:** `pgvector/pgvector:pg16` — extension ships pre-built.
2. **Roles storage:** separate `user_roles` join table (over an enum array on `users`) — each role grant is its own row, avoiding Postgres enum-array migration pain and leaving room for grant metadata (granted_by, expiry) without a schema rework.
3. **Migrations:** Alembic from Phase 0, every migration with a working `downgrade()`.
4. **Async stack:** SQLAlchemy 2.0 async + asyncpg.

`specs/01-phase0-foundation.md` is now **Approved**. Next gate: the Phase 0 task plan (write, then code-owner review, then build task by task).

---

## D15 — Phase 1 review gate resolved (2026-07-20)

Phase 0 is built and merged (PR #6, adversarial findings addressed). The Phase 1 spec is **Approved** with four decisions confirmed by the code owners:

1. **Queue library: arq** — async-native Redis queue; fits the asyncio stack (FastAPI, asyncpg, async SQLAlchemy) without thread bridging. RQ (sync) and Celery (heavyweight) rejected.
2. **PDF extraction: pypdf** — BSD-licensed and sufficient for the clean text-layer fixture PDFs; PyMuPDF rejected on AGPL licensing.
3. **CI embeddings: deterministic fake provider** — `LLM_PROVIDER=fake` yields hash-based vectors at the configured dimension so the ingestion/retrieval gates run in CI without Ollama; refused when `APP_ENV=prod`. Ollama stays the dev default; this never ships as a prod path.
4. **Embedding dimension: 768** (`EMBEDDING_DIM` config constant, nomic-embed-text); the chunks migration uses it.

The 12-task plan lives in `specs/02-phase1-rag.md`; tasks 9–10 are Codex's (fixtures per spec 09, gate tests for G1.1–G1.4).

---

## D16 — Phase 2 review gate resolved (2026-07-28)

Phase 1 is built and merged (PR #7). The Phase 2 spec is **Approved** with six decisions:

1. **Structured output: provider-native JSON-schema mode** (Ollama `format`, OpenAI `response_format`) + Pydantic validation + one repair retry, behind a new `complete_structured()` on the provider interface so D11's model-agnosticism holds. Prompt-only JSON is too flaky on small local models; LangChain's `with_structured_output` would add a second abstraction we don't control.
2. **Deterministic graph control flow** — the fixed node list calls tools directly; no ReAct loop. Predictable step counts keep G2.5 audit-completeness meaningful and make the Phase 3 durable pause tractable. Tools still go through the registry + audit wrapper.
3. **Fake completion provider for CI**, extending D15: deterministic schema-valid output plus injectable invalid output so the schema/enum/grounding gates prove they fail closed. Prod-refused.
4. **Taxonomy lives in `backend/app/agents/taxonomy.py`**, with a Codex-owned parity test against `fixtures/enterprise/taxonomy.json`. This resolves a real conflict: the D6 CI guard forbids `backend/app/` importing `fixtures/`, so the enums cannot live only in the fixture. One authority, drift caught by a gate.
5. **Two Postgres drivers, deliberately.** `langgraph-checkpoint-postgres` requires psycopg3 while the app stays on asyncpg (D14). We accept the second driver rather than hand-write an asyncpg checkpointer — the durable pause is the architectural centerpiece and not the place for bespoke persistence.
6. **Dev triage model:** `TRIAGE_MODEL`, default `llama3.1:8b`, separate from `EMBEDDING_MODEL`. Phase 5's eval judge must differ from it (D5).

The 12-task plan lives in `specs/03-phase2-triage-agent.md`; tasks 10–11 are Codex's.

---

## D17 — Phase 3 review gate resolved (2026-08-09)

Phase 2 is built and merged (PR #8). G2.1–G2.6 pass; G2.4 cleared the 70% bar — 75.0% as recorded, independently reproduced at 80.0% (16/20) on a fresh corpus ingest. The Phase 3 spec is **Approved** with five decisions:

1. **Proposed actions are derived in code, not chosen by the model.** `TriageResult` names values, never tools; a pure function maps them to concrete tool calls, emitting an action only when it would actually change the ticket. Keeps D16 decision 2 intact and adds no new failure mode for a small local model.
2. **One bundled approval per run** — a single card lists every proposed action and the approver decides once. Per-action approval was rejected: it multiplies inbox rows and breaks the one-run-one-decision mapping the durable resume depends on.
3. **Approver identity via an `X-User-Id` header** this phase, mirroring the `X-Org-Id` placeholder, replaced by the authenticated principal in Phase 4. Chosen over a nullable column so segregation of duties is testable now — an unattributed approval would gut the audit trail in the phase that exists to create it.
4. **Idempotency in a `tool_executions` table**, unique on `(run_id, tool, args_hash)`. Durable across restarts unlike Redis, and the unique index prevents double-execution under concurrent resumes; `audit_log` stays purely append-only.
5. **LangGraph dynamic `interrupt()` + `Command(resume=...)`** rather than static `interrupt_before`, so the decision payload rides the resume value and the graph carries no approval-specific plumbing.

The 12-task plan lives in `specs/04-phase3-actions-approval.md`; tasks 10–11 are Codex's.

---

## D18 — Phase 4 review gate resolved (2026-08-15)

Phase 3 is built and merged (PR #9). G3.1–G3.7 pass, and all six findings from Codex's adversarial pass are fixed. The Phase 4 spec is **Approved** with seven decisions:

1. **Auth goes behind a provider abstraction, like the LLM does.** `Auth0Provider` validates against the real tenant's JWKS; a local dev issuer generates a keypair at startup and **refuses to load when `APP_ENV=prod`**, exactly as the `fake` LLM provider does. The decisive property is that *validation* is a single code path — same JWT verify, same claims, same JWKS interface — so G4.1–G4.6 exercise the real enforcement offline and only the issuer differs. An Auth0-only build would make the gates unrunnable in CI, and a test-only bypass header would make them prove nothing about the path that actually ships.
2. **Auth0's access token is validated per request; we issue no token of our own.** Stateless, with a cached JWKS. Rejected issuing a session JWT: it adds a signing key to protect and rotate plus a revocation story, and buys nothing here because roles do not travel in the token (see 3), so there are no custom claims to mint.
3. **Roles live in our database, not in Auth0 claims.** The token establishes *who* (the `sub`); `user_roles` (D14) establishes what they may do. Keeps IdP config trivial, makes the role matrix testable without touching Auth0, and means a revoked role takes effect on the next request rather than the next token refresh.
4. **No administrator override on approval decisions.** Administrator is a configuration role, not an authorization role; letting it approve would put the same principal on both sides of D4/D5 segregation of duties. A person who must approve receives an explicit approver grant, which the personas doc already permits. The full role matrix lives in `specs/05-phase4-auth-tenant.md`.
5. **Dev-only routes authenticate like everything else** and additionally keep their prod 404 guard — two independent controls. An auth exemption list was rejected: it is precisely the construct that decays, and it would leave unauthenticated routes reading run data in shared dev and CI.
6. **Poison messages dead-letter through the existing typed-failure machinery** — a `dead_letter` value on `FailureReason` plus an attempt counter on `runs` — rather than a separate DLQ table. One migration, no new surface, and a dead-lettered run stays visible where operators already look.
7. **Tenant scoping is a narrow helper plus an automated unscoped-query check**, not a repository layer. A full repository rewrite of Phases 1–3 inside the phase that already retrofits auth across every router is too much change at once; the automated check is what stops D7 from depending on reviewer attention, which has already failed once (Codex F6). Postgres RLS remains the deferred production answer in ARCHITECTURE.md.

The 16-task plan lives in `specs/05-phase4-auth-tenant.md`; tasks 2, 13 and 16 are Codex's.

---

## D19 — Phase 5 review gate resolved (2026-08-16)

Phase 4 is built and merged (PR #10). G4.1–G4.6 pass, all eleven findings across three adversarial rounds are fixed, and CI is green. The Phase 5 spec is **Approved** with seven decisions:

1. **The judge is a second *local* model, not a second prompt.** `qwen2.5:7b` against llama3.1:8b triage — a different family, so different weights and different blind spots, which is the whole point of D5. Config validation refuses a judge equal to the triage model. Keeping it in Ollama preserves D11 (local-first, free) and lets an eval batch run offline; OpenAI remains available for final validation. A different prompt on the same model was rejected outright: that is a model grading its own homework.
2. **Eval mode is a separate compiled graph, not a flag.** `build_graph(eval_mode=True)` produces a graph in which the approval interrupt node *does not exist*, so an eval batch cannot pause. Rejected an `is_eval` boolean checked inside the approval node: the human-in-the-loop would then rest on a flag being false, and a flag that can be set can be set wrongly on a real run. Same reasoning as G3.2, where the rejected→execute edge was removed rather than guarded.
3. **G5.2's canary pair is a real-model gate, opt-in, like G2.4.** A deliberately-wrong resolution must score below a correct one, which requires actual semantics; the fake provider is deterministic and semantically blind. CI asserts what a fake honestly can — rubric-schema validation and the judge≠triage config check. Building a "judge mode" into the fake was rejected as the exact fiction D18 decision 1 exists to prevent: it would look like proof of judgement while proving only wiring.
4. **A batch runs as background jobs and is scored as runs settle.** `POST /api/eval/run` returns a batch id immediately; the runs go through the existing arq path, so eval exercises the real execution machinery rather than a parallel one. G5.4 (a batch completes even when individual runs fail) falls out of this rather than needing special handling. A synchronous endpoint would hold an HTTP connection for minutes and let one hung run kill the batch.
5. **Deterministic scoring covers the three fields the fixture actually labels** — category, urgency, recommended_team. The spec listed `suggested_priority`, but no such label exists in `fixtures/eval_tickets.json`; inventing twenty priority labels now would add an unreviewed answer key to one that is *already* unreviewed (G1.5). The spec is amended to match the fixture rather than the fixture bent to match the spec.
6. **Cost and evaluation accuracy are administrator-only** in `GET /api/metrics/summary`; every authenticated role sees run counts, latency, approval/edit/rejection rates and the pending-approval count. Spend and model-accuracy are oversight figures, and the personas doc gives oversight to the Administrator.
7. **The pricing table stays versioned in code**, in `app/llm/cost.py`, with an as-of date and Ollama at zero. Config-file pricing was rejected because an unset table silently reports $0 — and the cost figure is the one most likely to be quoted in a demo, so it should be the one most visible in review.

The 16-task plan lives in `specs/06-phase5-eval-observability.md`; tasks 2 and 16 are Codex's.

---

## Open items (as of 2026-08-16)

- **G1.5 is now blocking, not just overdue.** Phase 5 scores the agent against these labels and writes the result into a regression table that later phases compare against; an unreviewed answer key becomes a permanent baseline the moment a batch is recorded. Original note:
- **G1.5 (Phase 1) is now on the critical path.** `fixtures/eval_tickets.json`, `fixtures/retrieval_checks.json`, and `fixtures/enterprise/taxonomy.json` still carry `review_status: draft_pending_code_owner_review`. G2.4 cleared its bar by a small margin against labels nobody has signed off, and Phase 5's formal eval inherits the same answer key. **EVAL-012 and EVAL-019 were mis-categorised identically in two independent runs** — either a consistent model blind spot or two wrong labels, and they are the first worth a human look.
- ~~**Eval denominator inconsistent between tools.**~~ **Closed in Phase 3.** `scripts/eval_baseline.py` now scores over every ticket attempted, matching the gate, and both treat a run resting at `awaiting_approval` as scoreable — Phase 3's pause would otherwise have reported 0% for a working agent. Historic `eval/baseline.md` rows predate the change; the recorded 75% and 80% figures were already on the all-tickets basis.
- ~~**Build Phase 3**~~ **Done.** Merged as PR #9; G3.1–G3.7 green and Codex's six adversarial findings fixed.
- ~~**Phase 4 spec review**~~ **Resolved** as D18 above.
- ~~**Build Phase 4**~~ merged as PR #10; all four CI jobs green on `ab56e56`.
- ~~**Phase 5 spec review**~~ **Resolved** as D19 above.
- **Build Phase 5** on `feat/phase5-eval-observability`: tasks 1, 3–15 (Claude), 2 and 16 (Codex). **Tasks 1–15 done**; task 16 (adversarial pass + cold diff review) remains Codex's. Task 2 was written by Claude rather than Codex, like Phase 4's task 13: the gates needed the eval contract that tasks 3 and 5 define, and they landed in the same pass. That is a deviation from the D6 lane and is recorded rather than glossed — a Codex round on `tests/phase5` is still worth having in task 16.
- **Three defects Phase 5's own gates found in Phase 5's code**, each fixed in its own commit: the scorer expired the batch row between polls and died on the next attribute read (`MissingGreenlet`, batch stuck in `running` forever); `tool_success_rate` filtered on a tool name that does not exist, so every model call and lifecycle record sat in its denominator; and the answer key was resolved relative to the repository, which is not a path that exists inside the image (`fixtures/` is outside the backend build context by D6, so `POST /api/eval/run` 500ed on any containerised stack). The last is now `EVAL_LABELS_PATH` plus a read-only mount — the labels still never enter the database, which is what keeps them unreadable to the agent.
- **Two arm64 wheels SIGILL on import** and are pinned around in `backend/pyproject.toml`: hiredis 3.4.1 and cryptography 47+. Both take the containers down with exit 132 and no log line, which is a memorable half hour if it is not written down.
- ~~**Build Phase 4**~~ **Done** (tasks 1–15). Task 13 was reassigned from Codex to Claude mid-phase: the retrofit is harness-only and no assertion changed, and leaving the Phase 0–3 suites red would have blocked the phase on a second Codex round-trip. Task 16 (adversarial pass + cold review) remains Codex's.
- **An Auth0 tenant does not exist yet** and only a code owner can create one: one tenant, one SPA application, callback URLs, an API identifier, and the seed users. Until those values are in `.env`, Phase 4 develops entirely against the local dev issuer (D18 decision 1) — which is a supported path, not a workaround, but the Auth0 half of G4.1 stays unproven until a real tenant exists.
- ~~**Phases 0–3 gate suites will go red mid-phase.**~~ **Closed.** They went red at task 6 as planned and are green again: `tests/support/auth.py` maps the org id they already have onto a token, one line per suite, with no assertion touched.
- **`/api/dev/token` is the largest remaining attack surface** and deserves the adversarial pass's attention. It is unauthenticated by necessity (a login endpoint cannot require a login) and signs for identities we do not know (so that first-login refusal is testable). Its only guards are the prod 404 and the local-provider 404. If either regressed, anyone reaching the port could mint a token for any seeded email.
- **Deferred, tracked in ARCHITECTURE.md** (recorded so they are found on purpose, not in an incident): HNSW index on `chunks.embedding`, Postgres RLS, and value-level credential scanning in audit payloads. (A genuinely different eval-judge model is no longer deferred — D19 decision 1 adopts one.)

---

# Part 2 — Personas (merged)

Three roles. A single user may hold more than one role. All three are **human** users — none is an AI agent (see D5). The ticket "requester" (the employee with the problem) is **not** a persona and does not log in; they are a field on the ticket.

## Administrator
The person who sets up and oversees the system.

**Can:** upload company documentation; view ingestion status; configure the ticket workflow; view all workflow runs; review evaluation metrics; manage users and roles (minimally).
**Screens:** Dashboard, Knowledge documents, Upload document, Evaluation results, Audit log, read-only configuration.
**Not their job:** approving individual ticket actions (Approver's job); building the system (developer concern, separate from operating it).

## Operator
The person who runs tickets through the system day to day.

**Can:** create or import tickets; start triage workflows; see recommendations and citations; view workflow status.
**Screens:** Tickets, New ticket, Workflow run detail, Dashboard.
**New ticket form fields:** title, description, requester department, affected service, optional existing priority.

## Approver
The human gate. Reviews what the agent proposes and decides whether it happens.

**Can:** view pending actions (approval inbox); approve, edit, or reject proposed ticket updates; see evidence and reasoning summary; review previous decisions.
**Screens:** Approval inbox, Workflow run detail.
**Maps to (real deployment):** team lead, IT supervisor, or support manager.

**Decision outcomes:**
- **Approve** → workflow resumes, tool executes, updated ticket re-fetched for confirmation, run marked completed.
- **Edit** → edited values validated, approved edited action executes; both original and edited proposals stay in the audit record.
- **Reject** → no external write occurs, rejection + feedback recorded, run marked rejected.

## Approval card contents (what the Approver sees)
Proposed action; affected ticket; new values; existing values; evidence (retrieved docs + excerpts + citations); confidence; risk classification; agent version; Approve / Edit / Reject buttons.

## Demo seeding
One superuser may hold all three roles for convenience, but seed at least one distinct Operator (`operator@demo`) and one distinct Approver (`approver@demo`) so the handoff between two different people is demonstrable — visible segregation of duties.
