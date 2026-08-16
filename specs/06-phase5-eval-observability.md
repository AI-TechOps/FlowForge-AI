# Spec: Phase 5 — Evaluation & Observability

**Status:** Approved 2026-08-16 (decisions recorded as D19)
**Owner:** FlowForge Code Owners
**Depends on:** 05-phase4-auth-tenant.md (approved + built, merged as PR #10)
**Gate to exit:** Phase 5 definition of done demoed + spec review of Phase 6

## What this phase delivers

The differentiator. Every run is measurable: a formal evaluation harness scores the agent against the labeled seed set (rule-based + LLM-as-judge with a DIFFERENT model), and metrics endpoints expose everything the dashboard will show. This is what separates the project from demo-ware.

## Scope (in)

### 1. Data model (migration)
- `eval_results`: id, org_id, run_id, ticket_id, expected jsonb, actual jsonb, scores jsonb (per-field + overall), judge_model, eval_batch_id, created_at
- `eval_batches`: id, org_id, agent_version, started_at, finished_at, summary jsonb (aggregates)

### 2. Evaluation harness
- `POST /api/eval/run` (admin) — triages every `is_eval_seed` ticket as an eval batch, then scores.
- **Eval mode is a separate compiled graph** (D19 decision 2): `build_graph(eval_mode=True)` produces a graph in which the approval interrupt node does not exist, so an eval batch physically cannot pause. Runs execute through `propose`/grounding only — no interrupt, no approval record, no write execution — and the proposal is scored as-is. A boolean checked inside the approval node was rejected: the human-in-the-loop must not rest on a flag being false.
- **A batch executes as background jobs** (D19 decision 4). `POST /api/eval/run` returns a batch id immediately and the runs go through the existing arq path, so eval exercises the real execution machinery rather than a parallel one. Scoring happens as each run settles; the batch finalizes when all of them have.
- Read endpoints for consumers: `GET /api/eval/batches` (list) + `GET /api/eval/batches/{id}` (per-field accuracy, judge scores, hit@k, grounded-rate) — the Phase 6 Evaluation screen's data source.
- **Deterministic scoring (code, no LLM):** exact/enum match on **category, urgency, recommended_team** vs labels → per-field accuracy. `suggested_priority` is deliberately *not* scored (D19 decision 5): `fixtures/eval_tickets.json` carries no priority label, and inventing twenty would add an unreviewed answer key on top of one that is already unreviewed (G1.5).
- **LLM-as-judge (different model than triage — locked decision D5):** scores `recommended_resolution` quality and citation-support ("does the cited chunk actually support the claim?") on a 1–5 rubric. Judge prompt + rubric live in versioned files. The judge is **`qwen2.5:7b` against llama3.1:8b triage** (D19 decision 1) — a different family, so different weights and different blind spots; config validation refuses a judge equal to the triage model. Local, so a batch runs offline and free (D11); OpenAI stays available for final validation.
- **Retrieval success metric:** for each eval ticket, did retrieval surface the doc its label is grounded in (hit@k)?
- Batch summary: per-field accuracy, mean judge scores, grounded-rate, hit@k — stored on the batch, comparable across `agent_version`s.

### 3. Observability (formalizing what audit_log started)
- Metrics computed from runs/audit/approvals/eval tables, exposed at `GET /api/metrics/summary` (any authenticated role, with a time-window param). **Cost and evaluation accuracy are administrator-only** (D19 decision 6); every role sees run counts, latency, tokens, tool success, approval/edit/rejection rates, retrieval success and the pending-approval count. Spend and model accuracy are oversight figures and the personas doc gives oversight to the Administrator. The fields:
  total runs; successful; failed; waiting approvals; avg latency; avg tokens/run; tool success rate; approval rate; human edit rate; human rejection rate; evaluation accuracy (latest batch); retrieval success; estimated model cost.
  (This is exactly the MVP dashboard metric list — one endpoint feeds Phase 6.)
- `GET /api/runs` list with filters (status, date, ticket) for the run-history view.
- `GET /api/audit` (admin) — cross-run filterable audit list (run, actor, tool, date range) — the Phase 6 Audit log screen's data source. (Per-run audit already exists on `GET /api/runs/{id}`; this is the global view.)
- `GET /api/config/agent` (any authenticated role, read-only) — agent_version, active model/provider, allowed enums, prompt file version. Satisfies the MVP's "read-only configuration page" requirement.
- Cost estimation: per-model token pricing table **versioned in `app/llm/cost.py` with an as-of date** (D19 decision 7), Ollama = $0, recorded per call in audit and aggregated here. Config-file pricing was rejected because an unset table silently reports $0 — and the cost figure is the one most likely to be quoted in a demo, so it should be the one most visible in review. Figures are labelled estimates.
- Structured logging (JSON) with run_id correlation across API + worker.

### 4. Regression protocol
- `eval/baseline.md` (from Phase 2) grows into a small table: agent_version → batch summary. A prompt or model change without a fresh eval batch is a convention violation (checked at PR review).

## Scope (out)
- External observability SaaS (LangSmith etc.) — self-hosted-on-Postgres by design (D11).
- Grafana (optional stretch, not required — Phase 6 dashboard is the consumer).
- Online/user-feedback eval loops; A/B testing; alerting.

## Gates & checks
- **G5.1 Determinism:** deterministic scores are reproducible — same batch re-scored gives identical per-field accuracy.
- **G5.2 Judge sanity:** judge model ≠ triage model (asserted in config validation); judge outputs validate against rubric schema; a deliberately-wrong resolution scores lower than a correct one (canary pair test). **The canary is a real-model gate, opt-in like G2.4** (D19 decision 3) — it needs actual semantics, and the fake provider is deterministic and semantically blind. CI asserts what a fake honestly can: rubric-schema validation and the judge≠triage check. A "judge mode" in the fake provider was rejected as proof of wiring dressed up as proof of judgement.
- **G5.3 Metric truth:** each dashboard metric verified against a hand-computed value on a small known dataset (fixture with e.g. 5 runs → known approval rate).
- **G5.4 Full coverage:** an eval batch covers 100% of seed tickets and completes even if individual runs fail (failures counted, not crashing the batch). Eval mode never pauses for approval, so batch completion is well-defined.
- **G5.5 Version comparability:** two batches at different agent_versions appear in the regression table with identical metric keys, so any two versions are directly comparable side by side.

## Definition of done
- One command/endpoint produces a full eval batch with per-field accuracy, judge scores, hit@k, grounded-rate.
- `GET /api/metrics/summary` returns every MVP dashboard metric, verified per G5.3.
- Baseline table has ≥2 entries (Phase 2 baseline + current) demonstrating regression tracking.
- Gates G5.1–G5.5 pass with tests.

## Risks
- Judge model variance. Mitigation: temperature 0, rubric-anchored prompts, canary pair test in CI.
- Metric definitions drift from dashboard expectations. Mitigation: this spec's metric list is copied verbatim from the MVP spec; Phase 6 consumes this endpoint unchanged.

## Task plan

`[CC]` = Claude Code (implementation). `[CX]` = Codex (gate tests, adversarial probes, cold review — never a shipped component, per D6).

| # | Owner | Task | Proves |
|---|---|---|---|
| 1 | [CC] | Record D19; update this spec with the resolved decisions and this plan | — |
| 2 | [CX] | **Gate tests first:** G5.1–G5.5 in `tests/phase5/` | all |
| 3 | [CC] | Migration 0007: `eval_batches`, `eval_results`, with a working `downgrade()` | — |
| 4 | [CC] | Eval-mode graph: `build_graph(eval_mode=True)` with no interrupt node, plus a gate that a normal run still pauses | G5.4 |
| 5 | [CC] | Deterministic scorer — per-field accuracy, hit@k, grounded-rate, as pure functions | G5.1 |
| 6 | [CC] | Judge: versioned rubric + prompt files, Pydantic-validated output, judge provider, `judge != triage` config validation | G5.2 |
| 7 | [CC] | `POST /api/eval/run` + batch orchestration (arq jobs, score-on-settle, finalize) | G5.4 |
| 8 | [CC] | `GET /api/eval/batches` and `GET /api/eval/batches/{id}` | G5.5 |
| 9 | [CC] | `GET /api/metrics/summary` — every MVP dashboard metric, time-windowed, role-sliced | G5.3 |
| 10 | [CC] | `GET /api/audit` — admin, cross-run, filterable, paginated | — |
| 11 | [CC] | `GET /api/config/agent` — read-only agent configuration | — |
| 12 | [CC] | Cost table with as-of date + aggregation into metrics | G5.3 |
| 13 | [CC] | Structured JSON logging with `run_id` correlation across API and worker | — |
| 14 | [CC] | `eval/baseline.md` regression table, ≥2 comparable entries | G5.5 |
| 15 | [CC] | README / ARCHITECTURE / DECISIONS + CI wiring for the Phase 5 gates — **in this PR, before merge** | — |
| 16 | [CX] | Adversarial pass + cold diff review | — |

**Sequencing note:** task 2 needs the eval contract, which tasks 3 and 5 define. Unlike Phase 4 there is no red window — Phase 5 adds endpoints rather than changing existing ones, so earlier suites are untouched throughout.

**Dependency:** G1.5 is now blocking rather than merely overdue. A recorded batch turns the unreviewed labels into a permanent baseline that later phases compare against.
