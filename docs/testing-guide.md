# Step 5 Testing Guide

Run commands from the locations shown. Tests use only synthetic identities and an isolated tmpfs
PostgreSQL test service. On 2026-08-21 these commands passed with 167 backend tests and 47 frontend
tests. Automated tests configure the deterministic fake embedding provider and do not require
Ollama.

## Backend quality checks

```bash
cd backend
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy app
cd ..
docker compose --profile test up -d test-db
docker compose exec -T test-db pg_isready -U portfolio -d portfolio_test

cd backend
TEST_DATABASE_URL=postgresql+asyncpg://portfolio:portfolio_test@127.0.0.1:5433/portfolio_test \
  uv run pytest
```

The suite includes all Step 1–4 regressions plus provider determinism, bounded ordered batches,
dimension/finite/non-zero rejection, production-provider restrictions, loopback-only Ollama URLs,
content-free provider errors, authorization-before-vector SQL construction, approved-version READY
vectors, lifecycle invalidation, bounded authorized backfill, copied-ACL corruption, hybrid scores,
citation identity/provenance, six-user isolation, forged values, and log/audit redaction.
PostgreSQL-backed tests refuse any database not named `portfolio_test`.

## Frontend quality checks

```bash
cd frontend
npm install
npm run format:check
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

Vitest uses jsdom and React Testing Library. `fetch` and XHR are replaced with deterministic success,
progress, poll, error, and cancellation behavior; no backend process is required for these tests.
Coverage includes capability gating, trusted option cascades, multipart metadata, safe request-ID
errors, previews with coordinates, inert unsafe strings, decisions, filtering/version upload,
deletion confirmation, development-only search routing, Nora denial, strict hybrid/citation response
parsing, bounded inputs, safe errors, embedding/index states, three-score rendering, citation preview,
and both `not_run` and completed evaluation-summary presentation. Backend integration tests provide
the measured curated result; UI fixtures verify presentation only.

## Compose and database checks

From the repository root:

```bash
docker compose config --quiet
docker compose up -d db
docker compose exec -T db pg_isready -U portfolio -d portfolio
```

Then verify migration reversibility and schema drift:

```bash
cd backend
uv run alembic upgrade head
uv run alembic check
DEMO_USER_PASSWORD='<choose a local 12+ character password>' \
  uv run python -m app.scripts.seed_development
DEMO_USER_PASSWORD='<same password>' uv run python -m app.scripts.seed_development
uv run alembic downgrade 20260821_0004
uv run alembic upgrade head
DEMO_USER_PASSWORD='<same password>' uv run python -m app.scripts.seed_development
```

Confirm the extension, document tables, embedding columns/constraints, and Step 5 indexes after the
final upgrade:

```bash
cd ..
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND (tablename LIKE 'document%' OR tablename LIKE 'parsed_%') ORDER BY tablename;"
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT indexname FROM pg_indexes WHERE tablename = 'document_chunks' ORDER BY indexname;"
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT column_name, data_type, udt_name, column_default FROM information_schema.columns WHERE table_name = 'document_chunks' AND column_name LIKE 'embedding%' ORDER BY ordinal_position;"
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'document_chunks'::regclass AND conname LIKE '%embedding%' ORDER BY conname;"
```

The final index list must include `ix_document_chunks_embedding_status` and the HNSW
`ix_document_chunks_embedding_cosine`. Downgrade to `0004` must remove the six embedding fields,
constraints, and indexes without removing the Step 4 chunk/search schema; re-upgrade must restore
them. Existing rows should have `embedding_status = 'PENDING'` after the upgrade.

## Live Ollama provider check

This check is separate from automated tests. Configure `.env` with the Step 5 values in the root
README. Start Ollama in one terminal (or use the running desktop service):

```bash
ollama serve
```

In another terminal, make the exact fixed model available and inspect it:

```bash
ollama pull nomic-embed-text:v1.5
ollama list
```

Then start the backend with `EMBEDDING_PROVIDER=ollama`. A non-loopback, HTTPS, credential-bearing,
query-bearing, or fragment-bearing `OLLAMA_BASE_URL` must fail settings validation. Do not use the
fake provider to claim live-model retrieval quality.

## Live smoke test

Start the database and backend, then run:

```bash
curl --fail-with-body http://127.0.0.1:8000/health
curl --fail-with-body http://127.0.0.1:8000/ready
curl --fail-with-body -H 'X-Request-ID: testing-guide' http://127.0.0.1:8000/health
```

Start the frontend, open <http://127.0.0.1:3000>, and confirm the anonymous route redirects to login.
Select each development-only demo card, enter the locally chosen seed password, and inspect tenant,
role, primary department, companies, query departments, and capabilities. Log out after each user.

Expected scopes:

- Alice: Orion Finance + Shared.
- Leo: Orion Legal + Shared.
- Maya: Orion Finance + Legal + Shared.
- Amir: Atlas Finance + Shared.
- Lina: Atlas Legal + Shared.
- Nora: Platform administration and Orion/Atlas upload management; no query departments.

As Nora, open `/admin/documents` and perform the Step 3 acceptance flow:

1. Upload `Simulated_data/orion/finance/Orion_FY2025_Board_Pack.pdf` as an Orion finance financial
   report for FY2025. Confirm four numbered preview pages, checksum/metadata, then approve it.
2. Upload `Simulated_data/orion/finance/Orion_FY2024_FY2025_Financials.xlsx` as a spreadsheet.
   Confirm all seven named sheets plus row/cell coordinates, then reject or approve it.
3. Use **New version** on a manageable document. Confirm the trusted scope metadata is locked and
   the returned version number increments. Retrying the same idempotency key must not add a version.
4. Upload `Simulated_data/invalid_inputs/not_a_real_pdf.pdf`; expect safe HTTP 415 and a request ID.
   Upload the unsafe CSV fixture; it may preview, but formula-like values must remain visible inert
   text rather than executing.
5. Sign in as Alice. The navigation link must be absent; direct navigation returns home without an
   admin API request, and direct backend calls return a safe denial.
6. Cancel a deletion and confirm no API mutation occurs. Then confirm deletion and verify the
   document disappears immediately and its former preview is HTTP 404.

After approving one PDF and one XLSX, open `/development/search` as each demo user and search a term
present in that user's Finance, Legal, or Shared sources. Record returned document/chunk IDs:

- Alice: Orion Finance + Shared only.
- Leo: Orion Legal + Shared only.
- Maya: Orion Finance + Legal + Shared only.
- Amir: Atlas Finance + Shared only.
- Lina: Atlas Legal + Shared only.
- Nora: no search navigation; direct UI navigation returns home and direct API access is HTTP 403.

Confirm every result shows version/chunk/document IDs, keyword/vector/final scores, copied ACL
metadata, citation excerpt/title/version, and either PDF page or spreadsheet sheet/row/cell
provenance. Citation IDs, excerpt, version, and location must equal the enclosing result. Approve a
new version and confirm only its READY chunks remain active while old rows are STALE with cleared
vectors. Reject another candidate and confirm it creates no eligible chunks. Delete the document and
confirm search returns no chunks from it immediately. The browser must never display a candidate
outside the server-returned result list.

API form for a deterministic smoke search:

```bash
curl --fail-with-body -X POST http://127.0.0.1:8000/api/development/authorized-search \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"query":"synthetic","top_k":20}'
```

The response must identify `nomic-embed-text:v1.5`, 768 dimensions, embedding counts, and the
separate scores. The current backend must report:

```json
{"status":"not_run"}
```

for `evaluation_summary`; do not record a Recall@5 result until a real curated dataset is added and
executed.

## Existing-chunk reindex smoke test

Migration `0005` leaves pre-existing Step 4 chunks `PENDING`, and hybrid search excludes them. Sign
in as Nora, capture her bearer token without logging or committing it, and run:

```bash
curl --fail-with-body -X POST http://127.0.0.1:8000/api/development/reindex-embeddings \
  -H "Authorization: Bearer $NORA_ACCESS_TOKEN"
```

Repeat until `processed_chunk_count` is zero; each call processes at most
`EMBEDDING_MAX_CHUNKS`. Then inspect only safe operational metadata:

```bash
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT embedding_status, count(*) FROM document_chunks GROUP BY embedding_status ORDER BY embedding_status;"
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT count(*) AS invalid_ready_rows FROM document_chunks WHERE embedding_status = 'READY' AND (embedding IS NULL OR embedding_dimensions IS DISTINCT FROM 768 OR embedding_model_name IS DISTINCT FROM 'nomic-embed-text' OR embedding_model_version IS DISTINCT FROM 'v1.5' OR embedding_chunk_hash IS DISTINCT FROM content_hash);"
```

The invalid READY count must be zero. Repeat the reindex request once more and expect zero processed
rows. Alice's token must receive HTTP 403. A pending row whose copied ACL no longer equals its
authoritative document/department must remain unprocessed. Search as the appropriate query user
before and after the backfill: the pending row is absent before and eligible after.

## Curated retrieval gate

`app/retrieval/evaluation.py` contains checked-in synthetic ground-truth cases. Exact curated queries
produce a completed summary derived from actual authorized top-five candidates; the integration
gate records Recall@5 `1.0`, one expected hit, and zero authorization leaks for the exercised PDF
case. Unit tests cover all configured cases and scope-mismatch counting. Ad hoc queries return
`not_run`. The current evidence does not justify adding a reranker.

Use an API client to add forged tenant, user, role, department, and company fields to login. The body
must fail with safe `validation_error`. Add the same values as `/api/auth/me` query parameters or
headers; the response must remain the database-derived user. A malformed or expired bearer token
must return `invalid_session`.

## Failure interpretation

- `/health` fails: the API process or network path is unavailable.
- `/health` passes and `/ready` fails: PostgreSQL, credentials, the port, or migration environment is
  unavailable.
- Unit tests pass but the browser fails: confirm `VITE_API_BASE_URL` and backend CORS origins.
- Alembic upgrade fails on `vector`: confirm the Compose image is the pgvector image, not plain
  PostgreSQL.
- Login returns `invalid_credentials`: confirm the development seed ran with the same local password.
- `/api/auth/me` returns `invalid_session`: sign in again, then confirm user and membership status in
  PostgreSQL.
- Upload returns `unsupported_document`: confirm the extension, declared MIME, signature, and file
  safety; renaming a file does not change its detected type.
- Upload returns `unsafe_document`: inspect only the stable error code/request ID in the client and
  server metadata-only logs; do not log the source file to diagnose it.
- Preview returns `preview_unavailable`: poll the ingestion job and inspect its safe terminal status.
- Admin routes return 403/404: confirm the current database `MANAGE_UPLOADS` grant for the exact
  workspace/company. Do not infer authority from the UI or JWT.
- Approval/search/reindex returns `embedding_unavailable`: confirm the loopback Ollama service and
  exact `nomic-embed-text:v1.5` model, then check only safe request IDs and metadata-only logs. Do not
  log provider bodies, query text, vectors, or document chunks.
- Search returns no result for migrated documents: inspect authorized embedding status counts; run
  the bounded Nora reindex flow until it reports zero. Do not make pending rows searchable by
  weakening status, model, hash, ACL, or lifecycle predicates.
- Search returns HTTP 503 while keyword data exists: the implementation intentionally fails closed
  when query embedding is unavailable; it has no keyword-only fallback.
- Evaluation displays `Not run`: this is the current expected backend state, not a UI failure. The
  curated evaluation acceptance criterion remains open.
