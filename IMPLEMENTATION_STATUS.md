# Implementation Status

## Current milestone

Playbook Step 1 / PRD Milestone 0 — repository scaffold and development harness.

## Completed acceptance criteria

- FastAPI application exposes process health and database readiness endpoints.
- Pydantic settings load from environment variables and a safe example file.
- SQLAlchemy 2, Alembic, PostgreSQL, and pgvector development foundations exist.
- Request IDs, structured metadata-only logs, and safe JSON error envelopes are implemented.
- Backend pytest, Ruff, and mypy configuration exists.
- React, TypeScript, Vite, React Router, and the application layout are implemented.
- The frontend displays backend health and safe failure information.
- Vitest and React Testing Library cover frontend success and failure paths.
- Setup, architecture, security, and testing documentation is present.

## Pending acceptance criteria

None within Step 1.

## Verification result

Verified on 2026-08-20:

- Backend: formatting, linting, strict type checking, and 7 pytest tests pass.
- Frontend: formatting, linting, type checking, 2 Vitest tests, and production build pass.
- Compose configuration validates and PostgreSQL reports healthy/accepting connections.
- Alembic upgrade, schema check, downgrade, and final upgrade pass.
- PostgreSQL reports pgvector extension version 0.8.6.
- Live `/health` and database-backed `/ready` both return HTTP 200.
- The Vite development server starts and serves the React entry page.

## Known limitations

- Readiness checks database connectivity only; it does not inspect future domain data.
- The migration creates only the pgvector extension. There are no domain tables.
- The frontend performs a health request on initial page load and has no polling or retry control.
- Local Compose credentials are development-only.
- Authentication, uploads, retrieval, model calls, MCP, memory, and calculations are deliberately absent.

## Test commands

See [docs/testing-guide.md](docs/testing-guide.md) for the complete command set and expected results.

## Next approved milestone

None. Work must stop after Step 1 until the user explicitly approves the next step.
