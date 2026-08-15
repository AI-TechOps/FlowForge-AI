# Phase 4 adversarial pass + cold diff review

**From:** Codex (adversarial/review lanes)
**Date:** 2026-08-15
**Branch:** `feat/phase4-auth-tenant` at `40811ba`
**Diff reviewed:** `origin/main...HEAD` (9 commits, 44 files)
**Routing:** Advisory findings for FlowForge code owners under spec 10. No runtime code was changed.

## Oracle and scope

I read `specs/05-phase4-auth-tenant.md` and D18 before the implementation
diff and treated G4.1-G4.6, the approved 30-cell role matrix, first-login
provisioning, application-level tenant enforcement, the background-job
contract, and the terminal/dead-letter guarantees as the oracle. The local
`main` ref is stale, so the PR review correctly uses `origin/main...HEAD`.

I cold-read the full Phase 4 diff, rebuilt and migrated the stack, ran all
Phase 4 gates, and added focused probes under `tests/adversarial/`. The Docker
ARM images currently die with SIGILL while importing newly resolved binary
dependencies (`redis` and `jwt`); to keep this environmental failure from
blocking product evidence, I ran an equivalent native backend and worker from
an isolated `/private/tmp` virtualenv against the compose Postgres and Redis.
No repository dependency or runtime file was changed for that workaround.

## Result summary

Phase 4 gates against the local-provider/fake-LLM stack:

```text
57 passed
```

New Phase 4 adversarial probes:

```text
2 passed, 7 failed
```

The seven failures reproduce the findings below. The two passing controls
prove that client-supplied token roles/org do not elevate an operator and that
the local auth provider refuses `APP_ENV=prod`.

---

## Finding 1 — HIGH: approval detail follows unscoped relationships into another tenant

`backend/app/api/approvals.py:80-85` scopes the approval itself after an
unfiltered `session.get`, then loads its `Run` and `Ticket` by primary key with
no organization predicate and returns their output, evidence, title, status,
priority, and assignment.

The schema permits an organization-A approval to reference an organization-B
run: the foreign key covers only `run_id`, not `(org_id, run_id)`. The live
probe inserted exactly that inconsistent relationship and requested the card
as A's approver. The API returned HTTP 200 with B's unique summary, evidence,
ticket id, title, status, and priority. The expected tenant-boundary response
is 404 with no marker leakage.

The precondition is a mismatched relational row rather than a public request,
but Phase 4 deliberately relies on application-layer enforcement instead of
RLS, and D18 explicitly requires one scoping helper plus an automated check
against direct unscoped tenant queries. Neither exists; the diff still contains
direct tenant-model `session.get` calls throughout APIs and workers. A worker
bug, import, migration, or operator repair that creates one bad relation turns
into a product-API cross-tenant disclosure.

Failing probe:
`test_phase4_approval_detail_cannot_follow_a_cross_tenant_relationship`.

## Finding 2 — HIGH: a duplicate initial queue delivery can reopen a terminal run

`backend/app/agents/runner.py:47-63` verifies only run id and organization. It
does not atomically require `status == queued` before incrementing attempts and
setting the row to `running`.

The probe seeded a completed run and delivered `execute_run` again with the
correct org. A controlled graph response reached the ordinary interrupt path;
the completed run regressed to `awaiting_approval` and gained a new pending
approval. A duplicate or stale queue message can therefore erase terminality
and potentially expose the write path again.

The initial job needs a compare-and-swap claim from `queued` to `running`;
terminal and already-claimed states must be no-ops, as `resume_run` already
does for duplicate resume deliveries.

Failing probe:
`test_phase4_duplicate_execute_delivery_cannot_reopen_a_terminal_run`.

## Finding 3 — HIGH: crashed triage jobs never recover or reach `dead_letter`

`execute_run` commits `running` before invoking the graph. A process-killing
poison message therefore leaves the row in `running`. Recovery at
`backend/app/agents/runner.py:204-261` scans `executing`, decided
`awaiting_approval`, and old `queued` rows, but never `running`.

The probe created two old `running` rows: one below the retry limit and one
already at `MAX_RUN_ATTEMPTS`. Recovery enqueued neither. The first remained
stranded and the exhausted one remained `running` with no failure reason,
rather than becoming `failed/dead_letter`.

This also makes the attempt boundary internally inconsistent. `_dead_letter`
runs only when a future pickup increments attempts above the configured max,
while arq itself is configured with `max_tries == MAX_RUN_ATTEMPTS`; after the
last process-killing attempt, there need not be another invocation to execute
that branch.

Failing probe:
`test_phase4_recovery_handles_running_jobs_and_dead_letter_boundary`.

## Finding 4 — HIGH: the documented Auth0 setup cannot supply first-login email

The frontend requests `openid profile email`, exchanges the code, discards the
ID token, and sends only `access_token` to the API
(`frontend/src/auth.ts:109-151`). The backend then expects a top-level `email`
inside that custom-API access token (`backend/app/auth/provider.py:116-119`) and
returns 403 for first login when it is absent
(`backend/app/auth/principal.py:86-91`).

Auth0's own token documentation says a custom-API access token ordinarily
contains authorization information, while standard profile/email information
is returned in the ID token. Adding an OIDC profile claim such as `email` to an
access token requires an Auth0 Action/custom-claim step. The README setup lists
only the SPA, API, callback URLs, and users; it configures no Action and the
backend does not call `/userinfo`. Consequently, creating the known-open Auth0
tenant exactly as documented still leaves every unlinked seed user at 403.

This is distinct from the known-open fact that no Auth0 tenant exists: it is a
contract defect in the configuration that will remain after one is created.
The eventual source should also prove `email_verified`, which the current
`TokenClaims` model does not carry.

Relevant primary documentation:
[Auth0 scopes and claims](https://auth0.com/docs/get-started/apis/scopes/sample-use-cases-scopes-and-claims),
[Auth0 access tokens](https://auth0.com/docs/secure/tokens/access-tokens).

## Finding 5 — MEDIUM: first-login ambiguity ignores already-linked tenants

`backend/app/auth/principal.py:93-111` correctly recognizes that email is only
unique within an organization and says duplicate emails must be refused. The
query, however, counts only rows where `auth_subject IS NULL`.

The live probe started with a linked A user, then added an unlinked B user with
the same email and presented a valid token with a second subject. Because the A
row was excluded, B was the sole candidate and `/api/me` returned 200 for B.
The same email now maps different subjects into different tenants even though
multi-org users are explicitly out of scope and the code claims ambiguity is
rejected.

Failing probe:
`test_phase4_first_login_rejects_email_already_bound_in_another_tenant`.

## Finding 6 — MEDIUM: the hand-written PKCE flow has no `state` binding

`frontend/src/auth.ts:109-154` stores a PKCE verifier but sends no random
`state`, stores no expected state, and never compares the callback's state
before exchanging its code. Auth0 documents `state` as the client-generated,
non-guessable correlation value that must be checked to prevent authorization
CSRF. The official SPA SDK normally handles this, but this PR implements the
flow directly.

Failing probe:
`test_phase4_auth0_pkce_callback_is_bound_to_the_login_with_state`.

Primary reference:
[Auth0 state-parameter guidance](https://auth0.com/docs/secure/attack-protection/state-parameters).

## Finding 7 — MEDIUM: background job payloads omit the acting user id

D18 requires background payloads to carry both `org_id` and acting user id.
All three enqueue contracts carry only resource id plus org id
(`backend/app/ingestion/queue.py:18-32`): ingestion loses the uploader, triage
loses the triggering administrator/operator, and resume loses the deciding
human at the queue boundary. Recovery cannot reconstruct the initial actor
because `Run` stores no triggering user.

Organization scoping is present, so this is not the direct cross-tenant failure
the G4.6 happy path attacks. It is an attribution and defense-in-depth gap:
workers cannot verify the complete authority context the spec says the caller
placed on the job, and the audit trail cannot answer which human triggered the
initial work.

Failing probe:
`test_phase4_background_job_payloads_carry_the_acting_user`.

## Finding 8 — MEDIUM: `reset_corpus --org-id` deletes one tenant and uploads into another

`scripts/reset_corpus.py:37-57` resolves and directly deletes documents for the
selected `--org-id`. Upload/list calls at `:60-105` always call
`auth_header(base_url)` with its default `demo@demo` identity; `org_id` is not
used to select or verify the token.

The isolated probe called `_upload` for two different organizations and
captured identical authorization contexts. In practice, choosing a non-demo
org can delete that org's corpus from Postgres and then upload the replacement
documents into the demo token's tenant. Before the destructive wipe, the
script must authenticate as an administrator in the selected org and verify
`/api/me.org_id` matches it, or remove the misleading cross-org option.

Failing probe:
`test_phase4_reset_corpus_cannot_wipe_one_org_and_authenticate_as_another`.

---

## Additional cold-review notes

- The Phase 4 README section obtains a token, but the Phase 1-3 curl examples
  at `README.md:84-163` remain unauthenticated and still show `X-User-Id` for a
  decision. Following them now yields 401/403 rather than the documented
  walkthrough.
- Migration `0005` has a runnable downgrade for the column, but intentionally
  leaves the `dead_letter` enum label behind. That is not schema-equivalent to
  revision `0004`, despite task 9 asking for a working downgrade; code owners
  should decide whether an inert label meets their downgrade contract.
- The general adversarial CI step sets only Phase 2 live flags. The new Phase 4
  fixture falls back to `DATABASE_URL` and the live stack is normally still
  present, so these probes run today; however, if the backend disappears they
  can skip because `PHASE4_REQUIRE_LIVE` is absent. The step should carry the
  Phase 3 and Phase 4 live variables explicitly.
- Rebuilding on this Apple/Docker host resolved current unpinned ARM wheels for
  both `redis` and `jwt` that exit with SIGILL on import. CI is amd64 and may
  not reproduce it, but dependency ranges currently make a clean local build
  architecture-sensitive.

## Test-change review

- Changes to Codex's Phase 4 files after `c2af16d` are Ruff formatting only;
  no assertion or expected status changed.
- The Phase 1-3 retrofit adds bearer tokens at the shared client boundary and
  deliberately keeps the old org/user headers, query values, and body values
  so G4.5 proves they no longer select a tenant. Existing assertions were not
  weakened.
- The dedicated Phase 4 CI step sets `PHASE4_REQUIRE_LIVE=1` and runs all 57
  gates; it does not silently skip a red stack.

## Positive checks

- G4.1-G4.6 all pass: scripted unauthenticated route walk, exact 30-cell role
  matrix, segregation of duties, cross-tenant resource matrix, org spoofing,
  and interleaved shared-worker jobs.
- A dev-token request carrying administrator/approver roles and a foreign org
  cannot elevate an operator; the database remains authoritative on the next
  request.
- The local auth provider refuses production configuration, and dev-only
  token, retrieval, and test-hook routes retain independent production guards.
- Run detail scopes audit rows by both run id and principal organization, and
  the mock adapter recorder now resolves the run under the caller's tenant.
