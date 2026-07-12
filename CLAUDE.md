# FlowForge-AI — Project Context

This file is standing context for every Claude Code session in this repo. Read it before doing anything.

## What FlowForge-AI is

An enterprise AI workflow automation platform. AI agents embed into a company's internal support operations and do real work: read a support ticket, retrieve relevant company documentation via RAG, classify and route the issue, propose a resolution grounded in cited evidence, pause for human approval, then execute the approved action against the ticket system — recording the full workflow for audit and evaluation.

Framed for a Forward-Deployed Engineer portfolio piece: customer-facing engineering that ships AI into a customer's real, messy systems. This is the capstone project — it combines RAG + agents + tool-calling and adds the evaluation and observability layer that separates a demo from a deployable system.

## Tech stack

- Backend: Python 3.11+, FastAPI
- Agents: LangGraph (with Postgres checkpointing for durable human-in-the-loop pauses)
- Frontend: TypeScript, React (Vite)
- Data: PostgreSQL + pgvector (documents, chunks, embeddings, runs, audit, eval)
- Cache / queue: Redis
- LLM: model-agnostic. Ollama locally for development, OpenAI API for final validation only. Never hardcode a provider — go through an abstraction layer.
- Containerization: Docker + Docker Compose
- Deploy: AWS free tier (single EC2 + Docker Compose), spun up for demo only, torn down after

## Core architecture

- React dashboard talks to FastAPI backend.
- FastAPI drives LangGraph agents.
- Data layer: Postgres/pgvector (persistent state, vectors, logs) + Redis (cache, background task queue).
- External integrations: auth provider (Auth0/OAuth2), LLM API (Ollama/OpenAI), enterprise ticket system (mocked behind an integration interface so Jira/ServiceNow can replace it later).

## The three personas

- Administrator: uploads docs, views ingestion status, configures workflow, views all runs, reviews eval metrics, minimal user/role management.
- Operator: creates/imports tickets, starts triage, sees recommendations + citations, views run status.
- Approver: views pending actions, approves/edits/rejects proposed ticket updates, sees evidence + reasoning, reviews past decisions.

A user may hold more than one role.

## The MVP end-to-end journey (this is the definition of "done")

1. Admin logs in.
2. Admin uploads an IT policy PDF.
3. Document is successfully indexed (stored, extracted, chunked, embedded, stored in pgvector with title/version/page/section).
4. Operator submits a VPN ticket.
5. Agent runs triage → structured result (summary, category, urgency, recommended_team, suggested_priority, recommended_resolution, confidence, requires_approval, citations).
6. Run detail page shows retrieved evidence with at least one valid citation. A recommendation is NOT grounded unless it has at least one valid citation.
7. Agent proposes an action (assign team / change priority / add internal note) and the workflow pauses.
8. Approver opens the approval inbox, reviews the proposed action + evidence + confidence + risk, and approves.
9. Approved write tool executes against the mock ticket system; updated ticket is retrieved for confirmation; run marked completed.
10. Dashboard reflects the run; audit log captures the full workflow.

## The five MVP tools

- `search_company_knowledge` — auto-executes
- `get_ticket` — auto-executes
- `assign_ticket` — requires approval
- `change_ticket_priority` — requires approval
- `add_internal_note` — requires approval

Every write tool MUST have: organization context, user context, typed arguments, permission check, idempotency key, timeout, audit record, retry policy, mock implementation, confirmation request after execution.

## The MVP screens (build ONLY these)

Login, Dashboard, Knowledge documents, Upload document, Tickets, New ticket, Workflow run detail, Approval inbox, Evaluation results, Audit log.

Do NOT build a drag-and-drop agent builder. Agent configuration lives in code + database records. A read-only config page is sufficient.

## Key architecture decisions (locked)

- Tenant isolation: single Postgres, `org_id` column on every table, strictly enforced query filtering. Note row-level security (RLS) as the production hardening step, but MVP uses application-level filtering.
- Durable pause: LangGraph checkpoints to Postgres so a run survives the gap between "agent proposes" and "approver decides." The pause is a real interrupt, not a same-request wait.
- Eval: a seeded labeled set of ~15-20 demo tickets with known-correct category/urgency/team. Agent output is scored against these. Build the seed set early (Phase 1) so eval is not an afterthought.
- Grounding rule: no citation, not grounded. Enforce in code, not just in the prompt.

## How we work — spec-driven development

We separate deciding what to build from building it. For every feature:

1. Write a spec (plain language: what it does, edge cases, out of scope) in `/specs`.
2. Human review — the FlowForge Code Owners read and approve the spec.
3. Break the spec into a numbered task plan.
4. Human review — the FlowForge Code Owners approve the plan.
5. Implement task by task, one at a time, showing the diff for each.
6. Atomic commit per task, not one giant commit per phase.

Rules:
- Do NOT skip the spec phase for real features. (Trivial one-line fixes can skip it.)
- Do NOT batch multiple tasks into one commit.
- Surface architectural assumptions in the spec, before code, where they're cheap to change.
- When a phase has genuinely parallel research (e.g. "research LangGraph checkpointing AND pgvector schema design"), dispatch subagents so each keeps its own clean context.

## Conventions

- Backend: type hints everywhere, Pydantic models for all structured LLM output and tool arguments, async FastAPI routes.
- Structured LLM output: always validated against a Pydantic schema. Never trust raw model text for routing decisions.
- Every agent run and every tool call is logged to Postgres (inputs, outputs, latency, tokens, tool result, cost estimate).
- Secrets in env vars, never committed. `.env.example` documents required vars.
- Commits: conventional style (`feat:`, `fix:`, `chore:`, `test:`), one logical change each.

## Roles are humans (not agents)

The three personas — Administrator, Operator, Approver — are human users, not AI agents. In particular, the Approver is always a person: the human-in-the-loop that authorizes write actions. Never put a model in the approver seat; that would delete the human-in-the-loop, which is the core architectural feature of this project. The agent proposes and a human with authority disposes. Proposer (agent) and authorizer (human Approver) must always be different actors — segregation of duties. The ticket filer (the "requester") is not a persona and does not log in; they are just a field on the ticket.

For the demo, one user may hold all three roles for convenience, but seed at least one distinct Operator and one distinct Approver so the handoff between two different people is demonstrable.

## Testing strategy

Two separate worlds — keep them isolated:

- Runtime AI (ships inside FlowForge-AI): the triage agent, the optional reviewer sub-agent, and the eval judge. All general-reasoning tasks. Use Ollama locally, OpenAI for final validation. For the eval judge (Phase 5), deliberately use a DIFFERENT model than the one doing triage — a model should not grade its own output.
- Development-time AI (how we build and verify FlowForge-AI, never shipped): implementation and testing tooling.

Division of labor:
- Claude Code — primary implementation. Has this CLAUDE.md context, reads across the whole repo, drives the spec-driven loop.
- Codex — development-time only: test generation from spec acceptance criteria, mock/fixture/seed-data generation, adversarial edge-case tests, and independent review of diffs (a different code model reading cold catches blind spots). NEVER used for runtime sub-agents or any shipped component.
- Ollama (local) — runtime LLM during development, free.
- OpenAI — runtime final validation only.

Isolation rules (non-negotiable):
- Codex-generated artifacts live in `tests/`, `scripts/`, `fixtures/` — never imported by `app/`.
- Nothing in the development-time world gets a production model API key or a network path into the running system.

When tests start mattering: Phase 0 (scaffolding) barely needs tests — set the convention, don't force it. Codex earns its place from Phase 1-2 onward, when there is real logic (ingestion, retrieval, the triage graph) where generated suites catch regressions. Each phase spec's "definition of done" is the source for its acceptance tests.

## Build order (phases)

- Phase 0: Foundation — repo, Docker Compose (Postgres+pgvector, Redis), FastAPI + React skeletons, config/env, org/tenant model.
- Phase 1: RAG — ingestion (PDF/MD/txt), chunk, embed, store, retrieve; seed eval ticket set.
- Phase 2: Triage agent — LangGraph graph, structured output, `search_company_knowledge` + `get_ticket` tools.
- Phase 3: Actions + approval — the three write tools, durable pause, approval flow (approve/edit/reject).
- Phase 4: Auth + tenant — Auth0/OAuth2, roles, org_id enforcement, background processing.
- Phase 5: Eval + observability — logging layer, rubric scoring against seed set, metrics endpoints.
- Phase 6: Dashboard — all MVP screens wired to real data.
- Phase 7: Ship — full Docker Compose on AWS free tier, demo recording, teardown, README.
