# Spec: Phase 0 — Foundation

**Status:** Approved (2026-07-11, FlowForge Code Owners)
**Owner:** FlowForge Code Owners
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
- `db` — `pgvector/pgvector:pg16` image (extension ships pre-built). `init-db.sql` runs `CREATE EXTENSION IF NOT EXISTS vector;`
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
- `users` (id, org_id FK, email, auth_subject nullable — linked to the OAuth2 subject in Phase 4, created_at). No password column: auth is Auth0-only (Phase 4); we never store or handle passwords.
- `user_roles` (user_id FK, role enum: `administrator` | `operator` | `approver`, created_at; PK on user_id+role). A user holds a role by having a row here; multiple roles = multiple rows.
- A `TenantBase` mixin or convention so every future table carries `org_id`.

Migrations via Alembic. This phase creates the initial migration with `organizations`, `users`, and `user_roles` only. Seed one demo org and one admin user (with an `administrator` role row) via a seed script (not a migration).

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

## Key decisions (confirmed 2026-07-11 by the FlowForge Code Owners)
1. Postgres image: **`pgvector/pgvector:pg16`** (ships the extension) over plain postgres + manual install.
2. Roles storage: **separate `user_roles` join table** over a Postgres enum array on `users`. Each role grant is its own row — no enum-array migration pain, and role grants can carry metadata (granted_by, expiry) later without a schema rework.
3. Migrations: **Alembic from Phase 0** — cheaper than retrofitting.
4. Async stack: **SQLAlchemy 2.0 async + asyncpg** — matches async FastAPI routes and LangGraph's async Postgres checkpointer.

## Definition of done for Phase 0
- `docker compose up` starts all four services with no errors.
- `GET /api/health` returns all-ok when db and redis are up.
- The frontend page loads and shows a green backend-healthy indicator.
- Alembic migration creates `organizations`, `users`, and `user_roles`; seed script inserts one org + one admin user with an `administrator` role row.
- CI guard for the runtime/development-time isolation rule (D6): nothing under `backend/app/` imports from `tests/`, `scripts/`, or `fixtures/` (import-linter contract or equivalent grep check).
- `.env.example` documents every required var; app reads config from env.
- README documents: how to run, how to seed, how to switch LLM provider.

## Task plan (approved 2026-07-12 by the FlowForge Code Owners)

One atomic commit per task. Tags per spec 10: **[CC]** = Claude Code, **[CX]** = Codex.

1. **[CC] Backend scaffold** — `backend/` with `pyproject.toml` (fastapi, uvicorn, pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, redis), `app/main.py` with stub `GET /api/health`, ruff config.
2. **[CC] Config system** — `app/config.py` via pydantic-settings; `.env.example` documenting all seven required vars.
3. **[CC] Infra** — `infra/docker-compose.yml`: `db` (`pgvector/pgvector:pg16`) + `redis:7` with healthchecks; `init-db.sql` enabling the vector extension.
4. **[CC] DB layer** — `app/db.py` (async engine + session factory), `TenantBase` mixin.
5. **[CC] Models + initial migration** — `organizations`, `users`, `user_roles` ORM models; Alembic init; initial migration with working `downgrade()`.
6. **[CC] Seed script** — `scripts/seed.py`: one demo org + one admin user + its `administrator` role row.
7. **[CC] Real health check** — `/api/health` pings Postgres and Redis, returns per-dependency status.
8. **[CC] Backend containerized** — `backend/Dockerfile`, compose service waiting on healthy db + redis.
9. **[CC] Frontend scaffold** — Vite + React + TS, `App.tsx` green/red health indicator, Dockerfile, compose service with `/api` proxy.
10. **[CC] LLM provider stub** — `app/llm/provider.py` interface + factory reading `LLM_PROVIDER`; nothing else imports a provider.
11. **[CX] Dev tooling** — migration upgrade→downgrade→upgrade runner script + isolation-guard check (fails when anything under `backend/app/` imports from `tests/`/`scripts/`/`fixtures/`, verified by a planted-import self-test). **[CC]** wires both into CI.
12. **[CC] Docs** — README: how to run, how to seed, how to switch LLM provider; Phase 0 definition-of-done walkthrough.
