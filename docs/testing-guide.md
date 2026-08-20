# Step 3 Testing Guide

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

The suite includes all Step 1/2 regressions plus document state-machine units, real PDF/XLSX/CSV
parsing, malicious container/signature/MIME cases, storage confinement and permissions, formula
inertness, PostgreSQL-backed upload/preview/approval/rejection/version/deletion flows, safe audit
records, idempotency, and direct backend authorization. PostgreSQL-backed tests refuse any database
not named `portfolio_test`.

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
errors, previews with coordinates, inert unsafe strings, decisions, filtering/version upload, and
deletion confirmation.

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
uv run alembic downgrade 20260820_0002
uv run alembic upgrade head
DEMO_USER_PASSWORD='<same password>' uv run python -m app.scripts.seed_development
```

Confirm the extension and Step 3 tables after the final upgrade:

```bash
cd ..
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
docker compose exec -T db psql -U portfolio -d portfolio \
  -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND (tablename LIKE 'document%' OR tablename LIKE 'parsed_%') ORDER BY tablename;"
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
