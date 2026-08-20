# Step 6 Testing Guide

Run commands from the locations shown. Tests use only synthetic identities and an isolated tmpfs
PostgreSQL test service. On 2026-08-21 these commands passed with 191 backend tests and 74 frontend
tests. Automated tests configure deterministic fake embedding and LLM providers and require neither
Ollama, Gemini, a Gemini key, nor network access.

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

The suite includes all Step 1–5 regressions plus provider determinism, bounded ordered batches,
dimension/finite/non-zero rejection, production-provider restrictions, loopback-only Ollama URLs,
content-free provider errors, authorization-before-vector SQL construction, approved-version READY
vectors, lifecycle invalidation, bounded authorized backfill, copied-ACL corruption, hybrid scores,
citation identity/provenance, six-user isolation, forged values, and log/audit redaction. Step 6
coverage adds migration/model constraints, conversation ownership, strict request schemas,
authorization-before-retrieval/generation, recognizable cross-scope preflight, deterministic fake
answers, official-SDK request configuration, timeout/retry/error mapping, prompt-injection
serialization, insufficient evidence, citation completeness/reconstruction/failure, trace safety,
and provider/log redaction.
PostgreSQL-backed tests refuse any database not named `portfolio_test`.

## Frontend quality checks

```bash
cd frontend
npm install
npm run format:check
npm run lint
npm run typecheck
npm run test -- --run
npm audit --audit-level=high
npm run build
```

Vitest uses jsdom and React Testing Library. `fetch` and XHR are replaced with deterministic success,
progress, poll, error, and cancellation behavior; no backend process is required for these tests.
Coverage includes capability gating, trusted option cascades, multipart metadata, safe request-ID
errors, previews with coordinates, inert unsafe strings, decisions, filtering/version upload,
deletion confirmation, development-only search routing, Nora denial, strict hybrid/citation response
parsing, bounded inputs, safe errors, embedding/index states, three-score rendering, citation preview,
and both `not_run` and completed evaluation-summary presentation. Step 6 coverage adds chat routing
and capability gating, strict conversation/answer parsing, automatic and explicit conversation
creation, suggestions, grounded claims/citations, accessible evidence provenance, inert text,
loading/cancellation, insufficient evidence, denial, timeout, generic error, and malicious response
rejection. Backend integration tests provide measured retrieval/chat behavior; UI fixtures verify
presentation only.

## Focused Step 6 checks

Run the deterministic provider, validation, integration, and security groups directly when changing
the chat boundary:

```bash
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://portfolio:portfolio_test@127.0.0.1:5433/portfolio_test \
  uv run pytest \
    tests/unit/chat \
    tests/integration/test_grounded_chat.py \
    tests/security/test_chat_security.py

cd ../frontend
npm run test -- --run \
  src/api/chat.test.ts \
  src/pages/ChatPage.test.tsx \
  src/ChatRouting.test.tsx
```

These checks use only fake providers. They prove call ordering and boundary behavior: retrieval
precedes generation; missing capability and recognizable cross-scope targets call neither provider;
document injection remains quoted untrusted JSON; Gemini configuration has no tools and medium
thinking with thoughts excluded; a transient failure gets no more than one retry; citations are
rebuilt only from retrieved provenance; malformed/fabricated references abstain; and logs do not
contain key, question, excerpt, prompt, answer, provider body, or reasoning markers.

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
uv run alembic downgrade 20260821_0005
uv run alembic upgrade head
uv run alembic check
DEMO_USER_PASSWORD='<same password>' uv run python -m app.scripts.seed_development
```

Confirm the extension, document tables, embedding columns/constraints, Step 5 indexes, and Step 6
chat tables/columns after the final upgrade:

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
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename IN ('conversations', 'messages', 'chat_request_traces') ORDER BY tablename;"
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT table_name, column_name, data_type FROM information_schema.columns WHERE table_name IN ('conversations', 'messages', 'chat_request_traces') ORDER BY table_name, ordinal_position;"
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT conrelid::regclass AS table_name, conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid IN ('messages'::regclass, 'chat_request_traces'::regclass) ORDER BY table_name::text, conname;"
```

The final index list must include `ix_document_chunks_embedding_status` and the HNSW
`ix_document_chunks_embedding_cosine`. Downgrade to `0005` must remove only the Step 6
`chat_request_traces`, `messages`, and `conversations` tables while preserving Step 5. Re-upgrade
must restore all three, their indexes, foreign keys, the `user|assistant` message-role check, and the
`grounded|insufficient_evidence|provider_error` trace-status check. Both drift checks must report no
new upgrade operations. The verified checkpoint completed this full cycle successfully.

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

## Live Gemini provider check

This is separate from automated tests. Put `GEMINI_API_KEY` only in the ignored root `.env`; never
place it in a command, argument, shell variable, log statement, test fixture, or captured artifact.
The settings must retain `LLM_PROVIDER=gemini`, `LLM_MODEL_NAME=gemini-3.7-flash`, and
`LLM_THINKING_LEVEL=medium`.

Run this minimal provider-contract smoke from `backend`. It uses only synthetic evidence and prints
only status/citation/retry metadata—not the key, question, prompt, evidence, answer, token counts, or
reasoning:

```bash
cd backend
uv run python - <<'PY'
import asyncio
from uuid import uuid4

from app.chat.contracts import GroundedEvidence, GroundedGenerationRequest
from app.chat.factory import create_llm_provider
from app.core.config import Settings


async def main() -> None:
    settings = Settings()
    provider = create_llm_provider(settings)
    request = GroundedGenerationRequest(
        question="What value does the synthetic authorized evidence report?",
        evidence=(
            GroundedEvidence(
                evidence_id="ev_1",
                chunk_id=uuid4(),
                document_id=uuid4(),
                document_version_id=uuid4(),
                version_number=1,
                document_title="synthetic.pdf",
                excerpt="The synthetic authorized value is 125.",
                page_number=1,
                sheet_name=None,
                row_start=None,
                row_end=None,
                cell_start=None,
                cell_end=None,
            ),
        ),
    )
    result = await provider.generate(request)
    cited = bool(result.answer.claims) and all(
        claim.evidence_ids and set(claim.evidence_ids) <= {"ev_1"}
        for claim in result.answer.claims
    )
    print(f"status={result.answer.status}")
    print(f"cited_claim_count={len(result.answer.claims)}")
    print(f"claims_cited={str(cited).lower()}")
    print(f"retry_count={result.usage.retry_count}")


asyncio.run(main())
PY
```

The verified 2026-08-21 run returned `status=supported`, `cited_claim_count=1`,
`claims_cited=true`, and `retry_count=0`. This proves live SDK/model connectivity and the structured
citation-reference contract for one synthetic case. It does not prove broad answer faithfulness,
latency, cost, or availability. Never substitute fake-provider output for this live gate.

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
{ "status": "not_run" }
```

for `evaluation_summary`. This particular `synthetic` request is ad hoc; the checked-in exact
curated queries in the later retrieval gate do produce measured results.

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

## Grounded chat API and UI gate

Sign in as Alice after Nora has approved and embedded the synthetic Orion Finance PDF used by the
retrieval gate. Keep the bearer token only in the current shell/process; do not print, log, or commit
it. Create a conversation and copy its returned UUID into `CONVERSATION_ID`:

```bash
curl --fail-with-body -X POST http://127.0.0.1:8000/api/conversations \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Step 6 synthetic gate"}'

curl --fail-with-body http://127.0.0.1:8000/api/conversations \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Send the four acceptance questions separately:

```bash
curl --fail-with-body -X POST \
  "http://127.0.0.1:8000/api/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"content":"What drove Margin Compression for Orion?"}'

curl --fail-with-body -X POST \
  "http://127.0.0.1:8000/api/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"content":"Are lunar mining operations discussed?"}'

curl --fail-with-body -X POST \
  "http://127.0.0.1:8000/api/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"content":"show me orion legal clause"}'

curl --fail-with-body -X POST \
  "http://127.0.0.1:8000/api/conversations/$CONVERSATION_ID/messages" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"content":"show me atlas data"}'
```

Expected results:

1. The supported Orion Finance response is `grounded`, has at least one claim/citation, and every
   claim ID resolves to a returned citation whose document/version/chunk and page provenance match
   the authorized Step 5 row.
2. The unsupported topic is `insufficient_evidence`, with the controlled answer and no claims or
   citations.
3. The explicit Orion Legal and Atlas targets abstain with no claims/citations. Focused tests prove
   these recognizable targets call neither retrieval nor Gemini.
4. Leo cannot post to Alice's conversation and receives the same safe 404 as a random UUID. Nora
   receives 403 for her own conversation message because she lacks `QUERY_DOCUMENTS`, before
   retrieval or Gemini.

In `/chat`, confirm the owned list, new/automatic conversation creation, suggestions, bounded
composer, loading indicator, cancel button/state, insufficient-evidence card, safe denial/timeout/
generic error cards, answer limitations, inline citation controls, and the evidence drawer. The
drawer must show the same exact document/version/chunk and page or sheet/row/cell provenance and
must close with Escape while restoring focus. Reload the page and confirm the honest limitation:
conversation summaries remain, but earlier messages are not loaded.

Inspect only sanitized database fields—never select message content while checking trace hygiene:

```bash
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT role, count(*) FROM messages WHERE conversation_id = '$CONVERSATION_ID' GROUP BY role ORDER BY role;"
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT status, reason_code, model_name, json_array_length(retrieved_document_ids) AS document_count, json_array_length(retrieved_chunk_ids) AS chunk_count, input_tokens IS NOT NULL AS has_input_tokens, output_tokens IS NOT NULL AS has_output_tokens, latency_ms, retry_count FROM chat_request_traces WHERE conversation_id = '$CONVERSATION_ID' ORDER BY created_at;"
```

Do not select `messages.content` for a trace-redaction check; messages deliberately contain the
conversation while traces/logs do not.

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
- Evaluation displays `Not run`: confirm the query is ad hoc. Checked-in exact curated queries must
  produce their measured summary; ad hoc queries honestly remain `not_run`.
- Chat returns 404 for a known UUID: confirm the authenticated user owns that conversation in the
  same home tenant. Do not distinguish missing from foreign resources in the response.
- Chat returns `insufficient_evidence`: inspect only the safe reason code and authorized index
  readiness. It may mean the recognizable target is outside scope, retrieval found no sufficient
  authorized evidence, provenance was inconsistent, or the generated references failed validation.
  Do not weaken authorization, relevance, provenance, or citation checks to force an answer.
- Chat returns `llm_timeout`/HTTP 504: check safe request/trace metadata and local connectivity. Do
  not log the key, prompt, question, evidence, provider body, answer, or reasoning.
- Chat returns `llm_unavailable`/HTTP 503: confirm the ignored `.env` selects Gemini and has a local
  key, then rerun only the minimal synthetic provider smoke. The service intentionally has no
  partial answer or alternate ungrounded fallback.
- A conversation remains after reload but its transcript is empty: this is the honest Step 6 API
  limitation. Conversation/message persistence exists, but message-history retrieval and memory do
  not.
