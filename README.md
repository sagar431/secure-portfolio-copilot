# Secure Portfolio Copilot

A security-first portfolio analysis copilot, currently complete through Playbook Step 4: secure
deterministic chunking and authorized PostgreSQL keyword search. In addition to database-revalidated
identity and governed PDF/XLSX/CSV ingestion, approved versions become provenance-rich chunks shown
through a development-only search inspector. It intentionally contains no embeddings, model, MCP,
memory, calculation, agent, or cloud features.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+ and npm
- Docker with Docker Compose

## One-time setup

From the repository root:

```bash
cp .env.example .env
# Edit .env: choose a 12+ character DEMO_USER_PASSWORD and random JWT_SECRET_KEY.
docker compose up -d db

cd backend
uv sync --all-groups
uv run alembic upgrade head
uv run python -m app.scripts.seed_development

cd ../frontend
npm install
```

The checked-in environment example contains development-only values. Do not use its database
password in a shared or production environment. `.env` is ignored by Git.

## Start the application

Use three terminals from the repository root.

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
Users with `QUERY_DOCUMENTS` see **Authorized search** in development; Nora does not. API
documentation is available at <http://127.0.0.1:8000/docs> in development.

Uploaded bytes are stored under `DOCUMENT_STORAGE_PATH` using generated object keys. Never point
that setting at a repository or shared-data directory. The default `.local/document-storage` path
is ignored by Git.

## Demo identities

| Email | Effective scope |
|---|---|
| `alice@example.com` | Orion Finance + Shared query |
| `leo@example.com` | Orion Legal + Shared query |
| `maya@example.com` | Explicit Orion Finance + Legal + Shared query |
| `amir@example.com` | Atlas Finance + Shared query |
| `lina@example.com` | Atlas Legal + Shared query |
| `nora@example.com` | Platform administration and Orion/Atlas upload management; no query |

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
npm run build
```

Database and migrations:

```bash
docker compose config --quiet
docker compose up -d db
docker compose exec -T db pg_isready -U portfolio -d portfolio

cd backend
uv run alembic upgrade head
uv run alembic check
uv run alembic downgrade 20260821_0003
uv run alembic upgrade head
uv run python -m app.scripts.seed_development

cd ..
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

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
- [Build playbook](docs/CODEX_BUILD_PLAYBOOK%20(1).md)
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

## Security boundary for this milestone

Only synthetic data belongs in this repository. The API does not log request bodies. Unexpected
exceptions become generic JSON errors, while server logs retain an error type and request ID for
diagnosis. JWTs identify only a user subject; every protected request reloads current memberships and
grants. The browser cannot supply effective identity or scope. Passwords use Argon2id, invalid login
errors are generic, and request/audit logs exclude passwords, tokens, request bodies, and query
strings.

Upload, parsing, chunking, and keyword search are local, bounded, deterministic Step 4 capabilities.
The search inspector returns evidence excerpts rather than generated answers. Embeddings,
hybrid/vector retrieval, LLM calls, MCP, memory, calculations, agent code, hard-delete retention
jobs, and AWS require separately approved later steps.
