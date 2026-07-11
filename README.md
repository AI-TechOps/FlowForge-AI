# FlowForge-AI

Enterprise AI workflow automation platform. AI agents read support tickets, retrieve company knowledge via RAG, propose grounded resolutions, pause for human approval, execute approved actions against a ticket system, and record everything for audit and evaluation.

> Portfolio capstone framed for a Forward-Deployed Engineer role. See `specs/00-mvp-definition.md` for the full MVP.

## Documents in this repo

- `CLAUDE.md` — standing context for Claude Code. Read first, every session.
- `specs/00-mvp-definition.md` — the MVP: personas, journey, tools, screens, definition of done.
- `specs/01-phase0-foundation.md` — first phase spec (foundation), awaiting review.

## How we build: spec-driven development

For every feature, in order:

1. **Spec** — write what it does (plain language) in `specs/`.
2. **Review** — read and approve the spec.
3. **Plan** — break the spec into a numbered task list.
4. **Review** — approve the plan.
5. **Build** — implement task by task, reviewing each diff.
6. **Commit** — atomic commit per task.

Trivial fixes skip the spec. Real features do not.

## Phases

| Phase | Delivers |
|-------|----------|
| 0 | Foundation: Docker Compose, FastAPI + React skeletons, config, org/tenant model |
| 1 | RAG: ingestion, chunking, embeddings, retrieval, seed eval ticket set |
| 2 | Triage agent: LangGraph graph, structured output, read tools |
| 3 | Actions + approval: write tools, durable pause, approve/edit/reject |
| 4 | Auth + tenant: OAuth2, roles, org_id enforcement, background processing |
| 5 | Eval + observability: logging, rubric scoring, metrics endpoints |
| 6 | Dashboard: all MVP screens on real data |
| 7 | Ship: AWS free-tier deploy, demo, teardown, README |

## Running (after Phase 0 is built)

```bash
cp .env.example .env      # fill in values
docker compose -f infra/docker-compose.yml up
# backend:  http://localhost:8000/api/health
# frontend: http://localhost:5173
```

## LLM provider

Model-agnostic by design. `LLM_PROVIDER=ollama` for local dev (free), `LLM_PROVIDER=openai` for final validation. Nothing imports a provider directly except the factory in `backend/app/llm/provider.py`.
