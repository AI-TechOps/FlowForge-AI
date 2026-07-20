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

## Open items (as of 2026-07-20)

- **Build Phase 1** on `feat/phase1-rag`: tasks 1–8 and 11 (Claude), 9–10 (Codex), G1.5 label review (code owners).
- **Phase 2 spec review:** next review gate after Phase 1 is built.

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
