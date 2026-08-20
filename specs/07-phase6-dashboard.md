# Spec: Phase 6 — Frontend Dashboard (all MVP screens)

**Status:** Approved 2026-08-16 (decisions recorded as D21)
**Owner:** FlowForge Code Owners
**Depends on:** 06-phase5-eval-observability.md (approved + built, merged as PR #11)
**Gate to exit:** Phase 6 definition of done demoed + spec review of Phase 7

## What this phase delivers

The ten MVP screens, wired to real APIs, role-gated, and polished enough for a recorded demo. **No new backend endpoints** — Phase 5 closed the last gap, and every screen below has a finished endpoint behind it. The one backend-adjacent change is packaging: the frontend container stops being a dev server and becomes the artifact Phase 7 deploys.

This phase is where the project stops being provable by `curl` and starts being watchable.

## Scope (in) — the ten screens, exactly

1. **Login** — Auth0 redirect + callback, or the local dev issuer's seeded identities. Shows identity + roles via `GET /api/me`; logout. Reworked into the app shell rather than rebuilt (Phase 4 already made this real).
2. **Dashboard** (any persona) — `GET /api/metrics/summary` with a window selector (7/30/90 days). Metric cards for the scalars, an activity chart and an outcome donut, both derived client-side from `/api/runs` because no time-series endpoint exists. **Role-aware by absence:** cost and evaluation accuracy are simply not in a non-admin's payload, so the UI renders what it receives rather than deciding who deserves what (D19 decision 6 as amended by D20).
3. **Knowledge documents** (admin) — `GET /api/documents`: status (pending/processing/ready/failed), version, chunk count, error message on failure, reingest action.
4. **Upload document** (admin) — file picker (.pdf/.md/.txt), client-side size/type validation, `POST /api/documents` → returns to the list showing live ingestion status (poll while anything is processing).
5. **Tickets** (any persona; create is operator) — `GET /api/tickets` with filters (status, department, service, `is_eval_seed`), row → detail, "Run triage" action for operators.
6. **New ticket** (operator) — the exact MVP form: title, description, requester department, affected service, optional existing priority. Validated client-side, `POST /api/tickets`.
7. **Workflow run detail** (any persona) — the centerpiece. Status timeline, structured triage output, **evidence panel** (retrieved chunks with document title / page / section / score), the citation→chunk mapping that makes a recommendation grounded, proposal, approval state, and the run's audit entries. Polls until the run reaches a terminal status.
8. **Approval inbox** (approver decides; admin may read) — pending list → approval card exactly per the personas doc: proposed action, affected ticket, new vs existing values, evidence, confidence, risk class, agent version. Approve / Edit / Reject. Edit opens a validated form; Reject requires feedback text.
9. **Evaluation results** (admin) — `GET /api/eval/batches` list and batch detail: per-field accuracy, judge scores, hit@k, grounded rate, and the per-ticket table with expected vs actual. Batches are listed newest-first so two `agent_version`s read side by side (G5.5).
10. **Audit log** (admin) — `GET /api/audit`, filterable (run, actor, tool, date range), paginated, row expands to payload/result JSON.

**Plus one, by D21 decision 5:** a read-only **Agent configuration** view (`GET /api/config/agent`) — version, provider, models, timeouts, and the live taxonomy. CLAUDE.md permits exactly this and forbids anything more ("agent configuration lives in code + database records"). It is a panel, not a builder.

### Cross-cutting frontend requirements

- **Routing & data:** React Router for routes, TanStack Query for every read (D21 decision 1). One typed API client module; no `fetch` scattered through components.
- **Auth:** the existing `sessionStorage` token is retained. ARCHITECTURE already records httpOnly-cookie + backend session as the hardening step, and moving it is a backend change, not a screens change. 401 clears the token and returns to login.
- **Role gating is presentational, never protective.** Nav hides what a role cannot use and guarded routes render a clear "not available for your role"; the server stays the only real enforcer (G4.x). A guard that is bypassed must still fail at the API.
- **States:** every data view has loading, empty and error states. No blank screens, no spinner that never resolves.
- **Live data:** polling only (D21 decision 3) — run detail 2s until terminal, approval inbox 5s, documents 3s while processing, dashboard 15s. No backend change.
- **No business logic in the frontend:** display, forms, and calls. Grounding, scoring and authorization are decided server-side and rendered here.

### Visual design (D21 decisions 8–11)

- **Both themes with a toggle**, dark by default. Every colour is a CSS custom property defined twice — `:root` for dark, `[data-theme="light"]` for light — so no component ever names a colour. Preference persists in `localStorage`. `prefers-color-scheme` is deliberately **not** consulted — it made "dark by default" mean "whatever the OS says", which changed what a demo recording looked like and what a browser gate saw.
- **Developer-tool precision** (Cursor / Linear register): near-monochrome surfaces, one restrained accent, hairline borders rather than shadows, tight vertical rhythm, and status carried by small badges. Technical values — run ids, chunk refs, model names, hashes, JSON — are always monospace.
- **Self-hosted Inter + JetBrains Mono** as `woff2` under `frontend/public/fonts`, declared with `@font-face` and `font-display: swap`. Static assets, not packages; no CDN, which the container could not reach anyway. Tabular figures (`font-variant-numeric: tabular-nums`) on every metric so digits do not jitter while polling.
- **Left sidebar, compact density** (~36px rows). The sidebar lists only the routes the current role can use, which is what makes G6.2's role slicing legible in a single screenshot per persona.

## Scope (out)

- Drag-and-drop agent builder (explicitly excluded by CLAUDE.md).
- **User & role management** — the Administrator persona mentions it, but the ten-screen list omits it and no endpoint exists. Building it means new backend write APIs inside a frontend phase (D21 decision 5). Roles are seeded by `scripts/seed.py`.
- Real-time push (SSE/WebSocket), mobile layouts (desktop-first, sane at laptop widths), i18n.
- A charting dependency. Every chart is hand-rolled SVG in `components/charts.tsx` (D21 decision 6, widened) — an area chart, a donut, ring gauges and sparklines, all reading the theme through CSS custom properties.

## Gates & checks

- **G6.1 Golden path, automated:** the full MVP definition-of-done (steps 1–10) driven through the browser against the real stack by Playwright — login, upload, index, file ticket, triage, see evidence with ≥1 valid citation, approve, ticket actioned, run completed, audit shows it. This is the demo, executed in CI.
- **G6.2 Role slicing:** operator, approver and administrator each see a different nav and a different dashboard payload. Direct navigation to a forbidden route renders the refusal, and the underlying API call is rejected by the server.
- **G6.3 Evidence fidelity:** every citation rendered on run detail resolves to a chunk in that run's stored evidence. A citation the UI cannot resolve is a failure, not a blank.
- **G6.4 Edit path:** editing a proposal in the inbox round-trips validated values, and the audit view shows both the original and the edited proposal.
- **G6.5 Empty and error states:** a fresh org renders empty states on every screen; a stopped backend renders error states rather than a crash or an infinite spinner.

### The selector contract

Gates bind to `data-testid` attributes, never to text or CSS classes — a gate that breaks when a heading is reworded is a gate nobody trusts. The registry lives in `frontend/src/testids.ts`, is exported as a typed constant, and is the interface Codex's gates are written against. **Changing a testid is a spec change**, because it breaks a gate by design.

## Definition of done

- All ten screens plus the config panel exist, wired to real endpoints, role-gated, with loading/empty/error states.
- G6.1 passes in CI — the MVP journey, in a browser, against the real stack. This is the demo minus deployment.
- G6.2–G6.5 pass.
- The frontend container serves a production build; `tsc` type-checks in CI.

## Risks

- **Frontend scope creep** — the prettiest rabbit hole. Mitigation: the ten screens are a closed list; anything else is post-MVP and gets written down rather than built.
- **Playwright flake** turning a real gate into noise. Mitigation: bind to testids, await explicit states rather than sleeping, and let the run-status poll drive waits.
- **The evidence panel is the screen that sells the project** and also the fiddliest (citation→chunk mapping across page/section metadata). Mitigation: G6.3 asserts fidelity rather than appearance.

## Task plan

`[CC]` = Claude Code (implementation). `[CX]` = Codex (gate tests, adversarial probes, cold review — never a shipped component, per D6).

| # | Owner | Task | Proves |
|---|---|---|---|
| 1 | [CC] | Record D21; update this spec with the resolved decisions and this plan | — |
| 2 | [CC] | Frontend foundation: deps, router, typed API client, auth guard, app shell + role-aware nav, design tokens | — |
| 3 | [CC] | **Selector contract** — `frontend/src/testids.ts` + the table in this spec, so gates can be written before screens exist | — |
| 4 | [CX] | ~~**Gate tests first:** G6.1–G6.5 in `tests/phase6/`, bound to the selector contract~~ **Done** — 13 specs, all green | all |
| 5 | [CC] | Login reworked into the shell; 401 handling; logout | G6.2 |
| 6 | [CC] | Dashboard — metric cards, window selector, SVG outcome chart, role-aware rendering | G6.2 |
| 7 | [CC] | Knowledge documents + Upload, with ingestion-status polling and reingest | G6.5 |
| 8 | [CC] | Tickets list + filters + New ticket form + "Run triage" | G6.1 |
| 9 | [CC] | Workflow run detail — timeline, structured output, evidence panel, citation mapping, status polling | G6.1, G6.3 |
| 10 | [CC] | Approval inbox — card per personas doc, Approve / Edit / Reject | G6.1, G6.4 |
| 11 | [CC] | Evaluation results — batch list + batch detail + per-ticket table | — |
| 12 | [CC] | Audit log — filters, pagination, JSON row expansion | G6.4 |
| 13 | [CC] | Read-only agent configuration panel | — |
| 14 | [CC] | Loading / empty / error state pass across every screen | G6.5 |
| 15 | [CC] | Production Dockerfile (build + nginx), compose wiring, CI: `tsc`, Vitest, Playwright | — |
| 16 | [CC] | README / ARCHITECTURE / DECISIONS updated — **in this PR, before merge** | — |
| 17 | [CX] | Adversarial pass + cold diff review | — |

**Sequencing note:** unlike the backend phases, an end-to-end gate cannot be written before the thing it drives exists. Task 3 is what preserves the gates-first discipline: the selector contract is the interface, so Codex writes G6.1–G6.5 at task 4 against screens that do not exist yet, and they stay red until tasks 5–13 land. That red window is expected and is the point.

**Dependency:** G1.5 (the unreviewed answer key) remains open from Phase 1 and is unaffected by this phase — Phase 6 renders eval results, it does not produce them.
