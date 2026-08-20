# Step 2 Testing Guide

Run commands from the locations shown. Tests use only synthetic identities and an isolated tmpfs
PostgreSQL test service.

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

The suite includes Step 1 regressions plus password/JWT units, policy decisions, six exact identity
scopes, API login and `/me`, generic failures, forged fields, disabled/revoked state, seed
idempotence, and authorization security cases. PostgreSQL-backed tests refuse any database not named
`portfolio_test`.

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

Vitest uses jsdom and React Testing Library. `fetch` is replaced with deterministic success or error
responses; no backend process is required for these tests.

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
uv run alembic downgrade 20260820_0001
uv run alembic upgrade head
DEMO_USER_PASSWORD='<same password>' uv run python -m app.scripts.seed_development
```

Confirm the extension after the final upgrade:

```bash
cd ..
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
```

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
