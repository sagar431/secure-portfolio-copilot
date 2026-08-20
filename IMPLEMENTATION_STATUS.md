# Implementation Status

## Current step

Playbook Step 4 — secure deterministic chunks and authorization-first PostgreSQL keyword search.

## Completed acceptance criteria

- Step 1–3 health, identity, authorization, upload, parsing, preview, approval, versioning, rejection,
  and deletion behavior remains covered by regression tests.
- Reversible migration `20260821_0004` adds `document_chunks`, copied ACL/lifecycle/version metadata,
  page or sheet/row/cell provenance, content hashes, a generated PostgreSQL `TSVECTOR`, an
  ACL/lifecycle index, and a GIN full-text index.
- PDF chunking is deterministic by page and heading; XLSX/CSV chunking is deterministic by sheet and
  bounded contiguous row groups. Empty, inactive, unapproved, deleted, oversized, or inconsistent
  sources fail closed without content in the error.
- Chunks are created only while approving the current non-deleted version. Approval locks the
  version and atomically transitions lifecycle state, deactivates old chunks, inserts new chunks,
  updates the current-approved pointer, audits IDs/counts, and commits.
- Rejected versions never become searchable. Version replacement and document deletion deactivate
  affected chunks immediately, while search independently rechecks authoritative lifecycle rows.
- Every public production retrieval repository method requires `AuthorizationScope`. SQL applies
  grant-correlated tenant/company/department filters plus exact visibility/classification, approval,
  deletion, active-version, current-version, and active tenant/company filters before ranking.
- PostgreSQL keyword retrieval uses `plainto_tsquery('simple', query)` and deterministic rank/ID
  ordering. Query length is at most 500 characters, `top_k` at most 20, and each excerpt at most 500
  characters.
- Search returns chunk/document/version IDs, bounded excerpts, document metadata, page or
  sheet/row/cell provenance, and scores. Audits contain actor/request/resource IDs and counts only;
  query and document text are absent from audit/log output.
- Development/test-only `POST /api/development/authorized-search` rejects extra scope/identity fields.
  Production does not register it. Nora receives a safe 403 before repository search.
- The development-only React page displays current scope, index counts/status, bounded query/top-k,
  safe errors, results, IDs, metadata, provenance, and scores. It renders the backend list as-is and
  performs no client-side candidate filtering. Nora cannot mount or call it.
- Alice, Leo, Maya, Amir, and Lina receive only the exact tenant/department matrix. Nora has upload
  management only. Forged tenant/company/department/role/user/document/version/scope values do not
  alter authority.

## Pending acceptance criteria

None within Step 4.

## Verification result

Verified on 2026-08-21:

- Backend Ruff formatting/lint and strict mypy pass; the complete 132-test suite passes against the
  isolated real PostgreSQL test database.
- Focused chunking/repository/lifecycle coverage passes 25 unit tests; four PostgreSQL integration
  tests cover approval-only creation, provenance, inheritance, replacement/rejection/deletion,
  six-user isolation, forged values, limits, and redaction.
- Frontend Prettier, ESLint, strict TypeScript, all 40 Vitest tests, and production build pass.
  `npm audit` reports zero vulnerabilities; the production bundle excludes the search feature.
- Alembic upgrade, no-drift check, downgrade to `20260821_0003`, and re-upgrade pass. PostgreSQL
  contains `document_chunks` and its ACL/lifecycle and GIN search indexes.
- Manual API/UI checks cover Alice, Leo, Maya, Amir, Lina, and Nora. The PDF and XLSX chunk counts and
  representative provenance are recorded in the Step 4 completion report.
- `git diff --check` passes and the `Simulated_data` aggregate hash remains
  `e1bc83febaace2a2ad837ce9fd012aa7e7054b3837385bb54b9e44554a37f865`.

## Known limitations

- Search is a deterministic keyword/full-text baseline. It has no embeddings, vector similarity,
  hybrid fusion, semantic rewrite, reranker, or retrieval-quality evaluation; those are Step 5.
- `plainto_tsquery` requires all normalized terms and uses the PostgreSQL `simple` configuration; it
  does not provide natural-language intent understanding.
- Chunking uses deterministic heading heuristics and fixed row groups. It does not use semantic/LLM
  chunking, OCR, merged-cell interpretation, or calculated spreadsheet values.
- Indexing runs synchronously inside approval in this local build. The API exposes safe indexing
  status/counts, but there is no distributed queue or resumable background indexer.
- Search excerpts are bounded prefixes of matched authorized chunks, not highlighted contextual
  windows. React renders them as inert text.
- Development password authentication, local object storage, soft-delete retention, and the
  development-only inspector are not production deployment designs.

## Test commands

See [docs/testing-guide.md](docs/testing-guide.md) for exact automated, migration, PostgreSQL, API,
and UI verification commands.

## Next approved step

None. Work stops after Step 4; Step 5 embeddings/hybrid retrieval has not started.
