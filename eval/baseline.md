# Triage eval baseline

Two tables. **Phase 5 eval batches** below is the one that counts from now on:
a recorded batch with per-field accuracy, hit@k, grounded-rate and judge
scores, produced by `POST /api/eval/run` and stored in `eval_batches`. The
older Phase 2 table is kept underneath because deleting the row where the gate
failed would erase the only evidence the gate can fail.

A prompt or model change without a fresh row here is a convention violation
(checked at PR review) — `AGENT_VERSION` in `backend/app/agents/prompts.py`
bumps whenever prompt text changes.

## Phase 5 eval batches

Every row is one `eval_batches` record. Metric keys are identical across rows by
construction (G5.5), so any two versions can be read side by side.

| Date | agent_version | Models (triage → judge) | Tickets | Category | Urgency | Team | Overall | Grounded | hit@k | Judge resolution | Judge citation | Failed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-08-16 | triage-v1 | `fake` harness check (3 tickets) | 3 | 0.0% | 33.3% | 33.3% | 0.0% | 100% | 0.0% | 3.33 | 3.33 | 0 |
| 2026-08-16 | triage-v1 | `ollama` `llama3.1:8b` → `qwen2.5:7b` | 20 | 80.0% | 75.0% | 70.0% | 50.0% | 95.0% | 80.0% | 3.68 | 4.79 | 1 |
| 2026-08-16 | triage-v1 | `ollama` `llama3.1:8b` → `qwen2.5:7b` | 20 | 80.0% | 75.0% | 70.0% | 50.0% | 95.0% | 80.0% | 3.68 | 4.79 | 1 |
| 2026-08-16 | triage-v1 | `ollama` `llama3.1:8b` → `qwen2.5:7b` | 20 | 80.0% | 75.0% | 70.0% | 50.0% | 95.0% | 80.0% | 3.68 | 4.79 | 1 |

**Overall** is the share of tickets where *all three* labelled fields are right,
which is why it sits far below any single field. `suggested_priority` is not
scored: the fixture carries no priority label (D19 decision 5).

The fake row is a harness check and **must never be quoted as model quality** —
the fake provider classifies by hashing token content, not by meaning (D16
decision 3), so its accuracy is noise by construction. It is here because it
proves the batch machinery end to end, and because the contrast is the point.

### The three Ollama rows are identical, and that is the finding

Three independent batches, each with its own twenty runs: every per-field score,
every hit@k, every judge score and **every generated `recommended_resolution`
string** matched exactly (verified by SQL `EXCEPT` between batches — zero rows).
At temperature 0, with a fixed corpus and anchored rubrics, this pipeline is
reproducible run to run on this machine.

That is worth recording because it sets the noise floor: at a fixed
`agent_version`, the run-to-run delta here is **zero**, so any future movement
in these numbers is signal rather than variance. It is not a claim that the
models are deterministic in general — different hardware, a re-pulled model tag,
or a re-ingested corpus can all move it, and a row that changes without a code
change means one of those changed.

### G5.2 canary (real judge, 2026-08-16)

The judge must rank a deliberately-wrong resolution below a correct one, which
needs actual semantics — so the canary is opt-in and refuses a fake stack (D19
decision 3). Measured:

```
PHASE5_RUN_CANARY=1 LLM_PROVIDER=ollama TRIAGE_MODEL=llama3.1:8b JUDGE_MODEL=qwen2.5:7b \
  pytest tests/phase5/test_judge_sanity_gate.py -k canary -s
# canary: qwen2.5:7b scored correct=5 wrong=2 (citation support 5/3)
```

A resolution about replacing a door badge scored 2 against 5 for the documented
recovery steps, and its citation support 3 against 5 — the judge noticed that
the cited passage does not say what the answer claimed. **PASS.**

### What the agent got wrong (batch `3cc5a149`)

| Ticket | Miss |
|---|---|
| EVAL-011 | **Failed `ungrounded`** — returned no usable citation, so it scores zero on every field. The only failed run. |
| EVAL-012, EVAL-019 | `general_inquiry` → `hardware`. **The same two tickets missed identically in Phase 2**, across a different provider configuration. |
| EVAL-015 | `hardware` → `email_collaboration`; team follows the category into Business Applications. |
| EVAL-003, EVAL-004, EVAL-014 | Team `IT Security` → `Service Desk`. Three of the six team misses are this one pattern, all on account-access tickets. |
| EVAL-005, EVAL-017, EVAL-018 | Urgency off by one band in both directions. |
| EVAL-002, EVAL-018, EVAL-019 | hit@k miss: retrieval never surfaced the document the label is grounded in. |

**Two of these are label questions, not model questions**, and they are the same
ones G1.5 has been flagging: EVAL-012/EVAL-019 have now been categorised
`hardware` by three independent runs, and the `IT Security` team label on
account-access tickets loses three times in a row. An answer key nobody has
signed off is being used to grade an agent; where the agent disagrees
*consistently*, the label is at least as likely to be wrong as the model.
**G1.5 remains open and is the first thing to fix before these numbers carry
weight.**

### Reproducing a batch

```bash
# Real models. The judge must differ from the triage model or the stack refuses
# to start (D5); pull both.
ollama pull llama3.1:8b && ollama pull qwen2.5:7b && ollama pull nomic-embed-text

# .env's OLLAMA_BASE_URL is localhost, which points a *container* at itself.
LLM_PROVIDER=ollama OLLAMA_BASE_URL=http://host.docker.internal:11434 \
  TRIAGE_MODEL=llama3.1:8b JUDGE_MODEL=qwen2.5:7b EMBEDDING_MODEL=nomic-embed-text \
  docker compose --env-file .env -f infra/docker-compose.yml up -d --build backend worker
docker compose -f infra/docker-compose.yml exec -T backend alembic upgrade head

# Switching provider switches EMBEDDINGS too, so the corpus must be re-ingested:
# chunks embedded by the fake provider are a different vector space entirely.
python scripts/seed.py
python scripts/reset_corpus.py          # 10 MD-IT documents -> 56 chunks
python scripts/load_eval_tickets.py     # 20 labelled tickets, labels withheld

ADMIN="Authorization: Bearer $(python scripts/dev_token.py --email admin@demo)"
BATCH=$(curl -sX POST localhost:8000/api/eval/run -H "$ADMIN" | jq -r .id)
curl -s "localhost:8000/api/eval/batches/$BATCH" -H "$ADMIN" | jq .summary
```

About ten minutes for the runs (20 tickets, worker concurrency 4) plus a minute
of judging on an M-series laptop. The batch runs as background jobs and the
scorer re-checks until they settle, so the HTTP call returns immediately.

## Phase 2 results (superseded by the table above)

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
