# Spec: Cerebras Inference as an LLM Provider

**Status:** Draft — awaiting review
**Owner:** FlowForge Code Owners
**Depends on:** 06-phase5-eval-observability.md (approved + built), 10-codex-integration.md
**Feeds:** 08-phase7-ship.md (§1, the demo LLM choice)

## Why this spec exists

This is a cross-cutting capability, not a phase: it adds one hosted provider behind the existing factory (D11) and has two consumers, which are justified separately because they rest on different arguments.

**1. The eval judge — the requirement.** D19 decision 1 adopted a judge from a different family (`qwen2.5:7b` against `llama3.1:8b` triage) and kept it local to preserve D11. That closed the "genuinely different model" deferral; ARCHITECTURE.md dropped the row in `c086640` (2026-08-16), and DECISIONS.md open items record it as no longer deferred. This spec does **not** reopen that item. Its case is that the adopted judge is *weak*, not *missing*:

- A 7B model grading an 8B model is barely a step up. On the recorded batches its citation-support mean is 4.79/5 on a batch where one run failed `ungrounded`, and a judge that rarely marks down is a judge whose scores carry little information.
- The G5.2 canary has run once, on 2026-08-16, and passed (`qwen2.5:7b` scored correct = 5, wrong = 2; `eval/baseline.md`). Once on one judge is a data point, not a habit. A hosted judge makes re-running it cheap enough to do on every judge or prompt change.
- Wiring a hosted judge exposes a live defect in the D5 check that exists today, whatever this spec decides (decision 6, G11.4).

This amends D19 decision 1 rather than reversing it: the local judge stays the default, and a hosted one becomes a supported, opt-in configuration. The amendment is recorded as D23.

**2. The Phase 7 demo LLM — an open question this informs but does not close.** Spec 08 §1 still reads "OpenAI with a cost cap, or Ollama on the instance", and its Risks name Ollama as the reason a small EC2 may not fit. Cerebras is a third option, with one correction to how it was first framed: **Cerebras has no embeddings endpoint, so it cannot remove Ollama from the instance on its own.** Triage on Cerebras still needs an embedding source: Ollama serving `nomic-embed-text` only (137M parameters, small next to an 8B chat model), or OpenAI embeddings. That needs the chat/embedding provider split, which this spec defers (decision 4). The open choice moves to Phase 7 plan review with a sharper set of options instead of being settled here.

## Verified facts (2026-10-22 local, 2026-10-23 UTC)

Read from the live sources before writing. Where the original brief and the docs disagree, the docs win and the discrepancy is listed.

**`GET https://api.cerebras.ai/public/v1/models`** — exactly two models:

| id | Context | Max completion | Price in / out (USD per 1M tokens) | Structured outputs | Reasoning |
|---|---|---|---|---|---|
| `gpt-oss-120b` | 131,072 | 40,960 | 0.35 / 0.75 | yes | yes |
| `qwen-3.8-27b` | 65,536 | not read | 0.99 / 1.49 | yes | yes |

`requests_per_minute` and `tokens_per_minute` are `null` in the public listing, so a personal account's rate limits are **unknown** (Risks).

**`inference-docs.cerebras.ai/capabilities/structured-outputs`** (no page date; says "API version 2 enforces these requirements"):

- `strict: true` enables constrained decoding; without it the schema is only a hint.
- Supported: `enum`, `const` (primitives), `minimum`/`maximum`/`exclusive*`/`multipleOf`, non-root `anyOf`, local non-recursive `$ref` + `$defs`, `required` (optional = omitted from `required`). Annotations (`description`, `title`, `default`) are accepted and not enforced.
- Not supported: `format`, `pattern`, `minItems`/`maxItems`, `oneOf`/`allOf`/`not`, `nullable`, external or recursive `$ref`, root unions, `items: true`.
- Required: root `type: object`; `additionalProperties: false` on **every** object.
- Limits: 5,000 schema characters (property names, definition names, enum/const strings; descriptions excluded), nesting depth 10, 500 properties, 500 enum values.

**Discrepancies with the brief:**

1. **`minLength`/`maxLength`.** The brief lists them as rejected outright. The docs scope it: "strict tool schemas for `qwen-3.8-27b` do not support `minLength` or `maxLength`." Whether `response_format` on `gpt-oss-120b` rejects them is not stated. This does not change the design (decision 5 strips them anyway), but the implementation must measure which keywords actually 400 on each model and record the result in the transform's docstring, as `_grammar_safe_schema` records its Ollama measurement.
2. **The schema budget** (5,000 characters, depth 10) is not in the brief. Measured: TriageResult uses 394 characters and 20 enum values; JudgeScore uses 43 and 0. Ample headroom, but a gate holds it (G11.1), because the taxonomy can grow.

**Schema audit, measured from the real Pydantic models** (not inferred from source):

| Schema | Rejected keywords present | Objects lacking `additionalProperties: false` |
|---|---|---|
| `TriageResult` | `Citation.chunk_id.format=uuid`; `minLength`/`maxLength` on `summary`, `recommended_resolution`, `Citation.claim` | none (`extra="forbid"`) |
| `JudgeScore` (the rubric the judge is actually called with) | `rationale.maxLength=1000` | none |

The precedent: commit `8eba4f2` was this exact class of bug against Ollama. Every fake-provider gate stayed green while real triage failed 100% of the time, because the fake never compiles a schema. Here, `format: uuid` alone would 400 the triage request, and `maxLength` on `rationale` may 400 every judge call (discrepancy 1).

## Scope (in)

### 1. A Cerebras provider class
- `CerebrasProvider` in `backend/app/llm/provider.py`, beside the others. It uses httpx and no SDK (the module's existing rule), with base URL `https://api.cerebras.ai/v1` and `/chat/completions` in OpenAI-compatible shape.
- `complete_structured()` sends `response_format: {type: json_schema, json_schema: {name, schema, strict: true}}`, temperature 0 and a fixed `seed` (supported per the model listing).
- `embed()` raises a typed error without making a network call. Silently returning nothing would surface as an empty retrieval much later; raising surfaces it at the call site.
- Usage → `StructuredCompletion(tokens_in, tokens_out, model)`. `gpt-oss-120b` is a reasoning model. The implementation must verify that (a) the JSON answer arrives in `message.content` and not in a separate reasoning field, and (b) reasoning tokens are counted in `completion_tokens`, so the cost estimate covers them. Both are assumptions until measured.

### 2. A third schema transform
- `_cerebras_strict_schema()` strips every unsupported keyword at every depth (`format`, `pattern`, `minLength`, `maxLength`, `minItems`, `maxItems`), sets `additionalProperties: false` on every object, and composes with `_strict_schema` (decision 5).
- It strips rather than lowers bounds, for the reason `_grammar_safe_schema` gives: the Pydantic model still enforces the real limits when the response is validated. An over-long triage answer becomes a normal repair retry. An over-long judge rationale becomes a failed judgement, which G11.8 makes visible.
- If the transform meets a construct it cannot rewrite safely (`oneOf`, `allOf`, `not`, `nullable`, a recursive `$ref`), it raises instead of dropping it. Removing `maxLength` loosens a bound the response check restores; removing `oneOf` changes what the schema means. None occur today, and a future model that adds one should fail loudly in CI (G11.1), not quietly in production.

### 3. Judge routing through the existing factory
- `get_provider(settings=None, chat_model=None, provider=None)`: a `provider=` parameter beside `chat_model=`, so the one module allowed to know providers exist (D11, D19 decision 1) is still the only one that chooses.
- New setting `JUDGE_PROVIDER`. Unset means the judge inherits `LLM_PROVIDER`, which is exactly today's behaviour, so the D11 local-first default does not move.
- The one call site, `backend/app/eval/judge.py:69`, becomes `get_provider(settings, chat_model=settings.judge_model, provider=settings.judge_provider)`.
- **Rejected: passing a doctored `Settings`** (a copy with `llm_provider` overwritten). The caller would then have to know which field selects a provider and what to put there, which is provider knowledge leaking out of `provider.py`. A copied Settings also bypasses validation unless re-validated, so it could carry a combination `Settings` itself would refuse.
- **Rejected: a separate `get_judge_provider()`**, for the reason D19 decision 1 already records: it would be a second place that knows providers exist.

### 4. Configuration and keys
- `CEREBRAS_API_KEY` and `JUDGE_PROVIDER`: blank entries in `.env.example`, passed through to `backend` and `worker` in `infra/docker-compose.yml` with empty defaults.
- `Settings` refuses `JUDGE_PROVIDER=cerebras` when the key is unset or blank, **at load**, not at the first judge call. The judge swallows its exceptions by design (G5.4, a judge outage must not fail the batch), so a lazily detected missing key would produce a batch that reports `completed` with zero judged tickets. The factory refuses a blank key as well, mirroring the `openai` branch.
- `LLM_PROVIDER=cerebras` is refused with a message naming the deferred embedding split (decision 4), not accepted and then failing at the first `embed()`.
- The repo is public and gitleaks runs in CI. The key lives only in `.env`, which is already ignored.

### 5. The D5 family check
- `_model_family` in `config.py` is replaced by lineage normalisation (decision 6). Today it takes the family by cutting at Ollama's `:tag`, and Cerebras puts the size after a hyphen. Measured against the current validator:

  ```
  triage=gpt-oss:20b   judge=gpt-oss-120b  -> accepted   (same family)
  triage=gpt-oss:120b  judge=gpt-oss-120b  -> accepted   (identical weights, two providers)
  triage=qwen3:8b      judge=qwen-3.8-27b  -> accepted   (same lineage)
  ```

  The validator's docstring says it "errs toward refusing"; across provider naming conventions it fails open.
- **No provider axis.** Different providers say nothing about different weights. `gpt-oss:120b` on Ollama and `gpt-oss-120b` on Cerebras are the same model, so a provider-aware check could only make this case *easier* to pass. Family comparison is sufficient once the normalisation is correct, and it is the only axis that tracks the thing D5 cares about: shared blind spots.

### 6. Provenance in the regression table
- Migration `0009`: `eval_batches.judge_provider`, backfilled from `llm_provider`. Unlike `0008`'s `"unknown"` backfill, this one is a fact, not a guess: before this spec the judge could only use the global provider, so every existing batch's judge provider *is* its `llm_provider`.
- `GET /api/eval/batches[/{id}]` and `GET /api/config/agent` return `judge_provider`. The *Models* column in `eval/baseline.md` names the provider on both sides of the arrow.
- Why it matters: 0008 exists because two rows that look comparable but are not is "the one failure [the table] cannot tolerate". A batch judged on Cerebras recorded as `llm_provider=ollama` would be exactly that row.

### 7. Cost table
- Add `gpt-oss-120b` (0.35, 0.75) and `qwen-3.8-27b` (0.99, 1.49), and set `PRICING_AS_OF` to the date the rates were read.
- **The free credit is not modelled.** The estimate is list price. A personal credit makes real spend zero, which is exactly when a silently-zero estimate stops being detectable: nobody notices a $0 figure when the bill is $0 too. The estimate stays the figure a customer deployment would pay, and the credit is a fact about one account, not about the system.
- Heuristic check: `estimate_cost()` short-circuits names containing `:` (Ollama tags) or prefixed `fake:`/`ollama:`. `gpt-oss-120b` and `qwen-3.8-27b` contain neither, so they reach the table lookup. The local tag `gpt-oss:120b` still costs $0, which is correct, because it is local. Asserted in G11.6.
- Rough scale, an estimate not a measurement: a 20-ticket batch is 20 judge calls; at ~3k tokens in and ~1k out (reasoning included), that is about $0.04 per batch on `gpt-oss-120b`.

## Scope (out)

- **Triage on Cerebras** and the `chat_provider`/`embedding_provider` split it requires: deferred to Phase 7 plan review (decision 4).
- Cerebras in any default path: CI, the compose default, or the default judge.
- Tool calling and streaming. The graph calls tools directly (D16 decision 2) and the provider interface has no streaming method.
- `qwen-3.8-27b` vision, and the dedicated/trial models the docs also list (`gemma-4-31b`, `kimi-k2.7-code`).
- Modelling account credits or spend caps in code.
- Any model writing labels (see the G1.5 assessment).

## Gates & checks

Every gate names how it fails, and each fails against the code as it stands today (D22: a gate that cannot fail looks like coverage and is worse than none).

- **G11.1 Strict-schema transform (offline, CI).** A checker in `tests/` encodes the strict subset as verified above, with that date. For both `TriageResult.model_json_schema()` and `JudgeScore.model_json_schema()`, the transformed schema has no unsupported keyword at any depth, `additionalProperties: false` on every object, a root `type: object` with no root union, only local non-recursive `$ref`, and stays within 5,000 characters, depth 10, 500 properties and 500 enum values. **Guard of the guard:** the same checker must *reject* the raw `TriageResult` schema and name `chunk_id`'s `format`, so a vacuous checker fails. A schema containing `oneOf` makes the transform raise. After the transform, `TriageResult` still rejects a 2,001-character `summary` and a non-UUID `chunk_id`, proving the domain limits were not removed with the transport ones. *Fails today:* no transform exists.
- **G11.2 Judge routing (offline, CI).** The network is replaced by a recording transport, and no test reaches `api.cerebras.ai`.
  - With `JUDGE_PROVIDER=cerebras` and a placeholder key, the judge's request goes to `/v1/chat/completions` with `response_format.type = json_schema`, `strict: true`, the G11.1-transformed `JudgeScore` schema, temperature 0 and a bearer header.
  - In the same process, the triage, ingestion and retrieval call sites still get the base provider.
  - `CerebrasProvider.embed()` raises, and the transport records zero requests.
  - With `JUDGE_PROVIDER` unset, the judge uses `LLM_PROVIDER`, which is today's behaviour.

  *Fails if* any judge path reaches the base provider, or any non-judge path reaches Cerebras.
- **G11.3 Refusal at load (offline, CI).** `Settings` with `JUDGE_PROVIDER=cerebras` and `CEREBRAS_API_KEY` unset, `""` or `"   "` raises at construction. `LLM_PROVIDER=cerebras` raises with a message naming the embedding split. `JUDGE_PROVIDER=fake` with `APP_ENV=prod` raises. `.env.example` carries blank `CEREBRAS_API_KEY=` and `JUDGE_PROVIDER=` entries. *Fails if* key validation is lazy: an implementation that checks only in the factory passes construction and fails this gate.
- **G11.4 Family separation (offline, CI).** A table of pairs:
  - **Refused:** `gpt-oss:20b`/`gpt-oss-120b`, `gpt-oss:120b`/`gpt-oss-120b`, `qwen3:8b`/`qwen-3.8-27b`, `llama3.1:8b`/`llama3.1:70b` (the D20 finding 5 case, kept).
  - **Accepted:** `llama3.1:8b`/`qwen2.5:7b` (today's default must still boot) and `llama3.1:8b`/`gpt-oss-120b`.
  - Under decision 6 option B, an unlisted family name is refused with a message naming the table.

  *Fails today:* the first three refused pairs are accepted (measured above).
- **G11.5 Provenance (CI: migration + offline).** `scripts/check_migration_cycle.py` runs 0009 up → down → up. After upgrade, every existing row has `judge_provider = llm_provider`. The batch row built from a `Settings` whose `judge_provider` differs from its `llm_provider` records the judge's, not the triage provider's. That assertion is the point: one test setting both to `fake` could never fail. The batch endpoints and `/api/config/agent` expose `judge_provider`. *Fails if* the column is copied from `llm_provider` at write time.
- **G11.6 Cost (offline, CI).**
  - `estimate_cost("gpt-oss-120b", 1_000_000, 1_000_000) == 1.10`
  - `estimate_cost("qwen-3.8-27b", 1_000_000, 1_000_000) == 2.48`
  - `estimate_cost("gpt-oss:120b", …) == 0.0`
  - an unknown model is still `0.0`
  - `PRICING_AS_OF` equals the rate-reading date

  *Fails today:* both Cerebras ids return 0.0.
- **G11.7 Isolation and CI posture (offline, CI).**
  - `check_runtime_isolation.py` stays green.
  - No file under `tests/`, `scripts/`, `fixtures/` or `.github/` references `CEREBRAS_API_KEY` or `api.cerebras.ai`, apart from this gate's own needle, which it assembles at runtime. The development-time world never holds the key (CLAUDE.md isolation rules), and every real-model gate drives the stack, which holds it.
  - `ci.yml` never sets `LLM_PROVIDER` or `JUDGE_PROVIDER` to `cerebras` and references no Cerebras secret.
  - gitleaks green.
  - Run once with a planted reference to prove it fails, as G10.2 did for the isolation guard.
- **G11.8 Real-model judge (opt-in, code owner only).** `PHASE11_RUN_CEREBRAS=1 PHASE11_REQUIRE_LIVE=1`, against a stack with `JUDGE_PROVIDER=cerebras JUDGE_MODEL=gpt-oss-120b`:
  - (a) A batch over the 20 seeds completes with `judged_tickets` equal to the number of results carrying a non-empty `recommended_resolution`. Zero swallowed judge failures is the assertion that catches a schema 400, which the judge would otherwise absorb into `None`.
  - (b) Every `llm.judge` audit row reports model `gpt-oss-120b`, non-zero tokens and a non-zero `cost_estimate`. The gate **fails rather than skips** if any row reports `fake:*` or an Ollama tag (the G2.4 pattern).
  - (c) The G5.2 canary passes on this judge: the wrong resolution scores strictly lower on both rubric dimensions.

  The result goes into `eval/baseline.md` with date, models and providers. CI skips this gate; it never fakes it (D19 decision 3).

## Definition of done

- G11.1–G11.7 green in CI on the fake provider. G11.8 run once by the code owner holding the key and recorded in `eval/baseline.md`.
- **Noise floor re-measured:** two batches at an identical configuration with the Cerebras judge, recorded side by side. The local stack proved bit-for-bit repeatability; a hosted judge is not assumed to have it. This is a measurement, not a pass/fail gate, because inventing a tolerance before seeing the data would fit the gate to the result.
- The `TriageResult` schema's live compile on Cerebras is recorded as **unproven** until triage runs there (decision 4). G11.1 proves it offline against the documented subset, the way G4.1's Auth0 half stays unproven without a tenant.
- D23 and the D19 decision 1 amendment finalised. README (*LLM provider*), ARCHITECTURE (provider abstraction and measurement lines), `.env.example` and compose updated **in the same PR** (development-loop rule).

## Risks

- **The key is personal and expiring.** Only one code owner can run G11.8 or produce a Cerebras-judged row, the same shape as the open "Auth0 tenant does not exist yet" item. Recorded as an open item. Mitigation: the default judge stays local, so nothing breaks when the credit ends; only the opt-in path goes dark.
- **Unknown rate limits.** The public listing reports `null`. A 20-call batch is small, but the judge swallows a 429 like any other error. G11.8(a) makes that visible instead of letting it read as a weak batch.
- **Hosted determinism.** The three identical local rows set the noise floor at zero. A hosted judge may not reproduce. Deterministic scores are unaffected (triage stays local); judge means may move. Mitigation: temperature 0 plus a seed, and the noise-floor measurement in the definition of done.
- **Judge scores from different judges are not comparable.** Mixing a `qwen2.5:7b`-judged row with a `gpt-oss-120b`-judged row reads as a change in quality when it is a change of grader. Mitigation: decision 3.
- **Docs drift.** The strict subset is versioned ("API version 2") and the page has no date. G11.1's checker carries its verification date, so a change shows up as a failing request against a dated contract, not a mystery.
- **Model retirement.** If `gpt-oss-120b` is withdrawn, rows judged on it cannot be reproduced. Mitigation: provenance (§6) records exactly what judged each row.
- **Data leaves the boundary.** Ticket text and retrieved policy excerpts go to a third party. That is acceptable for fictional Meridian data, but for a real customer it is a procurement question before it is an engineering one. Worth saying out loud in an FDE context; noted in the README.
- **Verbose reasoning model.** A `rationale` over 1,000 characters fails validation and becomes `None`. Mitigation: the judge prompt states the bound, and G11.8(a) counts failures.

## Assessment: does cheap, fast batching change G5.5 or G1.5?

**G5.5 — no, and recommended against presenting it as if it did.** G5.5 needs two batches at different `agent_version`s. `AGENT_VERSION` (`backend/app/agents/prompts.py`) bumps when **prompt text** changes. A model swap is a configuration change, recorded in the *Models* column: a third kind of row, same version and different models, which the table already distinguishes. Moving the judge to Cerebras creates no new agent version. It also barely speeds a batch up, because batch time is dominated by triage, which stays on local `llama3.1:8b`.

What it does change is the *cost* of closing G5.5 honestly. Both sides of a version comparison must share one judge (decision 3), so the `triage-v1` side has to be re-run under whichever judge the `triage-v2` side uses. At about $0.04 a batch that is trivial. The precondition is unchanged: a genuine prompt change, made for a reason other than the eval misses. Tuning the prompt to fix EVAL-012/019 and then reporting the gain would be fitting to the test set.

**G1.5 — not unblocked, and the useful version of the idea needs a constraint first.** G1.5 is a human signing off all 20 labels. A large model's disagreements with the draft labels could serve **only as an ordering of human attention**, under three rules:

1. **The model never writes a label.** Its output is a shortlist, not a diff to apply. A model that writes the answer key it is later graded against is the D5 failure mode.
2. **The shortlist never shortens the review.** All 20 are signed off. A ticket the model agrees with is not therefore correct, since model and draft can share a mistake. If anything, review blind first and consult the shortlist after, to avoid anchoring.
3. **The model that informs the review must never be the triage model scored against the result.** If `gpt-oss-120b` shapes the labels and Phase 7 later puts triage on `gpt-oss-120b`, triage is graded against labels it influenced.

**A conflict to flag:** the natural place for a shortlist script is `scripts/`, but CLAUDE.md says nothing in the development-time world gets a production model key. A script calling Cerebras would break that. The rule-compliant route is an ordinary eval batch through the stack, whose per-ticket `expected` vs `actual` *is* the disagreement list. That needs triage on the large model, which is deferred (decision 4). Until then the honest shortlist is the one already recorded: EVAL-012 and EVAL-019, missed identically across two configurations. **Recommendation:** do G1.5 by hand now, starting with those two. It is 20 tickets, and no tooling is worth building to avoid reading them.

## Key decisions (for the code owners to confirm)

1. **Routing via `provider=` on `get_provider()` plus a `JUDGE_PROVIDER` setting that inherits `LLM_PROVIDER` when unset.** Rejected: a doctored `Settings` (spreads provider knowledge to callers and bypasses validation), and a second factory (D19 decision 1's own reason).
2. **Judge model on Cerebras: `gpt-oss-120b`** (recommended) over `qwen-3.8-27b`. It is larger, about a third of the price, has twice the context, and is a different family from triage. If Phase 7 later moves triage to `gpt-oss-120b`, G11.4 forces the judge to `qwen-3.8-27b` automatically, which is the check doing its job.
3. **Which judge is "of record" for `eval/baseline.md`.**
   - **A (recommended):** the local judge stays the default; Cerebras is opt-in; any comparison of judge means names its judge and holds it fixed on both sides. This keeps D11, keeps CI and other contributors unaffected, and survives the credit ending.
   - **B:** `gpt-oss-120b` becomes the judge of record for all new rows. Stronger scores, but the baseline then depends on one person's expiring key.
4. **Triage on Cerebras: deferred to Phase 7 plan review** (recommended), not built here. It needs `chat_provider`/`embedding_provider` split across three more call sites (ingestion, retrieval, graph), and a query-embedding/chunk-embedding consistency check that retrieval does not perform today. The judge needs none of that. Phase 7 owns the demo-LLM choice and will reuse this spec's provider class. **Alternative:** include the split now, so spec 08 inherits a finished option, at the cost of making this spec about two features.
5. **Schema transform composes with `_strict_schema`** (every property required, optionality as `null`) (recommended). The judge's `rationale` and the citation locators are then always emitted rather than skipped by the model. **Alternative:** keep Pydantic's `required` as emitted, since Cerebras allows omission: one fewer rewrite, but a quieter judge. Either way the transform is Cerebras-only. Applying its stricter subset to the Ollama and OpenAI paths would be a behaviour change with no evidence behind it.
6. **Family normalisation.**
   - **A:** strip size suffixes in both conventions (`:20b`, `-120b`) and separators. This gives generation-level families (`qwen2.5` ≠ `qwen3.8`) and keeps open-ended names working.
   - **B (recommended):** an explicit lineage table in code (`llama`, `qwen`, `gpt-oss`, `gemma`, …), with unknown names refused at load. It errs toward refusing, as the D20 finding 5 docstring already claims to. A new model costs one reviewed line, the same discipline as the pricing table (D19 decision 7).

   Neither adds a provider axis (§5).
7. **Provenance column with a factual backfill** (migration 0009, `judge_provider = llm_provider`), rather than recording the judge provider only in audit payloads, where the regression table cannot see it.
8. **Cost is list price; credits are not modelled** (§7).
9. **CI stays on the fake provider.** G11.8 is opt-in like G2.4 and G5.2, and every real-model gate drives the stack and never calls Cerebras from `tests/` (G11.7).
10. **Assessments as above:** G5.5 unchanged; G1.5 by hand, with model input limited to a shortlist under the three rules.

## Task plan

*(Filled after spec approval — review gate.)*
