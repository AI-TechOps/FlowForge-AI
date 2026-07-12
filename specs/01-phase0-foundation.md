# Spec: Phase 0 — Foundation

**Status:** Draft — awaiting review
**Owner:** Muhammad
**Depends on:** 00-mvp-definition.md

## What this phase delivers

A running, empty shell of the whole system. No agents, no RAG, no auth logic yet — just the skeleton every later phase plugs into. At the end, `docker compose up` brings up a backend, a frontend, Postgres+pgvector, and Redis, all healthy and talking to each other, with the org/tenant data model in place.

## Why this phase exists

Every later phase assumes: a place to run FastAPI, a Postgres with pgvector enabled, a Redis for cache/queue, a config system that switches cleanly between local (Ollama) and validation (OpenAI), and an `org_id`-based tenant model on the schema from day one. Retrofitting tenant isolation later is painful — so it goes in now, even before there's data to isolate.

## Scope (what's in)

### 1. Repository structure
```
flowforge-ai/
  backend/            # FastAPI app
    app/
      main.py         # app entry, health check
      config.py       # settings via pydantic-settings, reads .env
      db.py           # SQLAlchemy async engine + session
      models/         # ORM models (org, user, doc, etc. — stubs this phase)
      api/            # routers (health only this phase)
    pyproject.toml
    Dockerfile
  frontend/           # React + Vite + TypeScript
    src/
      main.tsx
      App.tsx         # renders backend health status
    package.json
    Dockerfile
  infra/
    docker-compose.yml
    init-db.sql       # enables pgvector extension
  specs/
  CLAUDE.md
  .env.example
  .gitignore
  README.md
```

### 2. Docker Compose topology
Four services:
- `db` — postgres:16 image with pgvector. `init-db.sql` runs `CREATE EXTENSION IF NOT EXISTS vector;`
- `redis` — redis:7
- `backend` — builds from backend/Dockerfile, depends on db + redis, exposes 8000
- `frontend` — builds from frontend/Dockerfile, exposes 5173, proxies /api to backend

Healthchecks on db and redis; backend waits for both to be healthy.

### 3. Config / env strategy
`backend/app/config.py` uses pydantic-settings. Required vars documented in `.env.example`:
- `DATABASE_URL`
- `REDIS_URL`
- `LLM_PROVIDER` (values: `ollama` | `openai`) — default `ollama`
- `OLLAMA_BASE_URL`
- `OPENAI_API_KEY` (optional, only when provider is openai)
- `EMBEDDING_MODEL`
- `APP_ENV` (`dev` | `prod`)

No provider is imported directly anywhere except a single `llm/provider.py` factory (stub this phase — just the interface + a factory that reads `LLM_PROVIDER`).

### 4. Tenant / org data model (schema foundation)
Create the base ORM models with `org_id` from the start:
- `organizations` (id, name, created_at)
- `users` (id, org_id FK, email, auth_subject nullable — linked to the OAuth2 subject in Phase 4, roles as array/enum, created_at). No password column: auth is Auth0-only (Phase 4); we never store or handle passwords.
- A `TenantBase` mixin or convention so every future table carries `org_id`.

Migrations via Alembic. This phase creates the initial migration with `organizations` and `users` only. Seed one demo org and one admin user via a seed script (not a migration).

Migration convention (applies to every later phase too): every migration ships a working `downgrade()`; the check is `upgrade → downgrade → upgrade` against a scratch database, run in CI or as part of the phase gate.

### 5. Health check
- `GET /api/health` returns `{ "status": "ok", "db": "ok"|"error", "redis": "ok"|"error" }` — actually pings db and redis.
- Frontend App.tsx calls it and shows a green/red status so "it works" is visible in the browser.

## Out of scope (explicitly NOT this phase)
- Any RAG, embeddings, or document handling logic (models can be stubbed but no ingestion).
- Any LangGraph or agent code.
- Real auth / login (users table exists; no login flow yet).
- Any of the ten MVP screens beyond a trivial health-status page.
- AWS deployment (local Docker Compose only).

## Key decisions to confirm before building
1. Postgres image: use the `pgvector/pgvector:pg16` image (ships the extension) vs. plain postgres + manual install. **Proposed: pgvector/pgvector:pg16.**
2. Roles storage: Postgres enum array on users vs. separate `user_roles` join table. **Proposed: array of role enums on users for MVP simplicity; note join table as the scale-up path.**
3. Migrations: Alembic from Phase 0. **Proposed: yes** — cheaper than retrofitting.
4. Async stack: SQLAlchemy 2.0 async + asyncpg. **Proposed: yes.**

## Definition of done for Phase 0
- `docker compose up` starts all four services with no errors.
- `GET /api/health` returns all-ok when db and redis are up.
- The frontend page loads and shows a green backend-healthy indicator.
- Alembic migration creates `organizations` and `users`; seed script inserts one org + one admin user.
- CI guard for the runtime/development-time isolation rule (D6): nothing under `backend/app/` imports from `tests/`, `scripts/`, or `fixtures/` (import-linter contract or equivalent grep check).
- `.env.example` documents every required var; app reads config from env.
- README documents: how to run, how to seed, how to switch LLM provider.

## Task plan
*(To be filled after this spec is approved — this is the review gate.)*
