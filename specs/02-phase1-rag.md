# Spec: Phase 1 — RAG Foundation

**Status:** Approved (2026-07-20, FlowForge Code Owners)
**Owner:** FlowForge Code Owners
**Depends on:** 01-phase0-foundation.md (approved + built), 09-demo-enterprise-corpus.md (defines the fixture corpus and eval seed set)
**Gate to exit:** Phase 1 definition of done demoed + spec review of Phase 2

## What this phase delivers

Company knowledge becomes searchable. An Admin uploads a PDF/Markdown/text file; it is stored, extracted, chunked, embedded, and stored in pgvector with full citation metadata. A retrieval function returns ranked, citable chunks for a query. The labeled eval ticket seed set is created.

## Scope (in)

### 1. Data model (adds to Phase 0 schema via Alembic migration)
- `documents`: id, org_id, title, version, status (`pending|processing|ready|failed`), file_ref, error_message, created_at
- `chunks`: id, org_id, document_id, chunk_index, text, embedding vector(dim per model), embedding_model, page, section, token_count
  - `org_id` is denormalized from the document so retrieval filters tenants directly on the chunk query (D7: org_id on every table), and `embedding_model` is stored per chunk so a future model switch can find stale embeddings (this backs the re-embed mitigation in Risks).

### 2. Upload endpoint + storage
- `POST /api/documents` — multipart upload. Accept: `.pdf`, `.md`, `.txt`. Reject others with 415.
- Max file size: 20 MB (config). Store original to local disk volume (`/data/uploads/{org_id}/{doc_id}`), path in `file_ref`.
- Returns `202` with document id; ingestion continues in background.

### 3. Background ingestion job (Redis queue)
- The worker runs as its own compose service (reusing the backend image with a different command) — added to `infra/docker-compose.yml` this phase. Queue library: **arq** (decided at plan review, 2026-07-20 — async-native, matches the asyncio stack).
- Worker consumes ingestion jobs: extract → chunk → embed → store → mark `ready` (or `failed` + error_message).
- Ingestion is idempotent: re-running a job for a document deletes and rewrites that document's chunks. A document stuck in `processing` (worker crash mid-ingestion) is recoverable via `POST /api/documents/{id}/reingest` (admin) — never permanently stuck.
- PDF extraction must preserve page numbers. Markdown: section = nearest heading. Plain text: section null, page null, chunk_index only.
- Chunking: overlapping windows, target ~500 tokens, overlap ~50 (config values, not hardcoded).
- Embeddings via provider factory (`nomic-embed-text` on Ollama for dev). Embedding dimension is a config constant; migration uses it.

### 4. Retrieval
- Internal function `retrieve(org_id, query, k)` → top-k chunks by cosine similarity, each with: text, score, document title, version, page, section, chunk id.
- `GET /api/documents` list (includes per-document chunk_count — the Phase 6 Knowledge screen shows it) + `GET /api/documents/{id}` status endpoint (Admin ingestion status view).
- A thin debug endpoint `POST /api/retrieve` (dev-only, flag-gated) to test retrieval manually.

### 5. Eval seed set + fixture corpus (built NOW, not in Phase 5)
- Defined in full by **spec 09 (Demo Enterprise & Knowledge Corpus)**: the Meridian Dynamics corpus (10 template-conforming docs across PDF/MD/TXT), `fixtures/enterprise/taxonomy.json`, and `fixtures/eval_tickets.json` (20 labeled eval tickets with grounding references + 5 demo tickets).
- Committed as fixtures this phase; the loader that inserts tickets into the `tickets` table (with `is_eval_seed=true`) ships in Phase 2, when that table exists. (The `tickets` table is a Phase 2 migration — Phase 1 cannot load into it.)
- Corpus drafted by Codex, reviewed doc-by-doc and label-by-label by the code owners (spec 09 gates G9.1–G9.4).

## Scope (out)
- No agent, no LangGraph, no triage (Phase 2).
- No reranking, no hybrid search, no multi-query expansion (note as future work).
- No document deletion/versioning UI (delete endpoint optional; versioning is metadata-only).
- No OCR for scanned PDFs (text-layer PDFs only; document this limit).

## Gates & checks
- **G1.1 Ingestion correctness:** uploading each fixture doc ends in `ready` with >0 chunks, and page/section metadata present for PDFs/MD.
- **G1.2 Retrieval sanity:** for 5 canned queries, the expected fixture doc appears in top-3. Queries + expected doc ids live in `fixtures/retrieval_checks.json`; a script asserts the hits. (Scripted check, not vibes.)
- **G1.3 Tenant isolation:** retrieval for org A never returns org B chunks (test with two seeded orgs).
- **G1.4 Failure path:** unsupported type → 415 at upload; oversized → 413 at upload; a corrupt file that passes upload → `failed` with a human-readable error_message within 60s of worker pickup; a worker killed mid-ingestion leaves a document that `reingest` recovers — never a permanently stuck `processing`.
- **G1.5 Seed set review:** every eval ticket's labels are justifiable from the fixture docs (human review — FlowForge Code Owners).

## Definition of done
- Upload → background ingest → `ready` works for all three formats.
- Retrieval returns ranked chunks with full citation metadata.
- Admin can see ingestion status per document via API.
- Eval seed set (15–20 labeled tickets + ≥3 fixture docs) committed; the DB loader lands in Phase 2 with the `tickets` table.
- All five gates pass; tests exist for G1.1–G1.4 (Codex may generate them from this spec).

## Risks
- Embedding dimension lock-in: switching models later requires re-embedding. Mitigation: store model name per chunk; re-embed script noted as future work.
- PDF extraction quality varies. Mitigation: fixture docs are clean text-layer PDFs; OCR out of scope.

## Key decisions (confirmed 2026-07-20 by the FlowForge Code Owners)
1. Queue library: **arq** — async-native Redis queue; matches FastAPI/asyncpg/async-SQLAlchemy without thread bridging.
2. PDF extraction: **pypdf** — BSD-licensed, sufficient for the clean text-layer fixture PDFs (OCR out of scope).
3. CI embeddings: **deterministic fake provider** — `LLM_PROVIDER=fake` produces hash-based vectors at the configured dimension so G1.1/G1.2 run in CI without Ollama; refused when `APP_ENV=prod`. Real Ollama remains the dev default.
4. Embedding dimension: `EMBEDDING_DIM=768` config constant (nomic-embed-text); migration uses it.

## Task plan (approved 2026-07-20 by the FlowForge Code Owners)

One atomic commit per task. **[CC]** = Claude Code, **[CX]** = Codex.

1. **[CC] Data model** — `documents` + `chunks` ORM models (org_id denormalized, embedding_model, vector(EMBEDDING_DIM)); Alembic migration 0002 with working `downgrade()`.
2. **[CC] Embeddings** — implement `embed()` on Ollama/OpenAI providers via httpx (no provider SDKs) + deterministic fake provider; `EMBEDDING_DIM` config.
3. **[CC] Upload** — `POST /api/documents`: multipart, 415/413 enforcement, store to `/data/uploads/{org_id}/{doc_id}`, `pending` row, enqueue, 202.
4. **[CC] Queue + worker** — arq worker, compose `worker` service on the backend image, org context in job payloads.
5. **[CC] Extraction** — pypdf per-page text, Markdown nearest-heading sections, plain text fallback.
6. **[CC] Chunker** — overlapping windows, `CHUNK_TARGET_TOKENS`/`CHUNK_OVERLAP_TOKENS` config.
7. **[CC] Ingestion pipeline** — extract → chunk → embed → store; idempotent delete-and-rewrite; `processing|ready|failed` + error_message; `POST /api/documents/{id}/reingest`.
8. **[CC] Retrieval** — `retrieve(org_id, query, k)` cosine top-k with citation metadata; `GET /api/documents` (+chunk_count), `GET /api/documents/{id}`; dev-only `POST /api/retrieve` (404 in prod).
9. **[CX] Fixtures** — Meridian Dynamics corpus (spec 09), `eval_tickets.json`, `retrieval_checks.json`.
10. **[CX] Gate tests** — `tests/phase1/` for G1.1–G1.4 + adversarial pass.
11. **[CC] CI + docs** — Phase 1 gates wired into CI (fake provider), README update.
12. **G1.5** — code-owner review of every eval label against the corpus (human gate).
