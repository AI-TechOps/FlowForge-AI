# Phase 2 adversarial pass + cold diff review

**From:** Codex (adversarial/review lanes)  
**Date:** 2026-08-09  
**Branch:** `feat/phase2-triage-agent`  
**Diff reviewed:** `main...feat/phase2-triage-agent` (23 commits, 46 files at review start)  
**Routing:** Advisory findings for FlowForge code owners under spec 10. No runtime code was changed.

## Oracle and scope

I read `specs/03-phase2-triage-agent.md` before the implementation and treated
G2.1–G2.6 plus its reliability controls as the oracle. I cold-read the full
branch diff, audited the disclosed test edits commit-by-commit, ran the existing
Phase 2 suite against the Docker stack, and added focused probes under
`tests/adversarial/`.

Known-open G2.4 (no Ollama on this machine) and G2.5's human spot-check half are
not repeated as findings.

## Result summary

Existing Phase 2 gates against the live fake-provider stack:

```text
10 passed, 2 skipped
```

The two skips were exactly the known-open G2.4 real-model gate and G2.5 human
spot-check. The other G2.1–G2.3, G2.5 automated, and G2.6 checks passed.

New Phase 2 adversarial probes:

```text
8 failed, 5 passed
```

The five passing probes confirm:

- fake-completion directives are interpreted only by `FakeProvider` and fake is
  refused in `APP_ENV=prod`;
- cross-org run detail remains hidden both before and after terminal status;
- `_fail` re-applies retrieved evidence after rollback;
- a forged, non-retrieved chunk id cannot satisfy grounding.

Collection is clean across `tests/phase1 tests/phase2 tests/adversarial` (42
tests), and the new files pass ruff check, ruff format check, and `git diff
--check`.

---

## Finding 1 — HIGH: the OpenAI strict structured-output schema is rejected before inference

`backend/app/llm/provider.py:148-155` sends `TriageResult.model_json_schema()`
with `strict: true`. But defaults in `backend/app/agents/schema.py:27-28` and
`:44-45` omit `page`, `section`, `requires_approval`, and `citations` from their
objects' `required` arrays.

OpenAI's strict Structured Outputs subset requires every object property to be
listed as required; nullable values should remain required while accepting
`null`. The current root schema requires 7 of 9 properties, and the nested
`Citation` schema requires 3 of 5. OpenAI will reject the request rather than
return a completion. This breaks the spec's OpenAI validation path and cannot be
exercised without a production/model key.

Official constraint: [OpenAI Structured Outputs — all fields must be required](https://developers.openai.com/api/docs/guides/structured-outputs#all-fields-must-be-required).

Failing probe:
`test_openai_strict_schema_marks_every_object_property_required`.

## Finding 2 — HIGH: ticket-supplied credentials are returned verbatim in audit rows

The live black-box probe put a PostgreSQL connection string and bearer token in
a ticket description. The same secret marker came back in two audit rows:

- `get_ticket.result.description`; and
- `search_company_knowledge.payload.query`.

`backend/app/agents/audit.py:20-41` only redacts values whose *key* contains a
small hint list. It does not inspect string values, and even direct
`database_url` and `connection_string` keys are absent from the hint list. This
violates the spec's explicit rule that audit payloads never contain API keys,
tokens, or connection strings.

Failing probes:

- `test_phase2_audit_never_repeats_a_credential_from_ticket_text` (live);
- `test_audit_scrubber_redacts_database_url_and_connection_string_keys`.

## Finding 3 — HIGH: the required LLM transport retry/backoff is absent

`backend/app/agents/graph.py:76-107` retries only after a completion is returned
and fails schema parsing. An exception from `complete_structured()` exits the
loop immediately; `runner.execute_run` catches it and terminally fails the run
as `internal_error`, so arq also sees a successful job return and does not retry
it.

The Phase 2 reliability contract separately requires LLM-call retries with
backoff (max 2). A provider that disconnects once and would succeed on the next
call is currently invoked only once.

Failing probe: `test_transient_llm_transport_failure_retries_then_succeeds`.

## Finding 4 — HIGH: G2.5 omits rejected and cancelled calls from the audit trail

Two failure paths bypass the promised "every tool call and LLM call" trail:

1. `Tool.invoke` validates arguments and runs the permission check at
   `backend/app/agents/tools.py:54-58`, before entering the audit context at
   `:60`. A validation or authorization rejection produces no audit row.
2. `audit.timed` catches `Exception` at `backend/app/agents/audit.py:100-112`.
   `asyncio.CancelledError` is a `BaseException`, so the per-run
   `asyncio.wait_for` timeout can cancel an in-flight LLM/tool call without
   recording it. The run itself becomes typed `timeout`, but its trace is
   incomplete.

Failing probes:

- `test_invalid_tool_arguments_still_create_an_audit_record`;
- `test_cancelled_call_is_audited_before_cancellation_propagates`.

## Finding 5 — MEDIUM: grounding accepts fabricated citation locators

`backend/app/agents/validate.py:73-80` defines a valid citation solely as a
matching `chunk_id`. The model-supplied `document_title`, `page`, and `section`
are neither compared with the retrieved evidence nor replaced from that trusted
evidence.

A result citing a real retrieved chunk id but claiming an invented document,
page 999, and a fabricated section therefore passes `is_grounded`, reaches
`completed`, and exposes a misleading citation. A wholly forged chunk id is
correctly rejected; the gap is the untrusted locator metadata attached to a
real id.

Failing probe:
`test_citation_with_matching_chunk_but_fabricated_locator_is_not_grounded`.

## Finding 6 — MEDIUM: oversized retrieval `k` is rejected, not clamped

The spec says `search_company_knowledge(query, k)` clamps `k` server-side to at
most 20 regardless of what the model requests. `SearchArgs.k` instead uses
`Field(..., le=MAX_K)` at `backend/app/agents/tools.py:82-85`, which raises a
validation error for 21+ rather than executing with 20.

The deterministic Phase 2 graph always supplies 5, so the happy gate does not
reach this contract edge; the reusable tool interface does.

Failing probe: `test_search_tool_clamps_oversized_k_to_the_server_limit`.

## Finding 7 — MEDIUM: enqueue failure leaves a permanently queued run

`backend/app/api/runs.py:42-52` commits and refreshes the queued run before it
calls Redis. If `enqueue_run` fails, the endpoint returns 500 but the durable row
remains `queued`, with no job and no reconciliation path. It will never reach a
terminal status after Redis recovers.

This is the queue-side counterpart to the spec's terminal-status reliability
promise. Either the enqueue and durable state need compensating failure
handling, or a sweeper/reconciler must recover orphaned queued runs.

---

## Disclosed test-edit adjudication

### `conftest.py::assert_failure_reason` — accepted

The reorder is correct. `dict.get("error", fallback)` never uses the fallback
when the `error` key exists, even when that field is merely prose (or `None`).
Reading `failure_reason` first makes the assertion target the typed contract.

### `test_eval_smoke_gate.py` fake-provider skip — policy accepted; detector escalated

I agree with not scoring the fake provider as model quality. D16 gives the fake
provider deterministic plumbing/fail-closed duties, while G2.4 is a semantic
accuracy bar and the baseline file already labels fake accuracy meaningless.
This is not, by itself, a disguised green gate; G2.4 remains explicitly open.

I do not consider the current detector reliable. It checks `LLM_PROVIDER` in
the pytest process, not the provider used by the already-running stack. The
documented command passes `.env` only to Docker Compose, so pytest can see the
variable unset and skip even when the backend is Ollama/OpenAI. Conversely, a
mismatched test-process value can run the score against a fake backend. Code
owners should retain the real-provider condition but choose an explicit,
stack-verifiable opt-in rather than infer it from the pytest process.

Per the request, this is an escalation on the disclosed edit, not a duplicate
report of known-open G2.4.

### Tenant-test rename and package/relative-import commit — accepted

Git reports the Phase 2 rename at 100% similarity. The packaging commit adds
only `__init__.py` files and changes imports from bare `conftest` to relative
imports. No test body or assertion changed. Combined collection now succeeds.

---

## Requested runtime-change verdicts

- **Per-prompt fake directive:** confined as intended. Only `FakeProvider`
  exposes/interprets `_injected_mode`; Ollama/OpenAI adapters have no directive
  interpreter, and the factory refuses fake in prod.
- **`audit` → `audit_entries`:** consistent in the run-detail response and new
  adversarial contract check.
- **`runner._fail` evidence re-apply:** correct. A live `no_citations` run failed
  as `ungrounded` while retaining non-empty retrieved evidence and audit rows.

---

## Disposition (Claude Code, 2026-08-09 — code owners triaged)

All seven findings verified independently before acting; F1 and F3 were
re-confirmed by hand because their probes assert against code paths that need a
key or a container. Every finding is addressed.

| # | Finding | Disposition | Commit |
|---|---|---|---|
| 1 | OpenAI strict schema rejected | Fixed at the transport layer | `33c2aaf` |
| 2 | Credentials in audit payloads | **Scoped down** — key gap fixed, value scanning deferred | `d695788` |
| 3 | No LLM transport retry | Fixed, with backoff, every attempt audited | `e305404` |
| 4 | Rejected/cancelled calls unaudited | Fixed, both paths | `65a59cf` |
| 5 | Fabricated citation locators | **Remedy changed** — overwrite, not discard | `e561ed3` |
| 6 | Oversized `k` rejected | Fixed, clamps | `b3d8a70` |
| 7 | Enqueue failure strands a run | Fixed, 503 + terminal `failed` | `43e538f` |
| — | G2.4 detector escalation | **Upheld** — opt-in + audit-trail verification | `c79ccc2` |

Three of Codex's probes were retargeted rather than made to pass. Each carries
its reasoning in its own docstring, per the AGENTS.md rule that a test is never
edited merely to go green:

- **F1** asserted against `TriageResult.model_json_schema()`. Requiring every
  field on the domain model would force local models to emit `page` and
  `section` or fail validation, pushing runs to `schema_invalid` and working
  against G2.4. The strict rewrite lives in the OpenAI adapter; the probe now
  asserts what is actually sent.
- **F2**'s live probe is a strict `xfail`. Spec 03 §1 aims the no-secrets rule at
  provider credentials and explicitly defers content redaction to production
  hardening. Kept, not deleted, so it fails loudly the day value scanning lands.
- **F5** asserted the citation was dropped. Discarding fails an entire run when a
  model picks the right chunk but invents a page number — exactly what small
  local models do, and directly against G2.4's bar. Locators are now taken from
  the retrieved chunk, so fabricated provenance cannot survive while grounding
  is preserved.

Finding 2's severity is the one substantive disagreement: Codex rated it HIGH as
a spec violation, the code owners read spec 03 §1 as covering provider
credentials with content redaction explicitly out of MVP scope. The cheap half
was still worth fixing — a payload key named `database_url` matched no hint.

Verified after the fixes: Phase 1 9 passed, Phase 2 10 passed, adversarial 18
passed / 1 xfailed, and 53 passed across the whole suite. The adversarial probes
now run in CI's integration job.

