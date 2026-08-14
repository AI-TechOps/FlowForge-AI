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
| 2026-08-09 | triage-v1 | `ollama` / `llama3.1:8b` | 20 | 55.0% (11/20) | not scored | not scored | **FAIL** (<70%) |
| 2026-08-09 | triage-v1 + citation repair | `ollama` / `llama3.1:8b` | 20 | **75.0%** (15/20) | not scored | not scored | **PASS** |

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

### G2.4 status: PASSED at 75.0% (bar is 70%)

Both 2026-08-09 rows are kept: the delta between them is the evidence for the
fix, and deleting the failing row would erase the only proof that the gate can
fail.

**The first run failed at 55%, and not on classification quality:**

- 11 correct
- 2 genuinely mis-categorised — EVAL-012 and EVAL-019, both labelled
  `general_inquiry`, predicted `hardware`
- **7 failed as `ungrounded`** — the model returned zero citations

No run failed `schema_invalid`, and every ungrounded run had retrieved a full 5
chunks, so retrieval and JSON validity were both sound. `llama3.1:8b` simply
emitted `"citations": []` intermittently — the cheapest legal completion — while
its successful runs cited 1–4 chunks each. Inconsistency, not inability.

**The fix was a citation repair retry** (`backend/app/agents/graph.py`): an
answer that is schema-valid but uncited spends the repair attempt the loop
already budgets, asking the model to copy an exact `chunk_id`. It only fires
when evidence exists, so an empty knowledge base still fails fast as
`ungrounded` (G2.2), and the happy path is still one LLM call, so G2.5's audit
count is unchanged.

| | first run | with citation repair |
|---|---|---|
| Category accuracy | 55.0% (11/20) | **75.0% (15/20)** |
| `ungrounded` | 7 | 1 |
| Completed | 12 | 19 |

The repair fired on 5 of 20 runs; the other 15 cited correctly first time.

**What did not work:** `minItems: 1` on `citations` in the schema sent to the
model. Ollama's grammar compiler accepts it and silently ignores it — measured,
0 citations returned anyway — and OpenAI's strict subset rejects `minItems` on
arrays outright, so it would also have broken the OpenAI path. Recorded so it
is not retried.

### Scoring basis (aligned in Phase 3)

Both the gate and `scripts/eval_baseline.py` now divide by **every ticket
attempted**, not by completed runs. A run that fails `ungrounded` is a failure
to triage, not a sample to drop — scoring only completed runs would let an
agent that fails half its tickets report a flattering number, and would hide a
regression that shows up as more failures rather than more wrong answers.

Both also count a run resting at `awaiting_approval` as scoreable: from Phase 3
a successful triage pauses there for a human with its output final. Without
that, every eval after Phase 3 would have reported 0%.

### Reading this number honestly

- **75% is a one-ticket margin.** Each of 20 tickets is worth 5 points, so this
  clears a smoke bar; it is not a claim that the agent is 75% accurate. Phase 5's
  formal eval is the number that should carry weight.
- **The answer key is unreviewed.** `fixtures/eval_tickets.json` still carries
  `review_status: draft_pending_code_owner_review` (open item G1.5). No labels
  were changed and no ticket was tuned against, so the improvement is real
  rather than fitted — but the absolute figure is only as trustworthy as labels
  nobody has signed off. EVAL-012 and EVAL-019 remain worth a human look.
- **Urgency and team are unscored** by this gate; `scripts/eval_baseline.py`
  covers those.
