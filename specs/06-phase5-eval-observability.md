# Spec: Phase 5 — Evaluation & Observability

**Status:** Draft — awaiting review
**Owner:** FlowForge Code Owners
**Depends on:** 05-phase4-auth-tenant.md (approved + built)
**Gate to exit:** Phase 5 definition of done demoed + spec review of Phase 6

## What this phase delivers

The differentiator. Every run is measurable: a formal evaluation harness scores the agent against the labeled seed set (rule-based + LLM-as-judge with a DIFFERENT model), and metrics endpoints expose everything the dashboard will show. This is what separates the project from demo-ware.

## Scope (in)

### 1. Data model (migration)
- `eval_results`: id, org_id, run_id, ticket_id, expected jsonb, actual jsonb, scores jsonb (per-field + overall), judge_model, eval_batch_id, created_at
- `eval_batches`: id, org_id, agent_version, started_at, finished_at, summary jsonb (aggregates)

### 2. Evaluation harness
- `POST /api/eval/run` (admin) — triages every `is_eval_seed` ticket as an eval batch, then scores.
- **Eval mode:** eval-batch runs execute the graph through `propose`/grounding only — no interrupt, no approval record, no write execution. The proposal is scored as-is. (Without this, a 20-ticket batch would strand 20 runs in `awaiting_approval` waiting for a human.)
- Read endpoints for consumers: `GET /api/eval/batches` (list) + `GET /api/eval/batches/{id}` (per-field accuracy, judge scores, hit@k, grounded-rate) — the Phase 6 Evaluation screen's data source.
- **Deterministic scoring (code, no LLM):** exact/enum match on category, urgency, recommended_team, suggested_priority vs labels → per-field accuracy.
- **LLM-as-judge (different model than triage — locked decision D5):** scores `recommended_resolution` quality and citation-support ("does the cited chunk actually support the claim?") on a 1–5 rubric. Judge prompt + rubric live in versioned files.
- **Retrieval success metric:** for each eval ticket, did retrieval surface the doc its label is grounded in (hit@k)?
- Batch summary: per-field accuracy, mean judge scores, grounded-rate, hit@k — stored on the batch, comparable across `agent_version`s.

### 3. Observability (formalizing what audit_log started)
- Metrics computed from runs/audit/approvals/eval tables, exposed at `GET /api/metrics/summary` (any authenticated role; response sliced per the Phase 4 role matrix — admin sees everything including cost and eval accuracy, operator/approver see role-appropriate subsets, since the Dashboard is on every persona's screen list), with a time-window param:
  total runs; successful; failed; waiting approvals; avg latency; avg tokens/run; tool success rate; approval rate; human edit rate; human rejection rate; evaluation accuracy (latest batch); retrieval success; estimated model cost.
  (This is exactly the MVP dashboard metric list — one endpoint feeds Phase 6.)
- `GET /api/runs` list with filters (status, date, ticket) for the run-history view.
- `GET /api/audit` (admin) — cross-run filterable audit list (run, actor, tool, date range) — the Phase 6 Audit log screen's data source. (Per-run audit already exists on `GET /api/runs/{id}`; this is the global view.)
- `GET /api/config/agent` (any authenticated role, read-only) — agent_version, active model/provider, allowed enums, prompt file version. Satisfies the MVP's "read-only configuration page" requirement.
- Cost estimation: per-model token pricing table in config; Ollama = $0; recorded per call in audit, aggregated here.
- Structured logging (JSON) with run_id correlation across API + worker.

### 4. Regression protocol
- `eval/baseline.md` (from Phase 2) grows into a small table: agent_version → batch summary. A prompt or model change without a fresh eval batch is a convention violation (checked at PR review).

## Scope (out)
- External observability SaaS (LangSmith etc.) — self-hosted-on-Postgres by design (D11).
- Grafana (optional stretch, not required — Phase 6 dashboard is the consumer).
- Online/user-feedback eval loops; A/B testing; alerting.

## Gates & checks
- **G5.1 Determinism:** deterministic scores are reproducible — same batch re-scored gives identical per-field accuracy.
- **G5.2 Judge sanity:** judge model ≠ triage model (asserted in config validation); judge outputs validate against rubric schema; a deliberately-wrong resolution scores lower than a correct one (canary pair test).
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
*(Filled after spec approval — review gate.)*
