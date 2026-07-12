# Spec: Phase 1 — RAG Foundation

**Status:** Draft — awaiting review
**Owner:** Muhammad
**Depends on:** 01-phase0-foundation.md (approved + built)
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
- The worker runs as its own compose service (reusing the backend image with a different command) — added to `infra/docker-compose.yml` this phase. Queue library (arq/RQ/Celery) picked at plan review.
- Worker consumes ingestion jobs: extract → chunk → embed → store → mark `ready` (or `failed` + error_message).
- Ingestion is idempotent: re-running a job for a document deletes and rewrites that document's chunks. A document stuck in `processing` (worker crash mid-ingestion) is recoverable via `POST /api/documents/{id}/reingest` (admin) — never permanently stuck.
- PDF extraction must preserve page numbers. Markdown: section = nearest heading. Plain text: section null, page null, chunk_index only.
- Chunking: overlapping windows, target ~500 tokens, overlap ~50 (config values, not hardcoded).
- Embeddings via provider factory (`nomic-embed-text` on Ollama for dev). Embedding dimension is a config constant; migration uses it.

### 4. Retrieval
- Internal function `retrieve(org_id, query, k)` → top-k chunks by cosine similarity, each with: text, score, document title, version, page, section, chunk id.
- `GET /api/documents` list (includes per-document chunk_count — the Phase 6 Knowledge screen shows it) + `GET /api/documents/{id}` status endpoint (Admin ingestion status view).
- A thin debug endpoint `POST /api/retrieve` (dev-only, flag-gated) to test retrieval manually.

### 5. Eval seed set (built NOW, not in Phase 5)
- `fixtures/eval_tickets.json`: 15–20 tickets, each with input fields + labeled expected `category`, `urgency`, `recommended_team`.
- Committed as fixtures this phase; the loader that inserts them into the `tickets` table (with `is_eval_seed=true`) ships in Phase 2, when that table exists. (The `tickets` table is a Phase 2 migration — Phase 1 cannot load into it.)
- At least 3 knowledge documents in `fixtures/` (e.g., VPN policy, priority guidelines, password reset procedure) that the labels are grounded in.

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
- **G1.5 Seed set review:** every eval ticket's labels are justifiable from the fixture docs (human review — Muhammad).

## Definition of done
- Upload → background ingest → `ready` works for all three formats.
- Retrieval returns ranked chunks with full citation metadata.
- Admin can see ingestion status per document via API.
- Eval seed set (15–20 labeled tickets + ≥3 fixture docs) committed; the DB loader lands in Phase 2 with the `tickets` table.
- All five gates pass; tests exist for G1.1–G1.4 (Codex may generate them from this spec).

## Risks
- Embedding dimension lock-in: switching models later requires re-embedding. Mitigation: store model name per chunk; re-embed script noted as future work.
- PDF extraction quality varies. Mitigation: fixture docs are clean text-layer PDFs; OCR out of scope.

## Task plan
*(Filled after spec approval — review gate.)*
