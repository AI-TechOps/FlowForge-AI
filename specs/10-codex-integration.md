# Spec: Codex Integration — Lanes, Gates & Handoff Protocol

**Status:** Approved (2026-07-12, FlowForge Code Owners)
**Owner:** FlowForge Code Owners
**Depends on:** 00-mvp-definition.md, DECISIONS.md D6 (Codex is development-time only)
**Feeds:** every phase spec's Gates & checks section

## Why this spec exists

D6 already decides *that* Codex is a development-time tool and never a runtime component. This spec decides *how* it works day to day: which tasks are Codex's, at which point in each phase it acts, what artifacts it produces, and how work hands off between Claude Code and Codex with zero ambiguity. The rule of thumb: **Claude builds the system; Codex tries to break it and populates its world.**

## Standing context

On approval of this spec, create **`AGENTS.md`** at the repo root — Codex's equivalent of CLAUDE.md. It contains: the project summary, Codex's lanes and hard boundaries (below), the handoff protocol, and pointers to the phase specs. Codex sessions read AGENTS.md first, the same way Claude Code sessions read CLAUDE.md. The two files must never contradict each other; on conflict, DECISIONS.md wins and both get fixed.

## Codex's lanes (exhaustive — if it's not listed, it's Claude's)

1. **Gate test suites (every phase).** After a phase's spec and task plan are approved, Codex writes the acceptance tests for that phase's "Gates & checks" section — reading only the spec, *not* Claude's implementation (cold tests catch spec misreadings that implementation-aware tests inherit). Output: `tests/phaseN/`.
2. **Fixtures & seed data.** The Meridian Dynamics corpus, eval tickets, taxonomy files, retrieval checks (per spec 09), and any later fixture data. Output: `fixtures/`.
3. **Adversarial & edge-case tests.** Beyond the gates: property-based tests (chunking invariants, idempotency), failure-path probes (corrupt files, oversized uploads, killed workers), the Phase 4 authz matrix including segregation-of-duties cases, tenant-isolation cross-org probes. Output: `tests/adversarial/`.
4. **Independent diff review.** Before each phase PR merges, Codex reviews the full diff cold (different code model, no shared context with the implementation session) and files findings as PR comments or a review file. Advisory: findings route to the code owners, who decide.
5. **Dev tooling scripts.** Test harnesses and checkers that support the gates: the migration upgrade→downgrade→upgrade runner, the template-compliance checker (G9.1), seed loaders, smoke-test scripts. Output: `scripts/`.
6. **Docs cold-read QA (Phase 7).** A fresh Codex session given only the repo attempts the README quickstart and the G7.6 "explain the system" test — an independent version of the cold-reader gate.

## Hard boundaries (restating D6, now operational)

- Codex **never** writes or edits anything under `backend/app/` or `frontend/src/` — no runtime code, ever, including "small fixes" found while testing. It reports; Claude fixes.
- Codex artifacts live only in `tests/`, `fixtures/`, `scripts/`, and PR review comments. CI enforces the import direction (Phase 0 isolation guard): nothing in `app/` imports from Codex directories.
- Codex gets no production/model API keys and no network path into the running system.
- Codex is never a runtime sub-agent, never the eval judge, and never the Approver (D5).

## The handoff protocol (the phase loop, with Codex baked in)

Each phase runs this sequence — the same spec-driven loop, with Codex steps pinned to fixed points:

1. **Spec** written → code owners approve.
2. **Task plan** written; every task is tagged **[CC]** (Claude Code) or **[CX]** (Codex) — the tag in the plan *is* the assignment; nothing is implicitly anyone's → code owners approve.
3. **Codex: gate tests first.** Codex writes the phase's gate tests from the spec (lane 1) and any fixtures the phase needs (lane 2). Tests land red (or skipped) on a branch — they are the executable form of the definition of done.
4. **Claude: implement.** Claude Code works the [CC] tasks one atomic commit at a time until the gate tests pass. Claude may fix *tests* only when a test contradicts the spec — and that change is called out explicitly in the commit and PR for code-owner attention (the spec wins over both the test and the implementation).
5. **Codex: adversarial pass + diff review.** Lanes 3 and 4 on the phase branch. Findings → issues/PR comments.
6. **Claude: address findings** the code owners triage as real.
7. **Code owners: review & merge.** Phase gate closes.

Disagreement rule: if Claude and Codex disagree (a test Claude believes is wrong, a finding Codex insists on), neither resolves it by overriding the other — it escalates to the code owners with both positions stated. Tests are never edited merely to make them pass.

## Where each phase uses Codex (summary)

| Phase | Codex work |
|---|---|
| 0 | minimal: isolation-guard CI check fixture; migration up/down runner script |
| 1 | Meridian corpus + tickets + taxonomy (spec 09); G1.1–G1.4 gate tests; chunking property tests |
| 2 | G2.x gate tests from spec; structured-output fuzzing (malformed LLM responses); eval-ticket loader |
| 3 | approval-flow gate tests; idempotency/timeout/retry adversarial tests; durable-pause kill-and-resume test |
| 4 | authz matrix tests (G4.2/G4.3 incl. segregation of duties); tenant cross-org probes |
| 5 | eval harness gate tests; metrics-endpoint contract tests |
| 6 | screen-level API contract tests; dashboard-numbers-match-DB checks |
| 7 | docs cold-read QA (G7.6); deployed smoke-test script |

Each phase spec keeps its own Gates & checks as the source of truth; this table is a router, not a duplicate.

## Gates & checks (for this spec itself)

- **G10.1** `AGENTS.md` exists, agrees with CLAUDE.md and D6, and a fresh Codex session given only the repo correctly states its lanes and boundaries.
- **G10.2** CI isolation guard (Phase 0 DoD) is green and actually fails when a test import is planted in `app/` (guard-of-the-guard check, run once).
- **G10.3** Every approved task plan from Phase 1 on carries [CC]/[CX] tags on every task.

## Out of scope

- Any Codex runtime role (D5/D6 — locked).
- Automating the code-owner review away: Codex's review is a *third* opinion, additive to human review, never a replacement.
- Codex writing specs or task plans (Claude drafts, humans approve; Codex consumes).

## Task plan
*(Filled after spec approval — review gate.)*
