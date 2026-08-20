# Phase 6 adversarial pass + cold diff review

**From:** Codex (adversarial/review lanes)

**Date:** 2026-08-19

**Branch/head reviewed:** `feat/phase6-dashboard` at `29a78ef`

**Diff reviewed:** `origin/main...HEAD` (15 commits, 60 files)

**Oracle:** `specs/07-phase6-dashboard.md` and D21

**Routing:** Advisory findings for FlowForge code owners under D6. No runtime code was changed.

## Review disposition

Do not merge without code-owner triage of the failures below. The production
image builds and all official gates are green, but seven independent browser
probes reproduce contract gaps that those gates do not cover:

```text
Production Docker build (tsc + Vite): passed
Phase 6 gates (G6.1-G6.5):            13 passed
Phase 6 adversarial probes:            0 passed, 7 failed
Playwright collection / diff check:    passed
```

Run the probes against the compose stack with:

```bash
PHASE6_BASE_URL=http://localhost:5173 \
  npx playwright test --config=tests/adversarial/phase6.playwright.config.ts
```

The selector contract itself helped leave three omissions invisible: it has no
ids for the required department filter, audit date range, or affected ticket
on an approval card. The probes use accessible controls or the enclosing
contracted component where no narrower id exists. Additive ids are permitted
by D21; weakening the probes is not the resolution.

## Finding 1 — HIGH: a data-view 401 clears storage but leaves the authenticated shell mounted

`frontend/src/api/client.ts:106-109` removes the token on any 401, but the live
React token at `frontend/src/App.tsx:50-61` is independent state and is never
notified. Only the identity query controls the authentication boundary, and it
may remain fresh for five minutes. A 401 from Tickets therefore removes the
stored credential while leaving the prior identity, sidebar, and data view on
screen with an error. It does not return to login as the Phase 6 cross-cutting
auth contract requires.

Besides trapping the user until a reload, this keeps already-cached data
visible after the session has expired. Route every `Unauthenticated` failure
through one application-level logout transition that clears both auth state
and query data.

Failing probe:
`a 401 from any data view clears the live session and returns to login`.

## Finding 2 — HIGH: the approval card does not identify the affected ticket

The approval payload already has `ticket_id`, but
`frontend/src/screens/Approvals.tsx:152-169` renders only the run id,
confidence, and agent version before presenting the proposed changes and
decision buttons. The affected ticket is absent even though the Phase 6 screen
contract and the canonical approval-card contents in `DECISIONS.md` require
it.

An approver can therefore authorize a priority/team write without being told
which ticket will change. Render at least the ticket identifier and preferably
the ticket title/service fetched from the existing ticket endpoint.

Failing probe:
`an approval card identifies the ticket whose state will change`.

## Finding 3 — HIGH: the edit path accepts arbitrary strings as typed action values

`frontend/src/screens/Approvals.tsx:394-408` considers an edit valid whenever
its string differs from the proposal. The form at lines 432-446 uses the same
unconstrained text input for every action and submits values such as
`P99-not-a-priority` directly to the decision endpoint. There is no enum,
shape, or non-empty validation based on the proposed action.

That contradicts both the approval screen's “validated form” contract and
G6.4's requirement that validated values round-trip. The client should render
field-appropriate controls and refuse values outside the governed taxonomy
before the human authorizes the write; server validation remains mandatory.

Failing probe:
`the edit form rejects an invalid typed value before POSTing a decision`.

## Finding 4 — MEDIUM: operators and approvers lose the run's embedded audit entries

Workflow run detail is an any-persona screen and explicitly includes the run's
audit entries. `GET /api/runs/{id}` already returns tenant-scoped
`audit_entries` to every persona (`backend/app/api/runs.py:204-217`). The
frontend `Run` type omits that field at `frontend/src/api/types.ts:84-100`.
Instead, Run Detail calls the administrator-only global audit endpoint and
hides the entire panel behind `isAdmin` at
`frontend/src/screens/RunDetail.tsx:133-136,415-471`.

Render the entries embedded in the run-detail response for all personas. The
global `/api/audit` route can remain administrator-only; no authorization
change is needed.

Failing probe:
`any persona sees the audit entries embedded in run detail`.

## Finding 5 — MEDIUM: the dashboard window does not govern its charts

The metrics query follows the selected 7/30/90-day window, but the outcome
donut at `frontend/src/screens/Dashboard.tsx:93-112` counts every run in the
unwindowed 200-row history response. In the probe, switching from 30 days to 7
correctly changed the total-runs metric from 2 to 1 while the donut stayed at
2 and continued counting a 20-day-old run.

The activity chart has a second inconsistency: lines 76-81 cap every selected
window at 30 days, so selecting 90 days still labels and plots only the last
30. D21 says the selector governs the dashboard and that every chart series is
real. Filter the history once by the selected cutoff and derive both charts
from that same set; do not silently relabel a 90-day selection as 30 days.

Failing probe:
`dashboard outcome data follows the selected 7-day window`.

## Finding 6 — MEDIUM: Tickets omits the required department filter

The screen contract requires status, department, service, and eval-seed
filters. `frontend/src/screens/Tickets.tsx:39-50` tracks and sends only status,
service, and `is_eval_seed`; the controls at lines 92-125 mirror the same
three. The API hook already accepts `department`, so this is a frontend
omission rather than missing backend surface.

Failing probe:
`the required ticket filters include requester department`.

## Finding 7 — MEDIUM: Audit omits the required date-range filter

The Audit screen must be filterable by run, actor, tool, and date range.
`frontend/src/screens/Audit.tsx:49-64` models only actor, tool, and run, and the
controls at lines 86-111 expose only those fields. `useAudit` already supports
`since` and `until`, so no backend work is needed.

Failing probe:
`the audit log exposes both ends of its required date range`.

## Positive cold-review checks

- The rebuilt production nginx image passes the complete 13-test G6.1-G6.5 suite.
- CI now invokes the Phase 6 gates unconditionally instead of relying on a non-portable recursive glob.
- Role-specific navigation is paired with server-side 403 checks; the UI is not treated as the security boundary.
- Run polling stops at terminal states, approval polling is role-aware, and document polling stops after ingestion settles.
- Citation rendering now distinguishes cited evidence from merely retrieved chunks and surfaces unresolved citations explicitly.
- The API client centralizes bearer attachment and typed error parsing; the remaining 401 defect is its missing application-state handoff.
- Both themes use CSS variables, fonts are self-hosted, and the container serves a production build rather than Vite's development server.

The probes live in
`tests/adversarial/test_phase6_dashboard_boundaries.spec.ts`; their isolated
Playwright configuration lives beside them so the official Phase 6 gate
configuration remains unchanged.
