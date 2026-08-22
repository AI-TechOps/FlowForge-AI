# FlowForge-AI

Enterprise AI workflow automation platform. AI agents read support tickets, retrieve company knowledge via RAG, propose grounded resolutions, pause for human approval, execute approved actions against a ticket system, and record everything for audit and evaluation.

## Documents in this repo

- `CLAUDE.md` — standing context for Claude Code. Read first, every session.
- `ARCHITECTURE.md` — high-level design: system views, workflow, ingestion pipeline, data model.
- `DECISIONS.md` — decisions D1–D22 with rationale, plus the personas in detail. Each phase's review gate is recorded there (D14–D22), including the adversarial rounds and what they found.
- `specs/00-mvp-definition.md` — the MVP: personas, journey, tools, screens, definition of done (approved).
- `specs/01-phase0-foundation.md` … `specs/08-phase7-ship.md` — one spec per phase (0–7), each reviewed and approved before its task plan is written. Phases 0–6 are approved and built; Phase 7 is the remaining spec review.
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

| Phase | Delivers | Status |
|-------|----------|--------|
| 0 | Foundation: Docker Compose, FastAPI + React skeletons, config, org/tenant model | ✅ merged |
| 1 | RAG: ingestion, chunking, embeddings, retrieval, seed eval ticket set | ✅ merged |
| 2 | Triage agent: LangGraph graph, structured output, read tools | ✅ merged |
| 3 | Actions + approval: write tools, durable pause, approve/edit/reject | ✅ merged (PR #9) |
| 4 | Auth + tenant: OAuth2, roles, org_id enforcement, background processing | ✅ merged (PR #10) |
| 5 | Eval + observability: logging, rubric scoring, metrics endpoints | ✅ merged (PR #11) |
| 6 | Dashboard: all MVP screens on real data | ✅ merged (PR #12) |
| 7 | Ship: AWS free-tier deploy, demo, teardown, README | next |

**The MVP journey works end to end today**, locally: an administrator uploads a
policy, an operator files a ticket and starts triage, the agent retrieves
evidence and proposes a grounded action, the run *pauses*, a different human
approves or edits it, the approved write executes against the mock ticket
system, and the whole thing lands in the audit trail. Phase 7 is deployment and
the recording — not remaining functionality.

## Running

```bash
cp .env.example .env                          # defaults work for docker compose
docker compose --env-file .env -f infra/docker-compose.yml up --build
# backend:  http://localhost:8000/api/health  -> {"status":"ok","db":"ok","redis":"ok"}
# frontend: http://localhost:5173             -> the dashboard, sign in as a seeded identity
```

The frontend container serves a **production build** from nginx, not a dev
server (D21 decision 7) — so what you click is the artifact that ships, and
nginx proxies `/api` to the backend. For hot reload while working on the SPA,
run Vite directly instead:

```bash
cd frontend && npm install && npm run dev   # localhost:5173, proxies to :8000
```

> `--env-file .env` matters: with `-f infra/docker-compose.yml` alone, compose
> looks for `.env` next to the compose file (`infra/`), not the repo root, and
> your `LLM_PROVIDER`/`OLLAMA_BASE_URL` settings would silently not apply.

Apply migrations (one-time, with the stack up — alembic ships in the backend image):

```bash
docker compose -f infra/docker-compose.yml exec backend alembic upgrade head
```

Every migration has a working `downgrade()`, and that is checked rather than
claimed: `scripts/check_migration_cycle.py` runs `upgrade head → downgrade base
→ upgrade head` against a scratch database in CI, so every downgrade in the
chain actually executes. A migration you cannot reverse is a migration you
cannot deploy twice.

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

The same marker keeps the shared finalizer off the seed ticket: a real run
moves its ticket `new → triaged` on completion, an eval run leaves it exactly
as it found it. Topology only governs what the graph does, and the seed set is
the fixed input the regression table is measured against — a batch that
mutated its own subjects would mean batch two ran against different tickets
than batch one.

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

**Metrics are role-sliced.** Every persona sees run counts, latency, tokens per
run, tool success, approval/edit/rejection rates, retrieval success and pending
approvals. Cost and evaluation accuracy are administrator-only (D19 decision 6)
and are *absent* rather than zeroed — an absent key is a fact a dashboard can
render, a zero is a lie somebody can act on. Every rate is `null`, never `0.0`,
when its denominator is empty.

**The whole summary honours `window_days`,** including the eval figures. A
window with no batch in it reports `null` accuracy rather than reaching further
back for a number — quietly serving a stale batch is how a dashboard reports
accuracy for a prompt that is no longer deployed.

**Cost is an estimate with a date on it.** The per-model pricing table lives in
`app/llm/cost.py` with an as-of date (D19 decision 7); Ollama is $0. Estimates
are recorded per call in the audit trail and summed here.

**Logs are structured JSON with `run_id` correlation** across API and worker
(`LOG_FORMAT=text` for tailing by eye). One run's whole life — accepted by the
API, executed by the worker, judged by the scorer — is a single `run_id` query.

Regression protocol: `eval/baseline.md` holds one row per batch, keyed by
`agent_version`. **A prompt or model change without a fresh row there is a
convention violation**, checked at PR review.

## The dashboard (Phase 6)

Ten screens plus a read-only agent-config panel, on real endpoints. Phase 6 added
**no backend surface** — Phase 5 closed the last gap, so every screen sits on a
finished endpoint whose role gate the server already enforces.

| Screen | Endpoint | Who |
|---|---|---|
| Login | `/api/dev/token` or Auth0 → `/api/me` | anyone |
| Dashboard | `/api/metrics/summary`, `/api/runs`, `/api/audit` (feed, admin) | any persona |
| Tickets · New ticket | `/api/tickets` (status, department, service, eval-seed filters), `POST /api/runs` | any · operator |
| Runs · Run detail | `/api/runs`, `/api/runs/{id}` | any persona |
| Approval inbox | `/api/approvals`, `/decision` | admin reads · **approver decides** |
| Knowledge · Upload | `/api/documents`, `/reingest` | administrator |
| Evaluation | `/api/eval/batches` | administrator |
| Audit log | `/api/audit` (run, actor, tool, date range; paginated) | administrator |
| Agent config | `/api/config/agent` | any persona |

**Role gating in the UI is presentational, never protective.** The sidebar shows
only the routes your role can use and a guarded route refuses politely, but the
server is the sole enforcer — editing the URL still earns a 403 from the API.
The dashboard goes further and is role-aware *by absence*: the API simply omits
cost and evaluation accuracy for non-administrators, so the screen renders the
keys it was given and never decides who deserves what.

**Run detail is the screen that has to prove the grounding rule.** It shows
every retrieved chunk with document title, page and section, marks the ones the
model cited, and **names any citation that does not resolve** to retrieved
evidence rather than dropping it. Hiding an unresolvable citation would make a
broken run look clean — exactly the failure grounding exists to catch, concealed
by the screen meant to reveal it.

**An expired session ends everywhere at once.** Any 401 from any screen clears
the token, drops the React session and empties the query cache — data fetched
under a session that has ended must not outlive it on screen. Run detail's audit
panel reads the entries embedded in `GET /api/runs/{id}`, which are tenant-scoped
for every persona, so an operator sees their run's trail without the
administrator-only `/api/audit`.

**Charts are hand-rolled SVG and every series is real.** There is no
time-series endpoint, so the activity chart and the outcome donut are derived
client-side from `/api/runs`, filtered by the selected 7/30/90-day window.
Nothing is padded or smoothed; the bucket grain follows the data — hours when
everything is recent, days otherwise — and a sparkline with fewer than three
non-zero buckets refuses to draw rather than showing a flat line with one spike.
A chart that draws something when it has nothing is the most expensive kind of
lie in a product whose claim is that its numbers can be trusted.

**⌘K opens a command palette** over navigation, loaded tickets and recent runs.
It respects roles the same way the sidebar does — an operator cannot jump to the
audit log from it either — and it only fetches while open. Actions whose result
lands somewhere the user is not looking (approving resumes a worker, uploading
starts a background job) raise a toast; inline failures stay next to the field
that failed, where the user is already looking.

**Live data is polling, not push** (D21 decision 3): run detail every 2s until
the run settles, the inbox every 5s, documents every 3s while anything is
ingesting, the dashboard every 15s. Each stops on its own terms — a settled
corpus stops polling entirely.

Both themes ship, dark by default, and the toggle persists. Every colour is a
token defined twice, so no component names a colour. `prefers-color-scheme` is
deliberately ignored: it made "dark by default" mean "whatever the OS says",
which changed what a demo recording looked like and what a browser gate saw.

```bash
cd frontend
npm run typecheck    # tsc
npm test             # Vitest component tests (role gating, metrics, client)
npm run build        # the artifact the Docker image serves
```

## Running the gates

Every phase carries numbered gates that assert its definition of done, and they
are the point rather than a formality — three of the last four phases shipped
with defects that only a gate caught. They split by what can be honestly proved
without a live stack.

**Offline** — no database, no browser, runs anywhere:

```bash
pip install -e "./backend[dev]"
pytest                                  # unit + pure-function gates
python scripts/check_runtime_isolation.py   # D6: app/ never imports tests, scripts, fixtures
python scripts/check_tenant_scoping.py      # D18: no unscoped tenant loads under app/
ruff check . && ruff format --check .

cd frontend && npm ci && npm run typecheck && npm test
```

**Against the live stack** — bring it up first (`docker compose … up -d --build`,
`alembic upgrade head`, `python scripts/seed.py`, `python scripts/reset_corpus.py`,
`python scripts/load_eval_tickets.py`):

```bash
export DB=postgresql+asyncpg://flowforge:flowforge@localhost:5432/flowforge
export LLM_PROVIDER=fake APP_ENV=dev COMPOSE_FILE=infra/docker-compose.yml

# One phase at a time. PHASEn_REQUIRE_LIVE makes a live gate fail rather than
# skip, so a stack that is not really up cannot report green.
PHASE5_DATABASE_URL=$DB \
  PHASE5_BASE_URL=http://localhost:8000 \
  PHASE5_REQUIRE_LIVE=1 \
  pytest tests/phase5 -v

# Codex's adversarial probes (D6): they attack the seams the gates assume.
# Export every phase's pair, not just one — a probe whose phase variables are
# missing SKIPS rather than fails, so a partial export runs a third of the
# suite and still prints green.
for n in 2 3 4 5; do
  export PHASE${n}_DATABASE_URL=$DB PHASE${n}_BASE_URL=http://localhost:8000
done
pytest tests/adversarial -v      # expect: 43 passed, 1 skipped, 2 xfailed
```

**In a browser** — G6.1–G6.5 drive nginx serving the production build, so what
they exercise is the artifact that ships:

```bash
npm ci && npx playwright install chromium

PHASE6_BASE_URL=http://localhost:5173 npx playwright test          # the 13 gates
# `npm run e2e` from the repo root is the same thing; `npm run e2e:ui` opens
# Playwright's inspector and `npm run e2e:report` reopens the last HTML report.
# the 7 adversarial probes carry their own config, so the default invocation
# above does not collect them
PHASE6_BASE_URL=http://localhost:5173 \
  npx playwright test --config=tests/adversarial/phase6.playwright.config.ts
```

CI runs all of it on every pull request across five jobs: `lint`, `frontend`
(types, component tests, production build), `test` (offline suites plus the two
isolation guards), `live-gates-and-adversarial` (the whole stack, G1.1–G6.5,
both adversarial suites), and `secret-scan`.

### Two gates that could not fail, and how they were found

Worth knowing, because both looked green:

- A `data-testid` marked *every retrieved chunk* rather than only the ones the
  model cited, so G6.3's question — "does every rendered citation resolve to
  stored evidence?" — was trivially true. Caught because Codex writes gates
  against `frontend/src/testids.ts` without reading the screens; where the
  implementation disagreed with the registry, the registry was right.
- The CI step that runs the browser gates guarded itself with a glob needing
  `globstar`, which bash does not enable, so it skipped all thirteen specs and
  reported success. Caught by comparing job duration before and after, not by
  trusting the green tick.

A gate that cannot fail is worse than no gate, because it looks like coverage.
Both fixes are recorded in `DECISIONS.md` (D22).

## The MVP definition of done, walked through

This is the ten-step journey from `CLAUDE.md` — the definition of done for the
whole project, not for one phase. Every step below is clickable in the UI today,
and the whole sequence runs as an automated gate (**G6.1**) against nginx serving
the production build, so it is checked on every pull request rather than
remembered.

Bring the stack up, migrate, seed, and load the corpus first (see *Running*),
then open `localhost:5173`.

| # | Do this | What proves it |
|---|---|---|
| 1 | Sign in as `admin@demo` | Sidebar shows the administrator's routes; `GET /api/me` returns the roles |
| 2 | **Knowledge → Upload** an IT policy (`.pdf`, `.md`, `.txt`) | 202 with a document id; the row appears immediately |
| 3 | Watch the row reach **ready** | Extracted, chunked, embedded and stored in pgvector with title, version, page and section — the metadata citations are made of |
| 4 | Sign out, sign in as `operator@demo`, file a VPN ticket | The ticket appears in the list with status `new` |
| 5 | **Run triage** | The run opens and moves `queued → running`; the structured result carries category, urgency, team, priority, confidence and citations, all Pydantic-validated |
| 6 | Read the **evidence panel** | Every retrieved chunk with its document, page and section; the cited ones marked, and any citation that does **not** resolve named rather than hidden. No valid citation, no grounding — the run fails as `ungrounded` instead of reporting success |
| 7 | The run **pauses** at `awaiting_approval` | A real LangGraph interrupt checkpointed to Postgres — the job ended; nothing is holding a connection open |
| 8 | Sign in as `approver@demo` and open the **Approval inbox** | The card shows the affected ticket, proposed action, new vs existing values, evidence, confidence, risk and agent version. The operator and the administrator both get **403** here: the agent proposes, a different person disposes |
| 9 | Approve (or edit, or reject) | The write executes against the mock ticket system, the ticket is re-fetched for confirmation, and the run reaches `completed`. Reject writes nothing and ends `rejected` |
| 10 | Open the **Dashboard** and the **Audit log** | The run is in the metrics and the recent list; the trail carries every agent step, tool call, model call and the human decision, with tokens, latency and cost |

Steps 2–3 and 5–9 are background work on the `worker` service; the UI polls and
stops polling once each settles.
