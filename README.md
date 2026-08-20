# Secure Portfolio Copilot

A security-first portfolio analysis copilot, currently complete through Playbook Step 2: identity,
tenancy, departments, and deterministic authorization. It provides development-only password login,
short-lived JWTs, database-revalidated memberships, strict authorization scopes, reason-coded
RBAC/ABAC policy, and a protected React scope view. It intentionally contains no document
processing, retrieval, model, MCP, memory, calculation, agent, or cloud features.

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
query departments, and capabilities. API documentation is available at
<http://127.0.0.1:8000/docs> in development.

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
uv run alembic downgrade 20260820_0001
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
IMPLEMENTATION_STATUS.md Current milestone acceptance status
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

## Security boundary for this milestone

Only synthetic data belongs in this repository. The API does not log request bodies. Unexpected
exceptions become generic JSON errors, while server logs retain an error type and request ID for
diagnosis. JWTs identify only a user subject; every protected request reloads current memberships and
grants. The browser cannot supply effective identity or scope. Passwords use Argon2id, invalid login
errors are generic, and request/audit logs exclude passwords, tokens, request bodies, and query
strings.

Document upload, parsing, retrieval, embeddings, LLM calls, MCP, memory, calculations, agent code,
and AWS require separately approved later steps.
