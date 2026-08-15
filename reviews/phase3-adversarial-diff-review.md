# Phase 3 adversarial pass + cold diff review

**From:** Codex (adversarial/review lanes)
**Date:** 2026-08-14
**Branch:** `feat/phase3-actions-approval`
**Diff reviewed:** `main...feat/phase3-actions-approval` (20 commits, 38 files)
**Routing:** Advisory findings for FlowForge code owners under spec 10. No runtime code was changed.

## Oracle and scope

I read `specs/04-phase3-actions-approval.md` and D17 before the implementation
diff and treated G3.1-G3.7, the write-tool contract, the one-bundle/one-run
decision, and D7 tenant isolation as the oracle. I then cold-read the full diff,
rebuilt the Docker stack at this branch, migrated it to `0004`, ran the Phase 3
gates, and added focused probes under `tests/adversarial/`.

## Result summary

Existing Phase 3 gates against the rebuilt fake-provider stack:

```text
8 passed
```

That includes the real backend restart in G3.1, reject/no-write, replay and
concurrent decision idempotency, schema rejection and valid edit, confirmation,
and persistent pre-write timeout behavior.

Full adversarial suite after this pass:

```text
18 passed, 1 skipped, 1 xfailed, 6 failed
```

The six new failures reproduce the findings below. Ruff passes across
`backend/app`, migrations, tests, and scripts; `git diff --check` is clean. The
Redis-outage probe restores Redis and the worker in a `finally` block; all stack
services were running afterward.

---

## Finding 1 — HIGH: an edited approval can retarget the entire bundle to an unrelated ticket

`backend/app/api/approvals.py:134-138` validates an edited payload only by
calling `_validate_edits`; `:186-210` accepts any registered write tool whose
arguments match its Pydantic schema. It never binds the edited actions to the
approval's original tool set or affected ticket.

The live probe copied a valid proposal, replaced every `ticket_id` with a second
same-tenant ticket that was never shown on the approval card, and submitted the
result as `edited`. The API returned 200, the run completed, and the unrelated
ticket received a new team, priority, and internal note. The source ticket was
not the resource authorized by the edited payload.

This breaks the approval-card contract: a human is editing values for the
displayed affected ticket, not authorizing an arbitrary same-tenant write
request. It also bypasses D17's rule that code derives the concrete action
bundle from the validated triage result.

Failing probe:
`test_edited_approval_cannot_retarget_the_bundle_to_another_ticket`.

## Finding 2 — HIGH: Redis failure after the one-shot CAS permanently strands a decided approval

`backend/app/api/approvals.py:144-159` commits the pending-to-decided
compare-and-swap. Audit and `enqueue_resume` happen afterward at `:165-181`.
If Redis is unavailable, the endpoint returns 500 after the irreversible
decision is already committed. A retry receives 409 because the approval is no
longer pending.

The live probe paused a run, stopped Redis, submitted a rejection, and restored
Redis plus the worker. The approval remained durably `rejected`, its audit row
existed, but the run stayed `awaiting_approval` after worker startup. Recovery
only scans `executing` runs (`backend/app/agents/runner.py:159-190`), so this
state has no repair path.

This is the Phase 3 analogue of the Phase 2 queued-run outage that was already
fixed: either the decision plus resume intent needs a durable outbox/reconciler,
or a decided approval left at `awaiting_approval` must be recovered.

Failing probe:
`test_decided_approval_is_recovered_after_resume_enqueue_outage`.

## Finding 3 — MEDIUM: the idempotency ledger cannot prevent an ambiguous external double-write

`backend/app/agents/write_tools.py:108-119` inserts the local ledger row before
dispatch, but does not commit a completed result until after the adapter returns
and confirmation succeeds (`:153-168`). A transport timeout at `:137-147`
therefore calls the adapter again inside the same execution. The adapter
interface at `backend/app/integrations/ticket_system.py:141-158` has no
idempotency key that a remote system could honor.

The isolated probe used an adapter that committed its external mutation and
then lost the response. The write tool retried and applied the external
mutation twice. The current database-backed mock injects faults before its
mutation, so G3.6 passes without exercising this ambiguity.

Real Jira/ServiceNow adapters are post-MVP, so this is rated medium rather than
high for the current phase. It does, however, contradict the documented claim
that adding a real adapter requires only a new adapter class and the ledger
provides at-most-once writes across retries. The stable digest needs to cross
the adapter boundary or the retry policy must explicitly distinguish
ambiguous outcomes.

Failing probe:
`test_ambiguous_transport_timeout_cannot_apply_an_external_write_twice`.

## Finding 4 — MEDIUM: write tools declare approval but enforce no permission check

All three tools set `requires_approval=True`, but their `permission_check`
remains `None`. `Tool.invoke` treats `requires_approval` as passive metadata;
only a non-null `permission_check` is executed. Consequently, any internal
caller with a `ToolContext` can invoke these write tools directly without
presenting a decided approval.

The graph's current control flow reaches them only after `interrupt()`, so I did
not find a public API bypass in this diff. The missing enforcement still fails
spec 04 section 3's explicit full write-tool contract and makes the core safety
property dependent on every future caller remembering the right graph path.

Failing probe:
`test_every_write_tool_has_an_enforced_permission_check`.

## Finding 5 — MEDIUM: ticket prose remains a fault-injection control in production

The Redis test hook correctly returns no fault in production at
`backend/app/integrations/ticket_system.py:121-124`. `_maybe_fail` then
unconditionally scans the user-controlled ticket description at `:188-205`.
`[[FLOWFORGE_TICKET_FAULT:timeout]]` therefore still raises in
`APP_ENV=prod`.

The README also advertises this ticket-text directive without a dev-only
qualification. With the MVP mock adapter active in production mode, ticket
text can force every approved write attempt to fail. Fault-injection syntax
should be inert outside explicitly permitted dev/CI environments, just like
the HTTP hooks and Phase 2 fake provider.

Failing probe:
`test_ticket_text_fault_directive_is_inert_in_production`.

## Finding 6 — LOW: the dev call-recorder endpoint leaks another tenant's write trace

`backend/app/api/test_hooks.py:38-49` resolves an organization but ignores it;
the Redis key contains only `run_id`. A request from another valid organization
received HTTP 200 with the owner run's ticket id, team, priority, internal note,
and confirmation reads.

The endpoint 404s in production, which limits severity, but D7's tenant
boundary should still hold in shared development and CI environments. Resolve
the run under the acting organization before reading the recorder, or include
`org_id` in the recorder key and lookup.

Failing probe:
`test_mock_adapter_call_recorder_does_not_cross_tenant_boundary`.

---

## Additional cold-review risk — one approval per run is not enforced atomically

D17 defines one bundled approval per run. `Approval.run_id` is indexed but not
unique (`backend/app/models/approval.py:41-46`), while
`_pause_for_approval` performs an unlocked read-then-insert. `execute_run` also
does not require the run to still be `queued` before starting. Concurrent or
redelivered initial jobs can therefore both observe no approval and insert two
rows; later `scalar_one_or_none()` in `resume_run` assumes that cannot happen.

I did not add a gate that prescribes a unique constraint because an equivalent
atomic run-state claim would also satisfy the contract. Code owners should
choose one enforcement point and add a concurrent initial-job test.

## Test-change and CI review

- The Phase 2 status changes are legitimate compatibility updates: Phase 2
  triage output is settled and scoreable at `awaiting_approval` once Phase 3
  adds the durable pause. They preserve all existing output/evidence/audit
  assertions and do not turn `failed` into success.
- The eval baseline now uses all attempted tickets as its denominator; this
  matches the Phase 2 gate and avoids survivor bias.
- The Phase 0 exact schema list correctly adds both approved Phase 3 tables.
- The Phase 3 CI step sets `PHASE3_MANAGE_BACKEND=1`, so G3.1 does not silently
  skip. `PHASE3_MANAGE_STACK` is currently unused by the gate harness.
- The general adversarial CI step sets only Phase 2 live variables. The new
  Phase 3 live probes will skip there unless code owners also provide
  `PHASE3_REQUIRE_LIVE`, `PHASE3_DATABASE_URL`, and `PHASE3_BASE_URL`. The
  Redis-outage probe additionally needs `PHASE3_MANAGE_STACK=1` and must remain
  restricted to an isolated stack.

## Positive checks

- G3.1-G3.7 all pass on the rebuilt branch stack.
- Approval list/detail/decision product endpoints scope approval ids to the
  acting organization and validate `X-User-Id` against that same organization.
- Reject takes a structural graph edge that bypasses execute, and the live gate
  recorded zero adapter writes.
- Persistent pre-write injected timeouts retry twice, end in typed `failed`,
  preserve the approval, and roll back the mock ticket and ledger rows.
- Confirmation entries and durable idempotency rows are present for successful
  happy-path writes.
