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
python scripts/seed.py     # idempotent: demo org + the four seeded users below
```

Seeded identities — operator and approver are **different people** on purpose, so
the hand-off in the MVP journey is demonstrable rather than asserted (D4):

| Email | Roles |
|---|---|
| `admin@demo` | administrator |
| `operator@demo` | operator |
| `approver@demo` | approver |
| `demo@demo` | all three, for recording the demo with one narrator |

## LLM provider

Model-agnostic by design (`backend/app/llm/provider.py` is the only module that knows providers exist). Switch via env:

- `LLM_PROVIDER=ollama` (default) — local dev, free; set `OLLAMA_BASE_URL` if not on localhost. Embeddings use `EMBEDDING_MODEL` (default `nomic-embed-text`, 768-dim): `ollama pull nomic-embed-text`.
- `LLM_PROVIDER=openai` — final validation only; requires `OPENAI_API_KEY` (the factory refuses a missing or blank key).
- `LLM_PROVIDER=fake` — deterministic offline embeddings for CI/tests only; refused when `APP_ENV=prod`.

## Knowledge ingestion & retrieval (Phase 1)

Since Phase 4 every call needs a token; these are administrator operations.

```bash
ADMIN="Authorization: Bearer $(python scripts/dev_token.py --email admin@demo)"

# Upload a document (.pdf, .md, .txt; ≤20 MB) — returns 202 + document id
curl -H "$ADMIN" -F "file=@policy.pdf" -F "title=VPN Access Policy" localhost:8000/api/documents

# Ingestion status (pending → processing → ready | failed)
curl -H "$ADMIN" localhost:8000/api/documents            # list + chunk counts
curl -H "$ADMIN" localhost:8000/api/documents/<id>       # single document

# Recover a failed/stuck document
curl -H "$ADMIN" -X POST localhost:8000/api/documents/<id>/reingest

# Dev-only retrieval check (404 in prod)
curl -H "$ADMIN" -X POST localhost:8000/api/retrieve \
  -H 'Content-Type: application/json' \
  -d '{"query": "how do I reset my VPN access?", "k": 3}'
```

Ingestion runs on the `worker` compose service (arq + Redis). Files are stored under the `uploads` volume at `/data/uploads/{org_id}/{doc_id}`.

## Triage agent (Phase 2)

```bash
# Load the labeled eval seed set (20 tickets; idempotent)
python scripts/load_eval_tickets.py

OPERATOR="Authorization: Bearer $(python scripts/dev_token.py --email operator@demo)"

# File a ticket, then triage it
TICKET=$(curl -s -H "$OPERATOR" -X POST localhost:8000/api/tickets -H 'Content-Type: application/json' \
  -d '{"title":"Cannot connect to VPN","description":"Times out from home.","service":"MeridianConnect VPN"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
RUN=$(curl -s -H "$OPERATOR" -X POST localhost:8000/api/runs -H 'Content-Type: application/json' \
  -d '{"ticket_id":"'$TICKET'"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

# Run detail: structured output, evidence, and the full audit trail
curl -s -H "$OPERATOR" localhost:8000/api/runs/$RUN | python -m json.tool
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

## Write actions & human approval (Phase 3)

Triage no longer ends at a recommendation: it derives concrete write actions, **pauses**,
and waits for a human.

Two different people, which is the point (D4): the operator triages, the approver decides.

```bash
OPERATOR="Authorization: Bearer $(python scripts/dev_token.py --email operator@demo)"
APPROVER="Authorization: Bearer $(python scripts/dev_token.py --email approver@demo)"

# Triage now pauses instead of completing
RUN=$(curl -s -H "$OPERATOR" -X POST localhost:8000/api/runs \
  -H 'Content-Type: application/json' -d '{"ticket_id":"'$TICKET'"}' \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
curl -s -H "$OPERATOR" localhost:8000/api/runs/$RUN   # -> "status": "awaiting_approval"

# The approval inbox, and the card a human decides from
curl -s -H "$APPROVER" "localhost:8000/api/approvals?status=pending"
curl -s -H "$APPROVER" localhost:8000/api/approvals/$APPROVAL | python -m json.tool

# Decide. The approver is the token's user — nothing in the request can name
# someone else, and the operator above gets 403 here (G4.3).
curl -X POST localhost:8000/api/approvals/$APPROVAL/decision \
  -H 'Content-Type: application/json' -H "$APPROVER" \
  -d '{"decision":"approved"}'

# ...or override the agent, or refuse it outright
  -d '{"decision":"edited","final_values":[{"tool":"change_ticket_priority",
       "args":{"ticket_id":"'$TICKET'","priority":"P3"}}]}'
  -d '{"decision":"rejected","feedback":"not urgent"}'
```

Properties worth knowing, because they are what make the gate real rather than decorative:

- **The pause is durable.** `interrupt()` checkpoints to Postgres and the job *ends*. Restart
  the backend and worker mid-pause and the run still resumes and completes (G3.1) — the
  approver may decide hours later, in a different process.
- **Reject cannot write.** There is no graph edge from the rejected branch to `execute`, so
  "no write on reject" is structural, not a runtime check (G3.2).
- **At most once.** Every write claims a row in `tool_executions` (unique on run + tool +
  args hash) *before* calling the adapter, so a replay or a concurrent resume returns the
  stored result instead of writing again (G3.3).
- **Writes are confirmed.** After executing, the ticket is re-fetched and the field checked;
  a write that reports success without landing fails the run (G3.5).
- **Edits are validated at the API.** An invalid edited value is a 422 on the approver's
  request, never a run that dies halfway through the write path (G3.4). Both the original
  and edited proposals are retained.

`[[FLOWFORGE_TICKET_FAULT:timeout|error]]` in a ticket description injects an adapter
failure for one run, so the retry and no-phantom-write paths can be exercised (G3.6).

## Authentication, roles & tenancy (Phase 4)

Every `/api` route except `/api/health` requires a bearer token. `org_id` comes from
the authenticated principal and from nowhere else — the Phase 1–3 `X-Org-Id` /
`X-User-Id` headers are gone, and a client-supplied org id in a header, query string
or body changes nothing (G4.5).

**Two providers, one verifier.** `backend/app/auth/provider.py` is the only module that
knows an identity provider exists (D18 decision 1, mirroring the LLM provider):

- `AUTH_PROVIDER=local` (default) — an offline issuer that generates an RS256 keypair
  at startup. Refused when `APP_ENV=prod`.
- `AUTH_PROVIDER=auth0` — validates the tenant's tokens against its JWKS.

`AuthProvider.verify` is concrete, not abstract: both providers share one algorithm
allow-list, one audience and issuer check, one expiry rule. A provider supplies a key
and nothing else. That is what keeps the gates honest — they exercise the shipping
verification path even with no Auth0 tenant reachable.

**Roles live in `user_roles`, not in token claims** (D18 decision 3). The token says
*who*; the database says what they may do, so revoking a role takes effect on the next
request rather than the next token refresh.

### Getting a token locally

```bash
TOKEN=$(python scripts/dev_token.py --email admin@demo)
curl -H "Authorization: Bearer $TOKEN" localhost:8000/api/documents
```

Or use the frontend at http://localhost:5173 — with the local issuer it shows a button
per seeded identity; against Auth0 it redirects to the hosted login.

### Role matrix

Enforced per endpoint and asserted cell by cell (G4.2); the full table lives in
`specs/05-phase4-auth-tenant.md` §2.

| | admin | operator | approver |
|---|:--:|:--:|:--:|
| Documents, retrieve, `/api/test/*` | ✅ | ❌ | ❌ |
| Create ticket, start run | ✅ | ✅ | ❌ |
| Read tickets, runs | ✅ | ✅ | ✅ |
| Approval inbox | ✅ | ❌ | ✅ |
| **Approval decision** | ❌ | ❌ | ✅ |

**An administrator cannot approve.** Administrator is a configuration role; letting it
decide would put one principal on both sides of segregation of duties (D4/D5, D18
decision 4). Someone who must approve is granted the approver role explicitly.

### Configuring a real Auth0 tenant

One tenant, one application. In the Auth0 dashboard:

1. **Applications → Create Application** → *Single Page Web Application*.
2. In its **Settings**, set — replacing the host for a deployed stack:
   - *Allowed Callback URLs*: `http://localhost:5173/callback`
   - *Allowed Logout URLs*: `http://localhost:5173`
   - *Allowed Web Origins*: `http://localhost:5173`
3. **APIs → Create API**. The *Identifier* you choose is the token `aud` claim and must
   match `AUTH0_AUDIENCE` exactly. `flowforge-api` is a fine choice.
4. **User Management → Users** → create one user per seeded email above. There is no
   self-signup: a valid token for an address that is not seeded gets 403, by design.
5. Fill in `.env`:

```bash
AUTH_PROVIDER=auth0
AUTH0_DOMAIN=your-tenant.eu.auth0.com   # no scheme
AUTH0_AUDIENCE=flowforge-api
AUTH0_CLIENT_ID=...                     # public: an identifier, not a credential
```

The frontend reads `VITE_AUTH0_DOMAIN`, `VITE_AUTH0_CLIENT_ID` and `VITE_AUTH0_AUDIENCE`
at build time. There is no `/api/auth/config` endpoint on purpose — it would have to be
readable before a token exists, making it a second unauthenticated route and forcing a
G4.1 exemption, and D18 decision 5 rejected exemption lists.

### Background jobs

Job payloads carry org context and every job re-checks it. A run that exhausts
`MAX_RUN_ATTEMPTS` (default 3) is **dead-lettered**: terminal, with
`failure_reason=dead_letter`, visible on the run detail page beside every other failure
rather than in a queue nobody reads. Postgres — not Redis — is the authority on
outstanding work, so a run whose queued job is lost is re-enqueued by the reconciler.

## Evaluation & observability (Phase 5)

Every run is measurable. A batch scores the agent against the labeled seed set,
and one metrics endpoint feeds the whole Phase 6 dashboard.

```bash
ADMIN="Authorization: Bearer $(python scripts/dev_token.py --email admin@demo)"

# Start a batch: triages every is_eval_seed ticket, then scores it.
# 202 with a batch id -- the runs go through the ordinary arq path, so the eval
# measures the pipeline that ships rather than a parallel one (D19 decision 4).
BATCH=$(curl -sX POST localhost:8000/api/eval/run -H "$ADMIN" | jq -r .id)

# The regression table, newest first, and one batch in full (summary + every
# per-ticket result: expected, actual, scores, judge rationale).
curl -s localhost:8000/api/eval/batches -H "$ADMIN"
curl -s "localhost:8000/api/eval/batches/$BATCH" -H "$ADMIN"

# Every MVP dashboard metric, over a window.
curl -s "localhost:8000/api/metrics/summary?window_days=30" -H "$ADMIN"

# Cross-run audit (admin) and the read-only agent configuration (any persona).
curl -s "localhost:8000/api/audit?tool=llm.judge&limit=20" -H "$ADMIN"
curl -s localhost:8000/api/config/agent -H "$ADMIN"

# Run history, filtered. Eval runs are excluded unless asked for: a batch adds
# twenty at once and none of them is work a person requested.
curl -s "localhost:8000/api/runs?status=completed&since=2026-08-01T00:00:00Z" -H "$ADMIN"
```

**Eval mode is a different graph, not a flag.** `build_graph(eval_mode=True)`
compiles a graph in which the approval and execute nodes *do not exist*, so an
eval run ends at its proposal and is scored as it stands. A twenty-ticket batch
therefore cannot strand twenty runs waiting for a human, and an eval run cannot
write — not because a boolean is false, but because there is no node to reach
(D19 decision 2). `runs.eval_batch_id` is the single marker, set only by
`POST /api/eval/run`.

**What is scored.** Deterministically, in code: `category`, `urgency` and
`recommended_team` against the fixture labels, plus grounded-rate and hit@k.
`suggested_priority` is deliberately unscored — the fixture carries no priority
label (D19 decision 5). By model: `recommended_resolution` quality and
citation-support on an anchored 1–5 rubric, judged by **a different model than
triage** (`qwen2.5:7b` vs `llama3.1:8b`). A judge equal to the triage model is a
config error and the stack refuses to start.

**The answer key never enters the database.** `fixtures/eval_tickets.json` is
mounted read-only into the backend and worker (`EVAL_LABELS_PATH`); the loader
puts tickets in Postgres and leaves the labels out, so the eval knows the
answers and the pipeline never does.

**Metrics are role-sliced.** Every persona sees run counts, latency, tool
success, approval/edit/rejection rates, retrieval success and pending
approvals. Cost, evaluation accuracy and tokens-per-run are administrator-only
(D19 decision 6) and are *absent* rather than zeroed — an absent key is a fact
a dashboard can render, a zero is a lie somebody can act on. Every rate is
`null`, never `0.0`, when its denominator is empty.

**Cost is an estimate with a date on it.** The per-model pricing table lives in
`app/llm/cost.py` with an as-of date (D19 decision 7); Ollama is $0. Estimates
are recorded per call in the audit trail and summed here.

**Logs are structured JSON with `run_id` correlation** across API and worker
(`LOG_FORMAT=text` for tailing by eye). One run's whole life — accepted by the
API, executed by the worker, judged by the scorer — is a single `run_id` query.

Regression protocol: `eval/baseline.md` holds one row per batch, keyed by
`agent_version`. **A prompt or model change without a fresh row there is a
convention violation**, checked at PR review.

## Phase 0 definition-of-done walkthrough

1. `docker compose -f infra/docker-compose.yml up --build` — all four services start; db and redis have healthchecks, backend waits for both.
2. `curl localhost:8000/api/health` — real pings: `{"status":"ok","db":"ok","redis":"ok"}`.
3. Open `localhost:5173` — green dot, "backend ok".
4. `alembic upgrade head` creates `organizations`, `users`, `user_roles`; `python scripts/seed.py` inserts the demo org + admin. Every migration has a working `downgrade()`.
5. `.env.example` documents all seven required vars.
