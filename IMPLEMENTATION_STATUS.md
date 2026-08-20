# Implementation Status

## Current step

Playbook Step 5 complete — approved-version embeddings, authorization-first hybrid retrieval,
citation previews, and curated Recall@5 reporting are implemented and verified.

## Implemented

- All completed Step 1–4 health, identity, authorization, ingestion, parsing, lifecycle, deterministic
  chunking, and keyword-search behavior remains in place.
- Reversible migration `20260821_0005` extends `document_chunks` with a 768-dimensional pgvector
  embedding, model name/version/dimension metadata, the embedded content hash, and
  `PENDING|READY|FAILED|STALE` lifecycle state. Database checks require a `READY` vector to match the
  fixed dimensions and current content hash. Status and HNSW cosine indexes support operations and
  vector search.
- `EmbeddingProvider` has strict Ollama, deterministic fake-test, and disabled implementations. The
  active contract is fixed to `nomic-embed-text:v1.5` with 768 dimensions. Ollama is restricted to
  explicit HTTP loopback addresses; development providers are rejected in production.
- Embedding work is bounded by validated batch, total-chunk, provider-request, and whole-operation
  limits. Provider output must preserve batch cardinality and contain finite, non-zero vectors of
  the expected dimension. Failures expose only a generic content-free error.
- Approval requires current upload-management authorization, locks the version, performs the legal
  transition, builds chunks, and embeds them before installing the replacement. The final commit
  atomically deactivates old chunks and clears their vectors as `STALE`, inserts the new current
  version as `READY`, updates the approved-version pointer, and records metadata-only audits. A
  chunking or embedding failure rolls the approval/replacement back.
- Rejection and deletion deactivate affected chunks, erase their embedding and model metadata, and
  mark them `STALE` in the same transaction as authoritative lifecycle removal. Search independently
  rejoins the authoritative document/version rows and requires the embedded hash to equal the
  current chunk hash.
- Development/test-only `POST /api/development/reindex-embeddings` backfills bounded `PENDING` or
  `FAILED` chunks only for current approved documents inside the caller's database-derived
  `MANAGE_UPLOADS` scope. Rows are locked with `SKIP LOCKED`; unauthorized or copied-ACL-corrupt
  rows are not processed. Existing Step 4 rows become `PENDING` when migration `0005` is applied.
- Authorized search denies callers without `QUERY_DOCUMENTS` before the embedding provider or
  repository is used. It embeds only the query, then materializes an authorization- and
  lifecycle-filtered PostgreSQL CTE before cosine distance, scoring, ordering, or `top_k`.
- Hybrid score is deterministic: normalized PostgreSQL full-text rank contributes 35% and bounded
  cosine similarity contributes 65%. Results order by final score, keyword score, then chunk ID.
  Only `READY` embeddings for the configured model/version/dimensions and matching content hash are
  eligible.
- Results retain the Step 4 bounds and now return keyword, vector, and final scores plus a citation
  DTO containing document title, version, chunk/document/version IDs, bounded excerpt, and PDF or
  spreadsheet location. The retrieval audit contains permitted IDs, counts, and `top_k`, never
  query text, vectors, excerpts, or forbidden candidates.
- The development-only React inspector strictly validates the response, displays embedding/index
  status and counts, the three scores, citation preview, and safe indexing/degraded/empty/error
  states. It renders returned evidence as inert text and performs no client-side candidate filter.
  Curated synthetic queries show measured Recall@5, expected-hit, and authorization-leak counts;
  ad hoc queries honestly show `not_run`.
- Automated tests use the deterministic fake provider and do not require Ollama or another live
  embedding API.

## Pending acceptance criteria

None within Step 5. The curated cases achieved the expected top-five hit with zero authorization
leaks in the integration gate, so a reranker is not necessary for this checkpoint.

## Verification result

Step 4 was verified on 2026-08-21: backend format/lint/type checks and its then-current 132-test
suite passed against isolated PostgreSQL; frontend format/lint/type checks, 40 Vitest tests, build,
and audit passed; migration `0004` reversibility/no-drift and the Step 4 manual API/UI matrix passed.

Step 5 was independently verified on 2026-08-21. Backend Ruff format/lint and strict mypy pass; all
167 backend tests pass against isolated PostgreSQL. Frontend Prettier, ESLint, strict TypeScript,
all 47 Vitest tests, the zero-vulnerability npm audit, and the production build pass. Migration
`0005` upgrade, no-drift check, downgrade to `0004`, re-upgrade, and second no-drift check pass. A
live local Ollama smoke returned one finite, non-zero 768-dimensional
`nomic-embed-text:v1.5` vector. Production backend/frontend exclusion, tracked-secret scan,
`.env` ignore/untracked status, `Simulated_data` integrity, and `git diff --check` also pass.

## Known limitations

- There is no reranker, semantic query rewrite, natural-language answer generation, LLM, MCP,
  memory, financial calculation, agent loop, cloud embedding provider, or production search route.
- Ollama and the fake provider are development/test adapters only. Production settings require the
  embedding provider to be `disabled`, and all `/api/development/*` retrieval routes are absent.
  Because approval currently requires synchronous embedding, approval also fails closed in
  production; a production provider/worker design is a later milestone.
- Approval embeds synchronously inside the request and transaction. Large inputs are bounded, but
  there is no durable background queue, retry scheduler, or resumable production indexer.
- Search fails closed with HTTP 503 when the configured query embedding provider is unavailable; it
  does not fall back to keyword-only retrieval. `PENDING`, `FAILED`, `STALE`, wrong-model, and
  wrong-hash chunks are excluded rather than partially searched.
- Migration `0005` fixes the index at 768 dimensions and the configured
  `nomic-embed-text:v1.5` identity. Changing the model contract requires an explicit migration and
  re-embedding plan.
- Hybrid weights are fixed at 35% keyword and 65% vector. The small curated set passes its expected
  top-five cases, but it is not a broad semantic-quality benchmark. Citation excerpts remain bounded
  chunk prefixes rather than highlighted contextual windows.
- The reindex endpoint is a development/test admin operation, processes at most the configured
  chunk limit per call, and must be repeated until it reports zero. It is not a production job API.
- The schema/status response recognizes `FAILED`, and reindex will retry such rows, but the current
  transactional approval/reindex paths roll provider failures back rather than persisting a FAILED
  transition. Operational failure tracking therefore remains audit-based in this local build.
- Development password authentication, local object storage, soft-delete retention, and the search
  inspector remain local demonstration designs.

## Test commands

See [docs/testing-guide.md](docs/testing-guide.md) for exact automated, migration, PostgreSQL,
Ollama, API/UI, reindex, and manual authorization checks.

## Next approved step

Step 6 — grounded RAG chat with citations.
