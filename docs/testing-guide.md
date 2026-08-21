# Step 9 + Interview Features Testing Guide

Run commands from the locations shown. Tests use only synthetic identities and an isolated tmpfs
PostgreSQL test service. On 2026-08-21 these commands passed with 298 backend tests and 98
frontend tests. Automated tests configure deterministic fake embedding, LLM, Perception, Decision,
and MCP adapters and require neither Ollama, a live model provider, a provider key, nor network access.

## Focused deterministic router checks

```bash
cd backend
uv run pytest -q \
  tests/unit/model_routing \
  tests/unit/chat/test_model_router.py \
  tests/unit/test_ollama_qwen_provider.py \
  tests/unit/test_runpod_kimi_provider.py \
  tests/security/test_chat_security.py \
  tests/security/test_agent_security.py
```

These tests prove deterministic simple/complex/multi-document/low-confidence/agentic selection,
one-way fallback, exact authorized-request reuse, pinned Qwen transport, no tools or thinking,
strict output validation, content-free failures, and Kimi-only agent stages/finalization.

## Focused scoped-memory checks

```bash
cd backend
uv run pytest -q \
  tests/unit/memory \
  tests/integration/test_scoped_memory.py \
  tests/integration/test_grounded_chat.py \
  tests/security/test_chat_security.py

cd ../frontend
npm test -- --run src/api/memory.test.ts src/pages/MemoryPage.test.tsx src/App.test.tsx
```

These checks prove private-user/Finance/Legal/Shared isolation across users, departments, companies,
and tenants; rejection of forged ACL/owner fields and source widening; expiry, soft deletion, and
source-revocation behavior; authorization before full-text ranking; prompt-injection containment;
metadata-only logging; strict client parsing; and inspector/delete behavior. Validate migration
`0008` with `0006 -> 0008 -> 0007 -> 0008` plus `uv run alembic check`.

## Focused deterministic calculator checks

```bash
cd backend
uv run pytest -q \
  tests/unit/calculations \
  tests/unit/mcp_gateway \
  tests/unit/agent_loop \
  tests/security/test_agent_security.py \
  tests/integration/test_deterministic_calculations.py \
  tests/integration/test_agent_runs.py

cd ../frontend
npm test -- --run src/api/chat.test.ts src/pages/ChatPage.test.tsx
```

These checks prove exact EBITDA margin, revenue growth, and net profit margin results; fixed
formulas; input units and cell citations; host-only arithmetic/finalization; current Finance/company
reauthorization; and fail-closed missing, malformed, zero-denominator, unauthorized, ambiguous, and
model-forged numeric/scope cases. Calculators need no migration because inputs remain governed
parsed cells and results are response-only.

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

Step 7 coverage adds request-specific MCP catalog filtering, startup manifest drift,
unknown/unshortlisted tools, SDK coercion rejection, forged scope keys, malformed input/output,
timeout/transient/permanent/denial retry behavior, real authorized excerpt provenance, and official
in-process MCP structured output. Step 8 coverage adds bounded typed Perception, safe step-result
inputs, manifest-derived Decision descriptors, provider-schema derivation, exact per-tool actions,
versioned plan text, first-pending-step order, immutable completed history, replay prevention, every
explicit terminal path, step/replan/rewrite/duration limits, unflagged-plan-change counting, prompt
injection, trace smuggling/redaction, and final citation preservation.

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

Step 8 frontend coverage adds the explicit agent submit mode, bounded loading/cancellation, strict
agent envelope/terminal invariants, completed-only citation graphs, sanitized timeline rendering,
evidence drawer links, and rejection of extra sensitive keys, non-UUID event IDs, non-`ev_N`
references, non-approved action names, and non-allow-listed reason/stopping codes.
Step 9 coverage adds strict calculation envelopes, formulas, trusted inputs/units, calculation-to-
citation graph validation, accessible breakdown cards, exact results, and evidence-drawer links.

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
document injection remains quoted untrusted JSON; provider configuration has no tools; a transient,
malformed, or incomplete Kimi response gets no more than one retry; citations are
rebuilt only from retrieved provenance; malformed/fabricated references abstain; and logs do not
contain key, question, excerpt, prompt, answer, provider body, or reasoning markers.

## Focused Steps 7 and 8 checks

Run the deterministic orchestration, MCP, security, database integration, and UI groups directly:

```bash
cd backend
TEST_DATABASE_URL=postgresql+asyncpg://portfolio:portfolio_test@127.0.0.1:5433/portfolio_test \
  uv run pytest \
    tests/unit/agent_loop \
    tests/unit/mcp_gateway \
    tests/security/test_agent_security.py \
    tests/integration/test_agent_runs.py

cd ../frontend
npm run test -- --run \
  src/api/chat.test.ts \
  src/pages/ChatPage.test.tsx \
  src/ChatRouting.test.tsx
```

The backend group proves the official SDK `Client(MCPServer)` path, production gateway bridge,
startup catalog validation, strict raw JSON before SDK conversion, database reauthorization,
bounded state transitions, no-retry denial, safe trace projection, and citation preservation. The
frontend group proves the trace accepts only host-issued identifiers/allowlists and renders no raw
prompt, query, argument, scope, evidence, error, or reasoning field.

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
Steps 7 and 8 add no Alembic revision, so the identical `0006 -> 0005 -> 0006` cycle is their
cumulative migration gate.

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

## Live Runpod Kimi provider check

This is separate from automated tests. Put `RUNPOD_API_KEY` only in the ignored root `.env`; never
place it in a command, argument, log statement, test fixture, or captured artifact. Settings must
retain `LLM_PROVIDER=runpod`, the exact base URL
`https://api.runpod.ai/v2/moonshot-kimi/openai/v1`, model `kimi-k3`, and at least 1,024 output tokens.

Run the checked-in content-free contract smoke from `backend`:

```bash
uv run python -m app.scripts.live_runpod_kimi_smoke
```

It exercises initial Perception and Decision, feeds a synthetic successful authorized observation
through step-result Perception and mid-session Decision, then runs grounded finalization. It prints
only provider/model identifiers, enum metadata, plan/claim counts, citation validity, and retry
count—never the key, question, prompts, evidence, answer text, token counts, provider body, or
`reasoning_content`.

The verified 2026-08-21 run returned valid financial Perception, a valid two-step Decision selecting
`portfolio.search_authorized_documents`, sufficient step-result Perception, a valid mid-session
`FINALIZE`, and `final_status=supported` with one cited claim, `final_claims_cited=true`, and
`final_retry_count=0`. This proves live endpoint/model connectivity and both modes of the structured
stages plus finalization for one synthetic case. It does not prove broad faithfulness, latency,
cost, or availability. Never substitute fake output for this live gate.

## Live dual-model router check

Keep the pinned Mac Ollama endpoint running with `qwen3:8b`, retain the ignored local Runpod key,
select `LLM_PROVIDER=router`, and run from `backend`:

```bash
uv run python -m app.scripts.live_model_router_smoke
```

The first synthetic authorized request must report `qwen3:8b/SIMPLE_LOW_RISK`; the second must
report `kimi-k3/MULTI_DOCUMENT`. Output is bounded metadata only and must contain no credential,
question, evidence, answer, token count, provider payload, or reasoning.

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
   these recognizable targets call neither retrieval nor the model.
4. Leo cannot post to Alice's conversation and receives the same safe 404 as a random UUID. Nora
   receives 403 for her own conversation message because she lacks `QUERY_DOCUMENTS`, before
   retrieval or the model.

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

## Bounded agent and MCP manual gate

With the same owned conversation and synthetic approved evidence, run:

```bash
curl --fail-with-body -X POST \
  "http://127.0.0.1:8000/api/conversations/$CONVERSATION_ID/agent-runs" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"content":"What drove Margin Compression for Orion?"}'
```

Expect `terminal_status=completed`, one tool step, non-empty claims/citations, a final `terminal`
event with `status=completed`, and this logical timeline: initial Perception, policy binding,
capability-filtered MCP catalog, Decision, gateway validation, tool, structured observation,
step-result Perception, Decision/finalization, terminal. Every claim ID must resolve to a returned
`ev_N` citation. Trace objects must contain only `event_id`, `event_type`, `action_name`, `status`,
`duration_ms`, `evidence_reference_ids`, and `reason_code`.

Then submit `show me Orion legal contracts` as Alice. Expect `refused/scope_denied`, zero steps, no
claims/citations, and policy/terminal events only. Leo must receive the same safe 404 for Alice's
conversation as for a random UUID. The automated gateway tests additionally call both document
tools, inspect a one-tool request catalog, attempt an unknown/unshortlisted/malformed/forged call,
and prove no adapter execution on prevalidation denial.

Do not treat the returned timeline as internal state. It must contain no question, prompt,
Perception fields, plan text, tool arguments, authorization data, excerpt, answer, path, raw error,
secret, or chain-of-thought. The detailed trace is response-only and is not reloadable after page
refresh.

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
- Chat returns `llm_unavailable`/HTTP 503: confirm the ignored `.env` selects Runpod and has a local
  key, then rerun only the content-free synthetic provider smoke. The service intentionally has no
  partial answer or alternate ungrounded fallback.
- A conversation remains after reload but its transcript is empty: this is the honest Step 6 API
  limitation. Conversation/message persistence exists, but message-history retrieval and memory do
  not.
- An agent run ends `limit_reached`: inspect only the safe stopping reason (`max_steps`,
  `max_retrieval_rewrites`, `max_replans`, or `duration`). Do not increase bounds to repair a model
  plan; verify the deterministic state transition and authorized evidence path.
- An agent run ends `refused/scope_denied`: confirm the current database grants and recognizable
  target. Unknown/unshortlisted tools and authorization denials intentionally execute no further
  tool attempt.
- An agent run ends `failed/tool_error|model_error`: inspect request/session IDs and safe reason
  codes only. Do not log prompts, queries, MCP arguments/results, evidence, provider bodies, or raw
  exceptions.
