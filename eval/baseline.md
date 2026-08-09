# Triage eval baseline

Regression table for G2.4 (Phase 2 smoke bar: **category accuracy ≥ 70%** over
the 20 labeled seed tickets) and, from Phase 5, the formal eval batches.

Reproduce:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d
docker compose --env-file .env -f infra/docker-compose.yml exec -T backend alembic upgrade head
python scripts/seed.py && python scripts/load_eval_tickets.py
python scripts/eval_baseline.py           # add --limit N to sample
```

A prompt or model change without a fresh row here is a convention violation
(checked at PR review) — `AGENT_VERSION` in `backend/app/agents/prompts.py`
bumps whenever prompt text changes.

## Results

| Date | agent_version | Provider / model | Runs | Category | Urgency | Team | G2.4 |
|---|---|---|---|---|---|---|---|
| 2026-07-29 | triage-v1 | `fake` (harness check, 5 tickets) | 5 | 0.0% | 20.0% | 0.0% | n/a |
| 2026-08-09 | triage-v1 | `ollama` / `llama3.1:8b` | 20 | **55.0%** (11/20) | not scored | not scored | **FAIL** (<70%) |

### Why the first row is not a baseline

The `fake` provider classifies by hashing token content, not by meaning (D16
decision 3). It exists to prove plumbing — schema validation, the grounding
rule, audit completeness — offline and deterministically in CI. Its accuracy is
noise by construction, and the ~0% above is the expected result, not a
regression. **Never quote a fake-provider number as model quality.**

Reproduce the real-model row:

```bash
brew install ollama && ollama serve
ollama pull llama3.1:8b && ollama pull nomic-embed-text

# .env's OLLAMA_BASE_URL is localhost, which points a *container* at itself.
LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  TRIAGE_MODEL=llama3.1:8b EMBEDDING_MODEL=nomic-embed-text \
  docker compose --env-file .env -f infra/docker-compose.yml up -d --build backend worker

# The gate is opt-in and refuses to score a fake stack: it reads the model name
# off the probe run's audit rows and fails on `fake:*`.
PHASE2_RUN_EVAL=1 PHASE2_REQUIRE_LIVE=1 PHASE2_RUN_TIMEOUT_SECONDS=900 \
  PHASE2_DATABASE_URL=postgresql+asyncpg://flowforge:flowforge@localhost:5432/flowforge \
  pytest tests/phase2/test_eval_smoke_gate.py -v
```

Switching to a real provider also switches *embeddings*, so the gate re-ingests
the corpus under `nomic-embed-text`; chunks embedded by the fake provider are
not comparable and are tagged `fake:` in `chunks.embedding_model`.

### G2.4 status: MEASURED, NOT PASSED (55.0%, bar is 70%)

The failure is not classification quality. Of the 20 seed tickets:

- **11 correct**
- **2 genuinely mis-categorised** — EVAL-012 and EVAL-019, both labelled
  `general_inquiry`, predicted `hardware`
- **7 failed as `ungrounded`** — the model returned zero citations

Zero runs failed `schema_invalid`, and every ungrounded run had retrieved a
full 5 chunks, so retrieval and JSON validity are both fine. `llama3.1:8b`
intermittently emits `"citations": []`, which the schema permits and the
grammar therefore allows. Completed runs cite 1–4 chunks each, so this is
inconsistency, not inability.

**Ground the 7 and the ceiling is 18/20 = 90%.** Two candidate fixes, cheapest
first, both requiring a re-measure rather than assumption:

1. `minItems: 1` on `citations` in the schema sent to the provider, making the
   empty array grammatically unreachable. A fabricated `chunk_id` is still
   dropped by the grounding check, so this has to be measured.
2. Prompt tightening — the citation instruction currently sits in the system
   prompt. Per spec 03 this bumps `AGENT_VERSION` and invalidates this row.

Before tuning toward the labels: `fixtures/eval_tickets.json` still carries
`review_status: draft_pending_code_owner_review` (open item G1.5). The two
`general_inquiry` → `hardware` disagreements are exactly the kind that may be
label errors rather than model errors, and fitting a model to unreviewed labels
is how a baseline becomes meaningless.
