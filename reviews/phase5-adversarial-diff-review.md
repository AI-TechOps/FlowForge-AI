# Phase 5 adversarial pass + cold diff review

**From:** Codex (adversarial/review lanes)  
**Date:** 2026-08-16  
**Requested branch/head:** `feat/phase5-eval-observability` at `416a39e`  
**Head available after two fetches:** `6a0a319`  
**Diff reviewed:** `origin/main...HEAD` (20 commits, 41 files)  
**Routing:** Advisory findings for FlowForge code owners under D6. No runtime code was changed.

## Review disposition

Do not merge on the evidence available to this lane. The official Phase 5 suite
is green, but independent probes reproduce eight contract failures:

```text
Phase 5 gates:             60 passed, 2 skipped
Phase 5 adversarial:        0 passed, 8 failed
Ruff / git diff check:      passed
```

The two skips are the opt-in real-model canary allowed by D19 decision 3. They
are not findings. The requested commit `416a39e` does not exist in the fetched
local or remote object database; `HEAD` and
`origin/feat/phase5-eval-observability` both resolve to `6a0a319`. This review
therefore covers the requested 41-file PR diff as currently published, not an
unavailable commit.

Gate disposition against the actual contract:

| Gate | Disposition | Evidence |
|---|---|---|
| G5.1 | Pass in the official suite | Deterministic scorer tests are green. |
| G5.2 / D19.1 | Fail | Different tags from one model family bypass config validation. |
| G5.3 / D19.6 | Fail | Operators lose a shared token metric, and eval metrics ignore the requested window. |
| G5.4 / D19.2, D19.4 | Fail | Seeds are silently omitted, eval mutates ticket state, and run jobs publish before commit. |
| G5.5 | Fail | The checked-in regression table contains only `triage-v1`. |

## Finding 1 — HIGH: batch detail discloses another tenant's eval result

`backend/app/api/evaluation.py:141-155` scopes the `EvalBatch`, but its result
query filters only on `EvalResult.batch_id`. The schema permits a result owned
by organization B to reference a batch owned by organization A because the
foreign key and organization id are independent.

The probe inserted that inconsistent relationship and requested the A batch as
an A administrator. The HTTP 200 response included B's `seed_ref`, ticket id,
expected answer-key payload, and actual model output. This is a direct
cross-tenant read. Scope the result query by organization as well, and consider
a database constraint that makes the relationship tenant-consistent.

Failing probe:
`test_phase5_batch_detail_does_not_follow_a_cross_tenant_result`.

## Finding 2 — HIGH: eval run jobs are published before their rows commit

`backend/app/api/evaluation.py:72-92` flushes each new `Run`, publishes its arq
job, and commits only after every publication. A separate worker connection
cannot see an uncommitted row. An immediate pickup therefore treats a valid
job as missing; arq's deterministic job id can then make recovery/redelivery
ambiguous while the first result remains retained.

The deterministic probe replaced only the publisher with a visibility check
from a second database connection. At publication time the run did not exist
for that connection. Persist the batch and all runs before publishing their
jobs, or use an atomic outbox/after-commit mechanism.

Failing probe:
`test_phase5_run_jobs_are_not_published_before_their_rows_commit`.

## Finding 3 — HIGH: G5.4 silently excludes unlabelled eval seeds

The endpoint promises to triage every `is_eval_seed` ticket. Instead,
`backend/app/api/evaluation.py:54-76` creates `scoreable` by discarding every
seed whose `external_ref` is absent from the answer key, then reports that
filtered length as `total_tickets`.

With one labelled and one unlabelled seed, `POST /api/eval/run` returned 202 and
`total_tickets: 1`. It neither covered the second seed nor surfaced a data
contract failure. That lets G5.4 appear to be 100% over a hidden subset. The
endpoint should reject the inconsistent corpus before creating work, or record
and count the missing-label ticket as a failed result.

Failing probe:
`test_phase5_eval_endpoint_does_not_silently_drop_unlabelled_seed_tickets`.

## Finding 4 — HIGH: eval finalization writes to the source ticket

D19 decision 2 says eval runs execute proposal/grounding only, with no approval
and no write execution. The separate graph removes the explicit execute node,
but the shared finalizer at `backend/app/agents/runner.py:495-504` still changes
a `new` source ticket to `triaged` for every completed run, including one with
an `eval_batch_id`.

The probe finalized an eval run and observed its seed ticket change from `new`
to `triaged`. Evaluation is therefore not read-only with respect to its source
ticket. The no-write property needs to cover shared lifecycle code as well as
graph topology.

Failing probe: `test_phase5_eval_run_does_not_change_the_source_ticket`.

## Finding 5 — MEDIUM: same-family judge configurations bypass D19.1

D19 decision 1 rejects a different prompt or tag on the same model family. The
validator at `backend/app/config.py:82-97` compares only the complete stripped
strings, so `llama3.1:8b` triage plus `llama3.1:70b` judge is accepted. Those
models share the family and blind spots D19 explicitly requires the judge to
avoid.

The official G5.2 gate checks exact equality and happens to confirm that the
defaults have different prefixes, but it never attacks a same-family,
different-tag override.

Failing probe: `test_phase5_same_model_family_cannot_judge_itself`.

## Finding 6 — MEDIUM: operator token metrics contradict the role contract

Spec 06 says only cost and evaluation accuracy are administrator-only and
explicitly lists tokens among the metrics every authenticated role sees.
`backend/app/api/observability.py:36-39,155-160` also removes
`avg_tokens_per_run` for non-administrators.

The probe created one completed run with 30 audited tokens. Its operator saw
HTTP 200 but no `avg_tokens_per_run`; the expected value is 30.0. The official
gate encodes the same defect at `tests/phase5/test_metric_truth_gate.py:54-57`
by including the token metric in `ADMIN_ONLY_KEYS`. That assertion disagrees
with the spec and D19.6 and should be corrected, not used to ratify the runtime
behavior.

Failing probe: `test_phase5_operator_still_sees_average_tokens_per_run`.

## Finding 7 — MEDIUM: eval-derived metrics ignore `window_days`

The metrics endpoint computes `since` and applies it to runs, audit rows, and
approvals, but the latest-batch query at
`backend/app/api/observability.py:123-130` has no time predicate. A completed
batch from 200 days ago therefore supplies current `evaluation_accuracy`,
`retrieval_success`, `grounded_rate`, and `latest_eval_batch_id` to a 30-day
request.

The API advertises one time-window parameter for the summary, not a partly
windowed response. Either apply the window to `EvalBatch.created_at` or make
the different semantics explicit in the contract and response.

Failing probe: `test_phase5_metrics_window_excludes_an_old_eval_batch`.

## Finding 8 — MEDIUM: the checked-in G5.5 table has no version comparison

G5.5 requires two batches at different `agent_version`s. The Phase 5 regression
table in `eval/baseline.md:18-23` contains four rows, but every row is
`triage-v1`; three real-model rows are exact duplicates at that version. They
measure repeatability, not version comparability.

The official API gate inserts two synthetic batches with different versions,
which proves the endpoint can display such data. Its checked-in-table assertion
checks only row count and column shape, so task 14's actual artifact can remain
non-compliant while the gate passes. Record a genuine second-version batch;
do not relabel a duplicate run merely to satisfy the test.

Failing probe: `test_phase5_regression_table_contains_distinct_agent_versions`.

## Blocking code-owner action — G1.5 answer key review

G1.5 remains open and belongs to the code owners. The three governed fixtures
still declare `review_status: draft_pending_code_owner_review`; Codex has not
approved or changed their labels.

This batch strengthens the case for review rather than resolving it:

- EVAL-012 and EVAL-019 were classified `hardware` by three independent Phase
  5 runs after the same disagreement appeared in Phase 2.
- The `IT Security` team label on account-access tickets lost repeatedly.
- The formal baseline is now being recorded against those unsigned labels, so
  later version comparisons would inherit any answer-key error.

Code owners should review the full answer key, starting with those repeated
disagreements, record the rationale for any label changes, and update all three
review-status fields only after approval. Until then, the reported accuracy is
useful diagnostic evidence but not an approved regression baseline.

## Positive cold-review checks

- The eval graph is separately compiled without approval or execute nodes.
- The real-model judge canary remains opt-in and does not pretend the fake
  provider has semantic judgement.
- Deterministic scoring covers category, urgency, and recommended team, matching
  the labels D19.5 says actually exist.
- Pricing is versioned in code with an as-of date and zero local-model cost.
- Batch and list endpoints require administrator access, and the primary batch
  lookup itself is tenant-scoped.

The new probes live in
`tests/adversarial/test_phase5_eval_observability_boundaries.py`. The only
supporting test edit exports the existing Phase 5 live fixtures through
`tests/adversarial/conftest.py`.
