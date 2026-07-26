# Phase 1 gate run — findings for Codex

**From:** Claude Code (implementation lane)
**Date:** 2026-07-26
**Branch:** `feat/phase1-rag`
**Routing:** Per spec 10 handoff protocol — these are Codex-owned deliverables (lanes 2 & 3). Reported, not fixed. Code owners triage.

## What was run

Full Phase 1 gate suite against a live stack (`infra/docker-compose.yml`: db+pgvector, redis, backend, worker), fake embedding provider (`LLM_PROVIDER=fake`, `APP_ENV=dev`), migrations at head `0002`, health green.

```
pytest tests/phase1 tests/adversarial
env: PHASE1_REQUIRE_LIVE=1 PHASE1_MANAGE_WORKER=1
     PHASE1_DATABASE_URL=postgresql+asyncpg://flowforge:flowforge@localhost:5432/flowforge
     PHASE1_COMPOSE_FILE=<repo>/infra/docker-compose.yml
     LLM_PROVIDER=fake APP_ENV=dev   # exported into the pytest process, see note 3
```

## Result summary

**Implementation is correct — every gate that exercises `backend/app` passes:**

- G1.3 tenant isolation (run in isolation): PASS — no cross-org leakage, chunk ids disjoint across orgs.
- G1.4 unsupported type -> 415: PASS
- G1.4 oversized -> 413: PASS
- G1.4 corrupt file -> `failed` + human-readable `error_message` within 60s: PASS (`cannot read PDF: startxref not found`)
- G1.4 killed worker -> stranded `processing` -> `reingest` recovers -> `ready`: PASS
- adversarial (7 Phase 0 failure-path tests): PASS

No implementation defect surfaced. The items below are all Codex-lane deliverables.

---

## Finding 1 — Fixtures corpus missing (lane 2, task 9). Blocks G1.1 and G1.2.

`fixtures/` is empty. The gate tests Codex delivered (task 10) are present, but the fixtures they consume are not. G1.1 and G1.2 cannot run.

**Required (from `tests/phase1/conftest.py::locate_corpus_paths` + `ingested_corpus`):**

`fixtures/enterprise/` — 10 Meridian Dynamics docs, each filename stem containing its doc id (case-insensitive), exact extensions:

| Doc id | Ext | Title used at upload (conftest) |
|---|---|---|
| MD-IT-001 | `.pdf` | VPN Access Policy |
| MD-IT-002 | `.pdf` | Incident Priority & Escalation Guidelines |
| MD-IT-003 | `.md`  | Password Reset & Account Lockout Procedure |
| MD-IT-004 | `.md`  | MFA Enrollment & Recovery |
| MD-IT-005 | `.md`  | Hardware Request & Replacement Policy |
| MD-IT-006 | `.md`  | Software & SaaS License Request Procedure |
| MD-IT-007 | `.md`  | Email & Collaboration Troubleshooting Guide |
| MD-IT-008 | `.pdf` | Security Incident Reporting Policy |
| MD-IT-009 | `.txt` | Onboarding & Offboarding IT Checklist |
| MD-IT-010 | `.md`  | Remote Work IT Standards |

Exactly one file per id/ext (the finder asserts `found == 1`). PDFs must have a real text layer (OCR is out of scope). PDFs/MD must carry page/section metadata for G1.1's metadata-preservation check.

`fixtures/retrieval_checks.json` — exactly 5 checks (from `test_retrieval_gate.py`):
```json
{
  "checks": [
    { "query": "how do I connect to the VPN from home", "expected_doc_ids": ["MD-IT-001"] }
  ]
}
```
- List, or `{"checks": [...]}`. Exactly 5 entries.
- Each: non-empty `query` (str) + `expected_doc_id` (str) or `expected_doc_ids` (list); every id must start with `MD-IT-`.
- G1.2 asserts the expected doc appears in **top-3** for its query and that results are ranked by descending score. Because the corpus is uploaded with titles `"{doc_id} — {title}"`, the match is `expected_id.lower() in document_title.lower()` — pick queries that genuinely distinguish their target doc.

`fixtures/eval_tickets.json` — 20 labeled eval tickets + 5 demo tickets (spec 09). Not consumed by G1.1–G1.4 (the DB loader lands in Phase 2), but it is a task-9 deliverable and gates G1.5 (human review).

These are all human-review-gated (spec 09 G9.1–G9.4, G1.5). I deliberately did **not** generate them — fabricating the corpus would bypass that review.

---

## Finding 2 — Test-isolation defect in `tests/phase1` (lane 3). Makes G1.3 fail under full-suite ordering.

**Symptom:** `test_g1_3_retrieval_never_crosses_organization_boundaries` PASSES in isolation but FAILS in the full run at:
```
assert any(marker_a in title for title in titles_a)  # "org A must still retrieve its own probe document"
```
The cross-org leakage assertions (no B in A, disjoint chunk ids) still pass — this is a liveness/self-retrieval failure, not an isolation breach.

**Root cause:** `org_a_id` is a single session-scoped id shared by every Phase 1 test (`conftest.py`, `@pytest.fixture(scope="session")`). The destructive `test_g1_4_killed_worker_document_is_recoverable_via_reingest` (alphabetically first) uploads a ~4.5 MB filler `.txt` into that shared org, producing ~1556 chunks. G1.3 then queries that same org with `k=20`; its single-chunk probe is statistically crowded out of the top-20 by 1500+ unrelated chunks under the fake provider's near-uniform similarities.

**Evidence (DB after the run):** one org id holds *both* `Worker Recovery Probe … (1556 chunks)` and `Tenant A Probe … (1 chunk)`.

**This is not a product bug** — retrieval correctly returns that org's own top-k; the test just seeded the org with bulk noise before asserting a needle is present.

**Fix is Codex's call** (I did not edit the tests — spec 10: "tests are never edited merely to make them pass"). Options that would resolve it, for consideration:
- Give the destructive killed-worker test its own throwaway org id (not the shared session `org_a_id`), so its bulk data never pollutes other gates; or
- Scope tenant-probe org ids per-test instead of per-session; or
- Have G1.3 assert on `k` >= (chunks in org) or query by the probe's own marker so the needle is guaranteed retrievable regardless of co-tenant volume.

---

## Note 3 — Harness gotcha (not a defect, but the gate needs it documented)

`test_g1_4_killed_worker_…` restarts the worker via `docker compose up -d worker` in a subprocess that inherits the **pytest process** environment. If `LLM_PROVIDER` is not exported there, compose re-interpolates `${LLM_PROVIDER:-ollama}` and brings the worker back pointed at a non-existent Ollama; ingestion then fails on connect (`All connection attempts failed`) and the doc lands `failed` instead of the stranded `processing` the test expects. Running the gate requires `LLM_PROVIDER=fake` (and `APP_ENV=dev`) exported into the pytest environment, or an equivalent `infra/.env` / `--env-file` the compose invocations pick up. Worth a line in the gate runbook (the README already flags a related `compose --env-file` pitfall).
