# Spec: Phase 6 — Frontend Dashboard (all MVP screens)

**Status:** Draft — awaiting review
**Owner:** FlowForge Code Owners
**Depends on:** 06-phase5-eval-observability.md (approved + built)
**Gate to exit:** Phase 6 definition of done demoed + spec review of Phase 7

## What this phase delivers

The ten MVP screens, wired to real APIs, role-gated, and polished enough for a recorded demo. Nothing new in the backend except small read endpoints if a screen exposes a gap.

## Scope (in) — the ten screens, exactly

1. **Login** — redirects to Auth0; handles callback; shows logged-in identity + roles (via `GET /api/me`, Phase 4); logout.
2. **Dashboard** — the metrics from `GET /api/metrics/summary`, with a time-window selector. Cards + one or two simple charts. Role-aware (admin sees all; others see role-appropriate slice).
3. **Knowledge documents** (admin) — list with status (pending/processing/ready/failed), version, chunk count, error message on failures.
4. **Upload document** (admin) — file picker (.pdf/.md/.txt), size validation client-side, progress → returns to list showing live ingestion status (poll).
5. **Tickets** (operator) — list with filters (status, department, service, eval-seed flag), row → detail, "Run triage" action.
6. **New ticket** (operator) — the exact MVP form (title, description, requester department, affected service, optional priority) with validation.
7. **Workflow run detail** — the centerpiece screen: status timeline, structured triage output, **evidence panel** (retrieved chunks with document title/page/section/score and claim-to-citation mapping), proposal, approval state, audit entries. Read-only view of agent config via `GET /api/config/agent` (Phase 5) — satisfies "read-only configuration page".
8. **Approval inbox** (approver) — pending approvals list → approval card exactly per personas doc (proposed action, affected ticket, new vs existing values, evidence, confidence, risk class, agent version) with Approve / Edit / Reject. Edit opens a validated form; Reject requires feedback text.
9. **Evaluation results** (admin) — eval batches list, batch detail: per-field accuracy, judge scores, hit@k, grounded rate; agent_version comparison table. Backed by `GET /api/eval/batches` (Phase 5).
10. **Audit log** (admin) — filterable table (run, actor, tool, date), row expands to payload/result JSON. Backed by `GET /api/audit` (Phase 5).

### Cross-cutting frontend requirements
- Auth: token handling (held in memory or an httpOnly cookie — decided at plan review; never localStorage), auto-redirect on 401, role-based route guards AND role-based nav visibility (server remains the real enforcer).
- States: every data view has loading / empty / error states. No blank screens.
- API client: single typed client module; no fetch calls scattered in components.
- Styling: clean, consistent, professional (this is a portfolio piece — it will be screenshotted). One component library or a small design-token set; no visual sprawl.
- No new business logic in the frontend: display + forms + calls only.

## Scope (out)
- Drag-and-drop agent builder (explicitly excluded by MVP).
- Real-time push (polling is fine); mobile layouts (desktop-first, reasonable at laptop widths); i18n; dark mode.

## Gates & checks
- **G6.1 Journey click-through:** the full MVP definition-of-done (steps 1–10) performed entirely through the UI by a human, no API tools — recorded as the demo dry-run.
- **G6.2 Role gating:** logging in as operator@demo hides/blocks admin and approver screens (and the server rejects direct URL access); repeat per role.
- **G6.3 Evidence fidelity:** citations shown on run detail exactly match the run's stored output (spot-check three runs).
- **G6.4 Edit path UI:** editing a proposal in the inbox round-trips validated values and the audit view shows both original and edited.
- **G6.5 Empty/error states:** fresh org with no data renders sensible empty states on every screen; a killed backend renders error states, not crashes.

## Definition of done
- All ten screens exist, wired to real endpoints, role-gated, with loading/empty/error states.
- G6.1 dry-run completes cleanly — this IS the MVP demo, minus deployment.
- G6.2–G6.5 pass.

## Risks
- Frontend scope creep (the prettiest rabbit hole). Mitigation: the ten screens are a closed list; anything else is post-MVP.
- Chart library bloat. Mitigation: one lightweight chart lib, max two chart types.

## Task plan
*(Filled after spec approval — review gate.)*
