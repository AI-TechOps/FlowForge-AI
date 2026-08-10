# FlowForge-AI

Enterprise AI workflow automation platform. AI agents read support tickets, retrieve company knowledge via RAG, propose grounded resolutions, pause for human approval, execute approved actions against a ticket system, and record everything for audit and evaluation.

## Documents in this repo

- `CLAUDE.md` — standing context for Claude Code. Read first, every session.
- `ARCHITECTURE.md` — high-level design: system views, workflow, ingestion pipeline, data model.
- `DECISIONS.md` — decisions D1–D12 with rationale, plus the personas in detail.
- `specs/00-mvp-definition.md` — the MVP: personas, journey, tools, screens, definition of done (approved).
- `specs/01-phase0-foundation.md` … `specs/08-phase7-ship.md` — one spec per phase (0–7), each reviewed before its task plan is written. Phase 0 is approved.
- `specs/09-demo-enterprise-corpus.md` — the fictional company (Meridian Dynamics), its documentation template, corpus, and labeled ticket set.
- `specs/10-codex-integration.md` — Codex's lanes, boundaries, and the Claude↔Codex handoff protocol per phase.

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

## Running

```bash
cp .env.example .env                          # defaults work for docker compose
docker compose --env-file .env -f infra/docker-compose.yml up --build
# backend:  http://localhost:8000/api/health  -> {"status":"ok","db":"ok","redis":"ok"}
# frontend: http://localhost:5173             -> green backend-healthy indicator
```

> `--env-file .env` matters: with `-f infra/docker-compose.yml` alone, compose
> looks for `.env` next to the compose file (`infra/`), not the repo root, and
> your `LLM_PROVIDER`/`OLLAMA_BASE_URL` settings would silently not apply.

Apply migrations (one-time, with the stack up — alembic ships in the backend image):

```bash
docker compose -f infra/docker-compose.yml exec backend alembic upgrade head
```

Seed the demo org from the host (backend deps installed locally: `pip install -e backend`, with `.env` pointing at localhost):

```bash
python scripts/seed.py     # idempotent: demo org + admin@demo with administrator role
```

## LLM provider

Model-agnostic by design (`backend/app/llm/provider.py` is the only module that knows providers exist). Switch via env:

- `LLM_PROVIDER=ollama` (default) — local dev, free; set `OLLAMA_BASE_URL` if not on localhost. Embeddings use `EMBEDDING_MODEL` (default `nomic-embed-text`, 768-dim): `ollama pull nomic-embed-text`.
- `LLM_PROVIDER=openai` — final validation only; requires `OPENAI_API_KEY` (the factory refuses a missing or blank key).
- `LLM_PROVIDER=fake` — deterministic offline embeddings for CI/tests only; refused when `APP_ENV=prod`.

## Knowledge ingestion & retrieval (Phase 1)

```bash
# Upload a document (.pdf, .md, .txt; ≤20 MB) — returns 202 + document id
curl -F "file=@policy.pdf" -F "title=VPN Access Policy" localhost:8000/api/documents

# Ingestion status (pending → processing → ready | failed)
curl localhost:8000/api/documents            # list + chunk counts
curl localhost:8000/api/documents/<id>       # single document

# Recover a failed/stuck document
curl -X POST localhost:8000/api/documents/<id>/reingest

# Dev-only retrieval check (404 in prod)
curl -X POST localhost:8000/api/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query": "how do I reset my VPN access?", "k": 3}'
```

Ingestion runs on the `worker` compose service (arq + Redis). Files are stored under the `uploads` volume at `/data/uploads/{org_id}/{doc_id}`.

## Triage agent (Phase 2)

```bash
# Load the labeled eval seed set (20 tickets; idempotent)
python scripts/load_eval_tickets.py

# File a ticket, then triage it
TICKET=$(curl -s -X POST localhost:8000/api/tickets -H 'Content-Type: application/json' \
  -d '{"title":"Cannot connect to VPN","description":"Times out from home.","service":"MeridianConnect VPN"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
RUN=$(curl -s -X POST localhost:8000/api/tickets/$TICKET/triage \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

# Run detail: structured output, evidence, and the full audit trail
curl -s localhost:8000/api/runs/$RUN | python -m json.tool
```

The graph runs `load_ticket → retrieve_evidence → classify → ground_check → propose`
as a background job. Two rules are enforced in code, not in the prompt:

- **Grounding** — a run whose citations don't reference chunks it actually retrieved
  fails as `ungrounded`; it never reports `completed`.
- **Schema/enum** — output that doesn't validate gets one repair retry, then fails as
  `schema_invalid`. Classification values outside the taxonomy are a validation error.

`FAKE_LLM_MODE` (`valid` | `bad_enum` | `unparseable` | `no_citations`) injects bad model
output so those gates can be shown to fail closed. For a single run, put
`[[FLOWFORGE_FAKE_COMPLETION:bad_enum:category]]` in the ticket description instead —
same modes, one call only, with an optional field to corrupt. Both only apply to
`LLM_PROVIDER=fake`, which the provider factory refuses when `APP_ENV=prod`.

Triage quality is tracked in [`eval/baseline.md`](eval/baseline.md) — run
`python scripts/eval_baseline.py` against a **real** model (the fake provider's accuracy
is noise by design).

## Phase 0 definition-of-done walkthrough

1. `docker compose -f infra/docker-compose.yml up --build` — all four services start; db and redis have healthchecks, backend waits for both.
2. `curl localhost:8000/api/health` — real pings: `{"status":"ok","db":"ok","redis":"ok"}`.
3. Open `localhost:5173` — green dot, "backend ok".
4. `alembic upgrade head` creates `organizations`, `users`, `user_roles`; `python scripts/seed.py` inserts the demo org + admin. Every migration has a working `downgrade()`.
5. `.env.example` documents all seven required vars.
