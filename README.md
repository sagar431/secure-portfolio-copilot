# Secure Portfolio Copilot

A security-first portfolio analysis copilot, complete through Playbook Step 9 plus deterministic
dual-model routing and source-inheriting scoped memory. In addition to
database-revalidated identity, governed PDF/XLSX/CSV ingestion, and authorization-first hybrid
retrieval, it provides both the Step 6 non-agentic grounded chat and a bounded single-agent path.
The agent separates Perception and Decision, invokes five approved document/calculator tools through an
embedded MCP gateway with host-injected authorization, and preserves Step 6 citation validation.
Simple authorized grounded requests use Mac Ollama `qwen3:8b`; complex, multi-document,
low-confidence, and agentic work uses Runpod `kimi-k3`. Private-user, Finance, Legal, and Shared
memory is filtered and source-reauthorized before retrieval. Three fixed financial metrics are
computed from reauthorized spreadsheet cells by host code. The project contains no arbitrary
execution, multi-agent system, or cloud deployment.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and npm
- Docker with Docker Compose
- [Ollama](https://ollama.com/) for the live development embedding smoke test. Automated tests use a
  deterministic fake provider and do not require Ollama.
- A Runpod API key in the ignored local `.env` for live Kimi Perception, Decision, and grounded
  final-answer checks. Automated tests use deterministic fake providers and need no network key.

## One-time setup

From the repository root:

```bash
cp .env.example .env
# Edit .env: choose a 12+ character DEMO_USER_PASSWORD and random JWT_SECRET_KEY.
# Review the local-only Step 5 embedding and Step 6 LLM settings shown below.
docker compose up -d db

cd backend
uv sync --all-groups
uv run alembic upgrade head
uv run python -m app.scripts.seed_development

cd ../frontend
npm install
```

Add these local-only embedding settings to `.env` for the normal development application:

```dotenv
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
EMBEDDING_MODEL_NAME=nomic-embed-text
EMBEDDING_MODEL_VERSION=v1.5
EMBEDDING_DIMENSIONS=768
EMBEDDING_BATCH_SIZE=16
EMBEDDING_MAX_CHUNKS=512
EMBEDDING_TIMEOUT_SECONDS=30
EMBEDDING_OPERATION_TIMEOUT_SECONDS=120
```

`OLLAMA_BASE_URL` accepts only explicit HTTP loopback targets. The model name, version, and
dimensions are fixed by the current schema and validation. `fake` is for deterministic tests only;
`disabled` fails closed. Production accepts only `EMBEDDING_PROVIDER=disabled`, and production does
not register the development search or reindex routes. Since approval currently requires embedding,
document approval also fails closed in production; this branch is a local Step 5 demonstration, not
a production embedding deployment.

Add the model-router settings to the ignored local `.env`:

```dotenv
LLM_PROVIDER=router
RUNPOD_API_KEY=replace-with-a-local-runpod-key
RUNPOD_BASE_URL=https://api.runpod.ai/v2/moonshot-kimi/openai/v1
RUNPOD_MODEL_NAME=kimi-k3
QWEN_BASE_URL=http://192.168.31.213:11434
QWEN_MODEL_NAME=qwen3:8b
QWEN_TIMEOUT_SECONDS=15
QWEN_MAX_OUTPUT_TOKENS=1024
ROUTER_LOW_CONFIDENCE_THRESHOLD=0.55
LLM_TIMEOUT_SECONDS=60
LLM_MAX_OUTPUT_TOKENS=1024
LLM_MAX_EVIDENCE_CHUNKS=5
AGENT_MAX_STEPS=4
AGENT_MAX_REPLANS=1
AGENT_MAX_RETRIEVAL_REWRITES=1
AGENT_MAX_DURATION_SECONDS=90
AGENT_TOOL_TIMEOUT_SECONDS=10
AGENT_TOOL_MAX_TRANSIENT_RETRIES=1
```

Both endpoints and model IDs are fixed by settings validation. Qwen is a development-only LAN
endpoint with tools/thinking disabled and strict structured output. Kimi requires temperature
exactly `1` and at least 1,024 output tokens because reasoning consumes the same output budget. The
adapter deletes `reasoning_content` at the provider boundary, never exposes it, strictly validates
visible JSON with Pydantic, and permits at most two total calls for a transient, malformed, or
incomplete response. Empty content with `finish_reason=length` is incomplete, never success.
`fake` is deterministic test infrastructure and is rejected in production; `disabled` fails closed.
Gemini remains an optional compatible provider. Never pass or print either provider key on a
command line; load it only from the ignored `.env`.

The checked-in environment example contains development-only values. Do not use its database
password in a shared or production environment. `.env` is ignored by Git.

## Start the application

Use three application terminals from the repository root, plus a running local Ollama service for
live hybrid retrieval. Grounded chat additionally requires the local `.env` model configuration.

Database:

```bash
docker compose up -d db
docker compose ps
```

Backend:

```bash
cd backend
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm run dev
```

Open <http://127.0.0.1:3000>. Anonymous users are redirected to login. Development-only cards fill
the email for one of the six synthetic users; enter the local password selected before seeding. The
protected home page displays the current database-derived tenant, role, department, companies,
query departments, and capabilities. Nora also sees **Document ingestion**, where trusted backend
options constrain tenant, company, department, visibility, classification, and document type.
Users with `QUERY_DOCUMENTS` see **Authorized search** in development and **Grounded chat**; Nora
does not. API documentation is available at <http://127.0.0.1:8000/docs> in development.

Uploaded bytes are stored under `DOCUMENT_STORAGE_PATH` using generated object keys. Never point
that setting at a repository or shared-data directory. The default `.local/document-storage` path
is ignored by Git.

## Demo identities

| Email               | Effective scope                                                     |
| ------------------- | ------------------------------------------------------------------- |
| `alice@example.com` | Orion Finance + Shared query                                        |
| `leo@example.com`   | Orion Legal + Shared query                                          |
| `maya@example.com`  | Explicit Orion Finance + Legal + Shared query                       |
| `amir@example.com`  | Atlas Finance + Shared query                                        |
| `lina@example.com`  | Atlas Legal + Shared query                                          |
| `nora@example.com`  | Platform administration and Orion/Atlas upload management; no query |

All users use the local `DEMO_USER_PASSWORD`. This is synthetic development authentication only.

## Health and readiness

- `GET /health` proves the API process can respond. It does not access the database.
- `GET /ready` runs `SELECT 1` against PostgreSQL and returns HTTP 503 if the database is unavailable.
- Both endpoints return a typed JSON envelope and an `X-Request-ID` response header.

```bash
curl -i http://127.0.0.1:8000/health
curl -i http://127.0.0.1:8000/ready
curl -i -H 'X-Request-ID: manual-check' http://127.0.0.1:8000/health
```

## Verification commands

Backend:

```bash
docker compose --profile test up -d test-db
docker compose exec -T test-db pg_isready -U portfolio -d portfolio_test

cd backend
uv run ruff format --check .
uv run ruff check .
uv run mypy app
TEST_DATABASE_URL=postgresql+asyncpg://portfolio:portfolio_test@127.0.0.1:5433/portfolio_test \
  uv run pytest
```

Frontend:

```bash
cd frontend
npm run format:check
npm run lint
npm run typecheck
npm run test -- --run
npm audit --audit-level=high
npm run build
```

The current Step 8 correction passes 263 backend tests and the previously verified 88 frontend
Vitest tests, plus backend format/lint/strict-type gates. Live Runpod Kimi initial/step-result
Perception, initial/mid-session Decision, and grounded final-answer contracts pass against
`kimi-k3`; the final answer contained one host-validatable cited claim with no retry. See the
testing guide for focused fake-provider, MCP/agent/calculator, redaction, migration-cycle, and live
provider checks.

Database and migrations:

```bash
docker compose config --quiet
docker compose up -d db
docker compose exec -T db pg_isready -U portfolio -d portfolio

cd backend
uv run alembic upgrade head
uv run alembic check
uv run alembic downgrade 20260821_0005
uv run alembic upgrade head
uv run alembic check
uv run python -m app.scripts.seed_development

cd ..
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

For the live Step 5 provider check, run `ollama serve` in another terminal (or use the Ollama
desktop service), then run `ollama pull nomic-embed-text:v1.5` in a separate shell before starting
the backend. Run `uv run python -m app.scripts.live_runpod_kimi_smoke` separately from `backend`;
it prints only bounded contract metadata and never prints the key, prompts, evidence, answer text,
token counts, provider body, or reasoning. Automated tests use no live provider.

For the final live dual-route contract check, keep Mac Ollama running with `qwen3:8b` and run from
`backend`:

```bash
uv run python -m app.scripts.live_model_router_smoke
```

The smoke prints only model/route/status/count/latency metadata. It never prints credentials,
questions, evidence, answers, provider bodies, token counts, or model reasoning.

## Deterministic model routing

Routing runs in backend code only after authorization-first retrieval. Simple, high-confidence,
single-document grounded answers use Qwen. Multi-document evidence, low retrieval confidence,
bounded complex/comparison language, and every AgentLoop stage use Kimi. A retryable Qwen timeout,
transport failure, or invalid structured response may fall forward to Kimi using the exact same
authorized evidence. Kimi work never falls back to Qwen, and authorization denial/no-evidence paths
call neither model. Sanitized traces store the actual model and categorical route/fallback reason,
never model rationale or chain-of-thought.

Stop the application processes with `Ctrl+C`. Stop the database without deleting its volume:

```bash
docker compose stop db
```

## Repository map

```text
backend/                 FastAPI, SQLAlchemy, Alembic, and pytest
frontend/                React, TypeScript, Vite, Vitest, and Testing Library
docs/                    Product, architecture, security, and testing documentation
Simulated_data/          Existing synthetic fixtures; untouched by this milestone
compose.yaml             Local pgvector-enabled PostgreSQL
IMPLEMENTATION_STATUS.md Current step acceptance status
LEARNING_NOTES.md        End-to-end learning notes
```

## Documentation

- [Product requirements](docs/PRD.md)
- [Build playbook](<docs/CODEX_BUILD_PLAYBOOK%20(1).md>)
- [Architecture](docs/architecture.md)
- [Security invariants](docs/security-invariants.md)
- [Testing guide](docs/testing-guide.md)
- [Implementation status](IMPLEMENTATION_STATUS.md)
- [Learning notes](LEARNING_NOTES.md)

## Step 3 document workflow

The canonical management page is `/admin/documents`. Backend routes under `/api/admin` provide
trusted form options, upload and explicit new-version operations, ingestion status, version-addressed
preview/approve/reject actions, a scoped management library, and soft deletion. Every route requires
a current database-derived `MANAGE_UPLOADS` grant for the target workspace and company. The UI gate
is only a convenience and never replaces backend authorization.

Files are limited to 10 MiB and are checked by extension, declared MIME type, signature, container
structure, decompression limits, and format-specific safety rules before parsing. PDF previews retain
page numbers; spreadsheet previews retain sheet, row, cell coordinate, value kind, and formula-like
provenance. Formula-like values are rendered as inert text. Approval is legal only from
`PREVIEW_READY`; deletion immediately removes the document from management reads and removes stored
objects while retaining soft-delete metadata for a later retention process.

## Step 4 authorized search workflow

Approval now performs deterministic chunking in the same locked database transaction as the
version transition. PDF chunks never cross a page and split on deterministic heading boundaries.
XLSX/CSV chunks never cross a sheet and group bounded contiguous rows while retaining row and cell
ranges. Every chunk copies tenant, company, department, visibility, classification, document,
version, approval, deletion, and active-version metadata.

`POST /api/development/authorized-search` accepts only a normalized query of at most 500 characters
and `top_k` from 1 through 20. The route exists only when `APP_ENV` is `development` or `test`.
Repository methods require the immutable database-derived `AuthorizationScope`; tenant, company,
department, visibility, classification, approval, deletion, and current active-version predicates
are part of the SQL query before full-text ranking. Responses contain at most 20 bounded
500-character excerpts with chunk/document/version IDs, metadata, provenance, and scores. Search
audits contain IDs and counts, never the query or document text.

Approving a replacement version deactivates the old chunks atomically. Rejected versions never gain
searchable chunks, and deletion deactivates all document chunks before the transaction commits.

## Step 5 embedding and hybrid retrieval workflow

Migration `20260821_0005` adds `vector(768)`, fixed model/version/dimension and content-hash metadata,
`PENDING|READY|FAILED|STALE` state, a status index, and an HNSW cosine index. Existing Step 4 chunks
become `PENDING`. New approvals synchronously generate and validate bounded embedding batches before
publishing the version. The success commit installs `READY` chunks and deactivates prior chunks;
replacement, rejection, and deletion clear affected vectors and mark the rows `STALE`. Provider or
vector validation failure rolls approval/replacement back and returns a generic error.

Search denies callers without `QUERY_DOCUMENTS` before any provider call. It embeds only the query,
then builds `authorized_chunks AS MATERIALIZED` from database-derived grants, copied ACL fields, and
authoritative active/current/approved lifecycle rows. Cosine distance and top-k operate only on that
materialized authorized set. Eligible chunks must be `READY`, use the exact configured
`nomic-embed-text:v1.5` 768-dimensional model, and have an embedded hash equal to `content_hash`.

The deterministic score is 35% normalized PostgreSQL full-text rank plus 65% bounded cosine
similarity, ordered by final score, keyword score, then chunk ID. The response exposes all three
scores and a citation preview with document title, IDs, version, bounded excerpt, and page or
sheet/row/cell provenance. Audits contain permitted IDs, counts, and `top_k`, not query text,
vectors, excerpts, or forbidden candidates.

After applying migration `0005` to a database that already has Step 4 chunks, sign in as Nora and
repeat this bounded request until `processed_chunk_count` is zero:

```bash
curl --fail-with-body -X POST http://127.0.0.1:8000/api/development/reindex-embeddings \
  -H "Authorization: Bearer $NORA_ACCESS_TOKEN"
```

The endpoint has no request body and processes at most `EMBEDDING_MAX_CHUNKS` eligible rows per call.
It rechecks Nora's current `MANAGE_UPLOADS` scope and authoritative lifecycle/ACL equality, and uses
row locks with `SKIP LOCKED`. Query users such as Alice receive HTTP 403.

The search UI displays embedding readiness/counts, keyword/vector/final scores, safe
indexing/degraded states, and citation provenance. Its evaluation area reports measured Recall@5,
expected hits, and authorization leaks for checked-in curated queries; ad hoc queries display
**Not run**.

## Step 6 grounded chat workflow

Migration `20260821_0006` adds owner-scoped `conversations`, persisted `messages`, and sanitized
`chat_request_traces`. Create/list APIs expose conversation summaries; the message API accepts one
normalized question of at most 1,000 characters. A conversation is accessible only to its current
tenant/user owner, and `QUERY_DOCUMENTS` is required before search or generation.

The service performs a deterministic preflight for recognizable unauthorized tenant/company or
department targets, then calls the Step 5 `AuthorizedSearchService`. Only sufficient rows returned
through its database-derived authorization and lifecycle filters become prompt evidence. At most
five rows are serialized as `authorized_untrusted_evidence`; document strings are quoted JSON data,
not instructions. The selected adapter requests bounded structured JSON and configures no tools or
tool access. The Runpod path fixes the exact Kimi endpoint/model, temperature `1`, and a minimum
1,024-token output budget; visible output is strictly validated and hidden reasoning is discarded.

The model returns claim text and evidence IDs, not trusted citation objects. Host validation requires
every supported claim to reference retrieved IDs and rebuilds citations from those exact evidence
rows. Unknown, missing, or malformed references fail closed to `insufficient_evidence` with no
claims/citations. Missing evidence and recognized out-of-scope targets also abstain; provider
timeouts/unavailability return generic errors.

The `/chat` page lists the authenticated user's conversations, creates one explicitly or on the
first question, offers bounded suggestions, and renders loading, cancellation, empty,
insufficient-evidence, denial, timeout, and safe-error states. Supported claims have inline citation
buttons opening an accessible evidence drawer with the exact excerpt and provenance. The strict
client validator rejects extra fields, malformed coordinates, mismatched conversation IDs, and
unknown, duplicate, or unreferenced citations.

Step 6 does not provide a message-history read endpoint. Reloaded conversations are listed, but
earlier turns are not loaded or sent back to the model. Scoped long-term memory is a separate,
explicit store; it is not reconstructed from conversation history.

## Scoped memory

`POST /api/memories`, `GET /api/memories`, `POST /api/memories/search`, and
`DELETE /api/memories/{memory_id}` provide bounded create, inspect/search, and soft-delete flows.
The server derives tenant, company, department, user, visibility, and classification from the
current database authorization context and authorized source chunks. Source-free memory must be
`PRIVATE_USER`; sourced Finance, Legal, and Shared memory inherits the source ACL exactly, while a
private sourced memory may narrow visibility without changing its source restriction.

Every read materializes current tenant/company/department/user/classification/expiry policy before
search or display and reauthorizes every source chunk against current document lifecycle state.
Expired, deleted, revoked-source, foreign-tenant, wrong-company, and wrong-department memory is
absent. Memory passed to grounded chat is additionally company-limited to the retrieved evidence,
bounded to five newest items, labeled untrusted and non-evidentiary, and cannot create a citation.
The `/memories` inspector renders only the server-filtered list, supports source-free private
preferences, and exposes deletion only when the server says the current user may delete.

## Deterministic financial calculations

The bounded agent may select exactly one of
`portfolio.calculate_ebitda_margin`, `portfolio.calculate_revenue_growth`, or
`portfolio.calculate_net_profit_margin`. Tool input contains only `company_slug` and
`reporting_period`; model-supplied numbers, formulas, scope, and ownership fields are rejected.
Each invocation reauthorizes the target company and Finance access, starts from materialized
authorized chunks, and reads only literal numeric cells from one currently approved P&L workbook.

Host `Decimal` arithmetic returns the fixed formula, trusted inputs, units, percentage result, and
one exact cell citation per input. Formula-like cells, invalid units, ambiguous workbooks, missing
metrics, and zero denominators fail closed. Successful calculation finalization is deterministic,
so no model calculates or copies the result. The UI renders a strict calculation breakdown card.

## Steps 7 and 8: MCP gateway and bounded agent workflow

`POST /api/conversations/{conversation_id}/agent-runs` preserves the same owner and capability
checks, recognizable scope preflight, authorized evidence, persistence, and final citation rules.
Step 7 owns the embedded MCP boundary. One request owns one typed `AgentSession`; Step 8 adds
separate structured model calls for initial/step-result Perception and initial/mid-session
Decision. Perception observes and classifies only. It records mentioned scope as untrusted hints and
never authorizes, selects a tool, calculates, controls retries, or answers. After a tool step it sees
only the prior snapshot, current plan, immutable completed history, latest structured observation,
and safe remaining budgets.

Decision receives a manifest-derived, capability-filtered catalog containing only each approved
name, purpose, exact tool-specific input schema, and safe result description. It returns a
one-to-three-step plan with matching internal plan text and exactly one typed action; host code—not
the model—executes it. Provider JSON schemas derive from the strict Pydantic contracts and every
response is strictly validated locally.

The embedded official MCP client/server advertises only the request's capability-filtered subset of
the two document tools and three fixed calculator tools. The host validates
raw action JSON before MCP conversion, injects the immutable database-backed scope outside model
arguments, and revalidates it inside each adapter. Startup fails on duplicate names or schema/
capability drift. Unknown tools, forged authorization fields, malformed data, unauthorized IDs,
timeouts, and permanent failures return content-free observations.

The plan-state module requires initial version 1, exact one-version increments for changed plans,
first-pending-step execution, immutable completed history, and no completed-action replay. The loop
allows at most four tool steps, one semantic search rewrite, one replan, one transient tool retry, a
per-tool timeout, and 90 seconds total by default. Every path ends as `completed`,
`refused`, `needs_clarification`, `insufficient_evidence`, `limit_reached`, or `failed`. A completed
answer is accepted only after the Step 6 host citation validator reconstructs all cited provenance.

The `/chat` page keeps **Ask copilot** as the Step 6 default and adds **Run bounded agent**. Agent
turns show a sanitized responsive timeline. Only host UUID event IDs, stage/status, the five approved
tool names, `ev_N` evidence references, durations, counters, and allow-listed reason/stopping codes
are accepted. Prompts, queries, plan text, raw observations, evidence content, scope, paths,
exceptions, secrets, and model reasoning are neither stored nor rendered in that trace.

## Security boundary for this milestone

Only synthetic data belongs in this repository. The API does not log request bodies. Unexpected
exceptions become generic JSON errors, while server logs retain an error type and request ID for
diagnosis. JWTs identify only a user subject; every protected request reloads current memberships and
grants. The browser cannot supply effective identity or scope. Passwords use Argon2id, invalid login
errors are generic, and request/audit logs exclude passwords, tokens, request bodies, and query
strings.

Upload, parsing, chunking, embedding, hybrid retrieval, grounded chat, and bounded orchestration are
controlled capabilities. The embedding model contributes similarity only. The selected model may classify,
plan one typed next action, and draft claims from authorized evidence, but deterministic code owns
authorization, catalogs, execution, lifecycle, evidence, limits, terminal states, citations,
persistence, and audit metadata. No model tools are configured; tool execution occurs only through
the host MCP gateway. Logs/traces exclude questions, prompts, excerpts, answers, provider bodies,
keys, and hidden reasoning; conversation `messages` intentionally persist the user's question and
the controlled assistant answer.

Broad semantic entailment, reranking, message-history loading, trace persistence,
automated retention jobs, arbitrary code, remote/dynamic MCP, production embedding
infrastructure, and AWS remain absent.
