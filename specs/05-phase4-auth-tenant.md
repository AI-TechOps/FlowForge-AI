# Spec: Phase 4 — Authentication, Roles & Tenant Enforcement

**Status:** Draft — awaiting review
**Owner:** FlowForge Code Owners
**Depends on:** 04-phase3-actions-approval.md (approved + built)
**Gate to exit:** Phase 4 definition of done demoed + spec review of Phase 5

## What this phase delivers

Real login and real enforcement. OAuth2 via Auth0 (free dev tier), role-based access on every endpoint, org_id derived from the authenticated user (never from client input), and background processing hardened.

## Scope (in)

### 1. OAuth2 / OIDC login (Auth0)
- Authorization Code flow with PKCE. Frontend redirects to Auth0; backend validates the token (JWKS), issues its own session JWT (or validates Auth0 access token per request — pick in plan review).
- `users.auth_subject` column links Auth0 `sub` → our user row. First-login provisioning: if the subject's email matches a seeded user, link it; otherwise 403 (no self-signup in MVP).
- Logout endpoint + token expiry handling.
- `GET /api/me` — returns id, email, roles, org for the authenticated principal. Powers the Phase 6 Login screen's identity display and the frontend route guards.

### 2. Role enforcement (RBAC)
- Dependency/decorator per router: `require_roles(...)`.
  - Documents upload/manage → admin.
  - Tickets create / triage trigger → operator (admins may also, per personas doc).
  - Approval decisions → approver ONLY. **The proposing run's context can never satisfy the approver check** (segregation of duties in code).
  - Metrics/eval/audit views → admin (dashboard read: any authenticated role sees role-appropriate slices; exact matrix in plan).
- Role matrix documented in this spec's plan and tested per endpoint.

### 3. Tenant enforcement (hardening what Phase 0 started)
- `org_id` comes ONLY from the authenticated principal. Any client-supplied org_id is ignored/rejected.
- A single query-scoping utility (session/repository layer) applies org filtering; direct unscoped queries flagged in code review convention.
- Cross-tenant tests: for every resource type (documents, chunks via retrieve, tickets, runs, approvals, audit), org A token cannot read or mutate org B rows (404, not 403 — don't leak existence).

### 4. Background processing hardening
- Job payloads carry org_id + acting user id; workers enforce the same scoping.
- Poison-message handling: max retries then dead-letter status visible in audit.
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
- Retro-fitting enforcement breaks earlier tests. Mitigation: test fixtures get a token helper from day one of this phase; earlier suites updated in the same PR.

## Task plan
*(Filled after spec approval — review gate.)*
