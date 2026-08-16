# Spec: Phase 4 — Authentication, Roles & Tenant Enforcement

**Status:** Approved 2026-08-15 (decisions recorded as D18)
**Owner:** FlowForge Code Owners
**Depends on:** 04-phase3-actions-approval.md (approved + built, merged as PR #9)
**Gate to exit:** Phase 4 definition of done demoed + spec review of Phase 5

## What this phase delivers

Real login and real enforcement. OAuth2 via Auth0 (free dev tier), role-based access on every endpoint, org_id derived from the authenticated user (never from client input), and background processing hardened.

## Scope (in)

### 1. OAuth2 / OIDC login (Auth0)
- Authorization Code flow with PKCE. Frontend redirects to Auth0; the backend **validates the Auth0 access token on every request** against a cached JWKS and issues no token of its own (D18 decision 2).
- **Auth sits behind a provider abstraction** (D18 decision 1), the same shape as the LLM provider: `Auth0Provider` fetches the real tenant's JWKS, and a local dev issuer mints tokens from a keypair generated at startup and refuses to load when `APP_ENV=prod`. Validation is one code path for both — the gates below exercise the shipping enforcement path offline, and only the issuer differs.
- **Roles are read from `user_roles`, never from token claims** (D18 decision 3). The token says who; the database says what they may do.
- `users.auth_subject` column links Auth0 `sub` → our user row. First-login provisioning: if the subject's email matches a seeded user, link it; otherwise 403 (no self-signup in MVP).
- Logout endpoint + token expiry handling.
- `GET /api/me` — returns id, email, roles, org for the authenticated principal. Powers the Phase 6 Login screen's identity display and the frontend route guards.

### 2. Role enforcement (RBAC)
- Dependency/decorator per router: `require_roles(...)`.
- **The approved matrix** (D18 decision 4). This is the table G4.2 asserts, one test per cell:

| Endpoint | administrator | operator | approver |
|---|:--:|:--:|:--:|
| `POST /api/documents`, `GET /api/documents` | ✅ | ❌ | ❌ |
| `POST /api/retrieve` (dev-only) | ✅ | ❌ | ❌ |
| `POST /api/tickets` | ✅ | ✅ | ❌ |
| `GET /api/tickets`, `GET /api/tickets/{id}` | ✅ | ✅ | ✅ |
| `POST /api/runs` (trigger triage) | ✅ | ✅ | ❌ |
| `GET /api/runs`, `GET /api/runs/{id}` | ✅ | ✅ | ✅ |
| `GET /api/approvals` (inbox), `GET /api/approvals/{id}` | ✅ | ❌ | ✅ |
| **`POST /api/approvals/{id}/decision`** | ❌ | ❌ | ✅ |
| `/api/test/*` (dev-only) | ✅ | ❌ | ❌ |
| `GET /api/me` | ✅ | ✅ | ✅ |

- **Administrator deliberately cannot decide approvals.** Administrator is a configuration role; letting it approve would place one principal on both sides of D4/D5. The instinct to add an admin override is exactly why the exclusion is written down rather than left to judgement. A person who must approve is granted the approver role explicitly — the personas doc already allows one human to hold several.
- **The proposing run's context can never satisfy the approver check**: authorisation to write comes only from a decided approval carried by a human session (Phase 3's `approval_granted`), and no agent or worker principal can reach the decision endpoint at all.
- Metrics/eval/audit views land in Phase 5; they enter this matrix when those endpoints exist.

### 3. Tenant enforcement (hardening what Phase 0 started)
- `org_id` comes ONLY from the authenticated principal. Any client-supplied org_id is ignored/rejected. The `X-Org-Id` and `X-User-Id` placeholder headers (D17 decision 3) are deleted outright, not merely ignored.
- A single query-scoping helper applies org filtering, backed by an **automated check that flags direct unscoped queries on tenant models** (D18 decision 7). A full repository layer was rejected as too much simultaneous change in a phase that already retrofits auth across every router; the automated check is what keeps D7 from depending on reviewer attention, which has already failed once (Codex finding F6, the run-scoped call recorder that leaked across tenants). Postgres RLS remains the deferred production answer.
- **Dev-only routes authenticate too** (D18 decision 5), keeping their `APP_ENV=prod` 404 guard as a second, independent control. There is no auth exemption list.
- Cross-tenant tests: for every resource type (documents, chunks via retrieve, tickets, runs, approvals, audit), org A token cannot read or mutate org B rows (404, not 403 — don't leak existence).

### 4. Background processing hardening
- Job payloads carry org_id + acting user id; workers enforce the same scoping.
- Poison-message handling: max retries, then the run dead-letters via a `dead_letter` value on the existing `FailureReason` enum plus an attempt counter on `runs` (D18 decision 6). No separate DLQ table — a dead-lettered run stays visible where operators already look, and the run detail already renders typed failure reasons.
- Graceful shutdown: in-flight jobs finish or re-queue (no lost runs).
- Queue recovery: Postgres is the source of truth for run state — Redis losing queued jobs (restart, eviction) must not lose runs. On worker startup, `queued` runs older than a threshold are re-enqueued from Postgres.

### 5. Seed users
- `admin@demo`, `operator@demo`, `approver@demo` (distinct), plus one all-roles superuser for demo convenience. Mapped to Auth0 test users.

## Scope (out)
- Self-signup, password reset flows (Auth0 hosted pages handle credentials; we do no password handling at all).
- SSO/SAML beyond one OAuth2 provider. Multi-org users. API keys / machine-to-machine tokens.
- Postgres RLS (documented as the production hardening step; application-level enforcement is the MVP mechanism).

## Gates & checks
- **G4.1 AuthN:** every /api route except health/login rejects unauthenticated requests (401). Scripted walk of the route table.
- **G4.2 AuthZ matrix:** role matrix test — each (role, endpoint) pair behaves per the matrix; operator cannot decide approvals; approver cannot upload documents.
- **G4.3 Segregation of duties:** (a) a principal without the approver role gets 403 from the decision endpoint — including the operator who triggered the run; (b) no agent/system principal can call the decision endpoint at all — only authenticated human sessions; (c) a user approving a run they triggered succeeds only when they hold an explicit approver role grant (allowed per personas doc). All three asserted in the matrix test.
- **G4.4 Tenant matrix:** cross-tenant access test across all resource types → 404, no data leakage in errors.
- **G4.5 Org spoofing:** requests carrying a foreign org_id in body/query are served strictly under the token's org (or rejected).
- **G4.6 Job scoping:** a queued job for org A processed by a shared worker cannot touch org B rows (test with interleaved jobs).

## Definition of done
- Login via Auth0 works for all seed users; roles enforced per matrix; MVP step 1 ("Admin logs in") is real.
- All prior-phase endpoints now enforce auth + roles + tenant scoping with green gates G4.1–G4.6.
- Background jobs are org-scoped and survive worker restarts without losing runs.

## Risks
- Auth0 config friction (callback URLs, JWKS). Mitigation: keep one tenant, one application, document exact settings in README.
- **No Auth0 tenant exists yet, and only a code owner can create one.** Development proceeds against the local dev issuer (D18 decision 1), which is a supported path rather than a workaround — but the Auth0 half of G4.1 stays unproven until a real tenant, SPA application, API identifier, callback URLs, and test users exist in `.env`.
- Retro-fitting enforcement breaks earlier tests. Mitigation: test fixtures get a token helper from day one of this phase; earlier suites updated in the same PR (task 13). Because those suites are Codex-owned, the fix cannot come from the same task that breaks them — hence the planned red window between tasks 6 and 13.

## Task plan

`[CC]` = Claude Code (implementation). `[CX]` = Codex (gate tests, adversarial probes, cold review — never a shipped component, per D6).

| # | Owner | Task | Proves |
|---|---|---|---|
| 1 | [CC] | Record D18; update this spec with the resolved decisions, the role matrix, and this plan | — |
| 2 | [CX] | **Gate tests first:** G4.1–G4.6 in `tests/phase4/`, written against the matrix above and the token-helper contract from task 3 | all |
| 3 | [CC] | Auth provider abstraction: JWKS validation, `Auth0Provider`, prod-refused local dev issuer, settings + `.env.example` | G4.1 |
| 4 | [CC] | `Principal` (user, org, roles, subject) + `current_principal` dependency; `auth_subject` linked at first login; unknown subject → 403, no self-signup | G4.1 |
| 5 | [CC] | `GET /api/me`, logout, token expiry handling | G4.1 |
| 6 | [CC] | `require_roles(...)` applied to every existing router per the matrix | G4.2 |
| 7 | [CC] | Segregation of duties on the decision endpoint: approver-only, no agent/system principal, explicit-grant case | G4.3 |
| 8 | [CC] | `org_id` strictly from the principal; delete `X-Org-Id`/`X-User-Id`; scoping helper + unscoped-query check | G4.4, G4.5 |
| 9 | [CC] | Migration 0005: `runs.attempts`, `dead_letter` failure reason, `users.auth_subject` index — with a working `downgrade()` | — |
| 10 | [CC] | Worker hardening: org-scoped job payloads, poison-message dead-lettering, graceful shutdown, queued-run recovery from Postgres | G4.6 |
| 11 | [CC] | Seed users: distinct `admin@demo`, `operator@demo`, `approver@demo` + an all-roles superuser for demo convenience | G4.2 |
| 12 | [CC] | Update `scripts/eval_baseline.py` and `scripts/reset_corpus.py` to authenticate instead of sending `X-Org-Id` | — |
| 13 | [CX] | Retrofit the Phase 0–3 gate suites onto the token helper | regression |
| 14 | [CC] | Minimal PKCE login round-trip in the frontend: login, callback, `/api/me` rendered. No dashboard chrome — Phase 6 owns the screens | DoD step 1 |
| 15 | [CC] | README (exact Auth0 settings, local dev token flow), ARCHITECTURE and DECISIONS updates — **in this PR, before merge** | — |
| 16 | [CX] | Adversarial pass + cold diff review | — |

**Sequencing note:** task 6 turns the Phase 0–3 suites red, and task 13 turns them green again. That window is planned. Tasks 3–5 are a hard prerequisite for task 2, so Codex needs the token-helper contract before it can write the gates — task 3 defines it.

Task 14 exists because the definition of done says MVP step 1 is *real*, and a login reachable only by `curl` does not meet that bar. It is deliberately the smallest thing that does.
