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
| _pending_ | triage-v1 | `ollama` / `llama3.1:8b` | 20 | — | — | — | **not yet run** |

### Why the first row is not a baseline

The `fake` provider classifies by hashing token content, not by meaning (D16
decision 3). It exists to prove plumbing — schema validation, the grounding
rule, audit completeness — offline and deterministically in CI. Its accuracy is
noise by construction, and the ~0% above is the expected result, not a
regression. **Never quote a fake-provider number as model quality.**

### G2.4 status: OPEN

The real-model row is unfilled because no Ollama runtime is installed on the
build machine. Everything G2.4 needs is in place — seed set loaded, harness
written and exercised end-to-end, scoring verified against the answer key — so
closing it is one command once a model is available:

```bash
brew install ollama && ollama serve
ollama pull llama3.1:8b
LLM_PROVIDER=ollama docker compose --env-file .env -f infra/docker-compose.yml up -d worker backend
python scripts/eval_baseline.py
```

Then add the row above and re-run. If accuracy lands under 70%, the spec's
mitigation applies: tighten the prompt (bumping `AGENT_VERSION`) or try a
stronger local model before treating the bar as wrong.
